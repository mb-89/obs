"""Write a schema-valid Document and deliver it to an executable adapter."""
import argparse
import json
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from functools import cache
from pathlib import Path
from typing import Sequence

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from obs.adapter import (ADAPTER_OPTIONS_OWNER, AdapterError, VaultFile, adapter_manifest_path, load_adapter,
                         option_arguments)
from obs.comments import SCHEMA_PATH as COMMENTS_SCHEMA_PATH, apply_comments
from obs.discriminator import discriminating_validator
from obs.input import InputError, input_error, schema_error
from obs.node_ids import assign_ids
from obs.output import write_output
from obs.sources import SourceError, source_archive, validate_source_archive
from obs.vault import VaultError, build_document as _build_document, manifest_note


DOCUMENT_SCHEMA_PATH = Path(__file__).with_name("document.schema.json")
FIGURE_SCHEMA_PATH = Path(__file__).with_name("figure.schema.json")
ANSWERS_SCHEMA_PATH = Path(__file__).with_name("answers.schema.json")
ANSWERS_OWNER = "input-model#Answers"
PACKAGED_CAPABILITY_REFERENCE = Path(__file__).with_name("capability-reference.json")
"""The capability reference the package ships, written from spec/capabilities by every build
(hatch_build.py); obs-document reads it unless --capability-reference names another."""
CONTRACT_VERSION = 1
STRUCTURAL_NODE_TYPES = frozenset(
    json.loads(DOCUMENT_SCHEMA_PATH.read_text(encoding="utf-8"))["$defs"]["structuralType"]["enum"],
)
"""The node types that are not capability identifiers; the Document schema owns them."""


class DocumentError(ValueError):
    """Raised when a Document violates the neutral contract."""


def build_document(
    manifest_path: Path, reference: dict[str, object], configuration_path: Path | None = None,
    execute_commands: bool = False, embed_source: bool = False, delivery: Sequence[str] = (),
    option_files: Sequence[str] = (), answers: Path | None = None,
) -> dict[str, object]:
    """Parse a vault into a schema-valid neutral Document.

    ``execute_commands`` authorizes running the vault's cmd fences; see capabilities/command-fences.
    ``embed_source`` discloses the vault's source files; see architecture, Source archive.
    ``delivery`` are the call's adapter arguments the archive's build record names before the core's;
    ``option_files`` the vault-relative files its vault-file options name, which the archive holds.
    ``answers`` is a reader's answers file, whose verdicts the chapters that ask carry (input-model#Answers).
    """
    try:
        known = {item["id"] for item in reference["capabilities"]}
        document = _build_document(manifest_path, known, configuration_path, execute_commands)
        assign_ids(document)
        if embed_source:
            arguments = [*delivery, *(["--execute-commands"] if execute_commands else []), "--embed-source"]
            document["sourceArchive"] = source_archive(manifest_path.resolve().parent, document["assets"],
                                                        document["cssSnippets"], arguments, document.get("style"),
                                                        option_files)
        apply_comments(document, manifest_path)
        if answers is not None:
            apply_answers(document, read_answers(answers), answers)
        validate_document(document, reference)
    except (SourceError, VaultError) as error:
        raise DocumentError(str(error)) from error
    return document


def read_answers(path: Path) -> list[dict[str, object]]:
    """The verdicts of an answers file the schema accepts (input-model#Answers)."""
    try:
        answers = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InputError(f"{path}: top level: cannot be read as JSON ({error}). Pass the answers file a "
                         f"served artifact's reader sent; see {ANSWERS_OWNER}.") from error
    error = schema_error(list(_answers_validator().iter_errors(answers)), path, ANSWERS_OWNER)
    if error:
        raise error
    return answers["verdicts"]


@cache
def _answers_validator() -> Draft202012Validator:
    """answers.schema.json's validator, compiled once per process."""
    return Draft202012Validator(json.loads(ANSWERS_SCHEMA_PATH.read_text(encoding="utf-8")))


def apply_answers(document: dict[str, object], verdicts: list[dict[str, object]], path: Path) -> None:
    """Put each verdict on the chapter that asks: its answer at the chapter's version, else outdated."""
    asking = {chapter["id"]: chapter for chapter in _all_chapters(document["chapters"]) if "bless" in chapter}
    answered: dict[str, int] = {}
    for index, verdict in enumerate(verdicts):
        field, chapter_id = f"verdicts[{index}].chapter", verdict["chapter"]
        if chapter_id not in asking:
            raise input_error(path, field, f"names {chapter_id!r}, which asks for no bless in this Document",
                              f"Drop the verdict, or ask with obs.bless: pending in that note; see {ANSWERS_OWNER}")
        if chapter_id in answered:
            raise input_error(path, field, f"answers {chapter_id!r} a second time, after verdicts[{answered[chapter_id]}]",
                              f"Keep one verdict per chapter; see {ANSWERS_OWNER}")
        answered[chapter_id] = index
        request = asking[chapter_id]["bless"]
        request["answer" if verdict["version"] == request["version"] else "outdated"] = verdict


def _all_chapters(chapters: list[dict[str, object]]):
    for chapter in chapters:
        yield chapter
        yield from _all_chapters(chapter["children"])


def read_capability_reference(path: Path) -> dict[str, object]:
    try:
        reference = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise DocumentError(f"Invalid capability reference {path}: {error}") from error
    capabilities = reference.get("capabilities") if isinstance(reference, dict) else None
    if reference.get("schemaVersion") != CONTRACT_VERSION or not isinstance(capabilities, list):
        raise DocumentError(f"Invalid capability reference {path}.")
    if any(not isinstance(item, dict) or not isinstance(item.get("id"), str)
           or not isinstance(item.get("dependsOn"), list) for item in capabilities):
        raise DocumentError(f"Invalid capability reference {path}.")
    return reference


@cache
def document_validators() -> tuple[Draft202012Validator, dict[str, Draft202012Validator]]:
    """document.schema.json's validator and one per figure body kind ($defs/figureBodies), compiled
    once per process, with figure.schema.json, answers.schema.json and comments.schema.json registered."""
    schema = json.loads(DOCUMENT_SCHEMA_PATH.read_text(encoding="utf-8"))
    registry = Registry().with_resources([
        (FIGURE_SCHEMA_PATH.name, Resource.from_contents(json.loads(FIGURE_SCHEMA_PATH.read_text(encoding="utf-8")))),
        (ANSWERS_SCHEMA_PATH.name, Resource.from_contents(json.loads(ANSWERS_SCHEMA_PATH.read_text(encoding="utf-8")))),
        (COMMENTS_SCHEMA_PATH.name,
         Resource.from_contents(json.loads(COMMENTS_SCHEMA_PATH.read_text(encoding="utf-8")))),
    ])
    bodies = {
        kind: Draft202012Validator({**body, "$defs": schema["$defs"]}, registry=registry)
        for kind, body in schema["$defs"]["figureBodies"].items()
    }
    return discriminating_validator(schema)(schema, registry=registry), bodies


def validate_document(document: dict[str, object], reference: dict[str, object]) -> None:
    try:
        validator, bodies = document_validators()
        errors = list(validator.iter_errors(document))
    except ValueError as error:
        raise DocumentError(f"Invalid Document: {error}") from error
    error = schema_error(errors, "Invalid Document", "src/obs/document.schema.json")
    if error:
        raise DocumentError(str(error)) from None
    error = validate_source_archive(document)
    if error:
        raise DocumentError(error)
    known = {item["id"] for item in reference["capabilities"]}
    unknown = sorted(set(document["capabilities"]) - known)
    if unknown:
        raise DocumentError(f"Document uses unknown capabilities: {', '.join(unknown)}.")
    _validate_node_capabilities(document["manifest"].get("abstract", []), known, bodies)
    for chapter in document["chapters"]:
        _validate_node_capabilities(chapter["content"], known, bodies)
        _validate_chapter_capabilities(chapter["children"], known, bodies)


def _validate_chapter_capabilities(
    chapters: list[object], known: set[str], bodies: dict[str, Draft202012Validator],
) -> None:
    for chapter in chapters:
        _validate_node_capabilities(chapter["content"], known, bodies)
        _validate_chapter_capabilities(chapter["children"], known, bodies)


def _validate_node_capabilities(
    nodes: list[object], known: set[str], bodies: dict[str, Draft202012Validator],
) -> None:
    for node in nodes:
        if node["type"] not in STRUCTURAL_NODE_TYPES | known:
            raise DocumentError(f"Document node uses unknown capability: {node['type']}.")
        if node["type"] == "figures":
            _validate_figure_body(node, bodies)
            continue
        _validate_node_capabilities(node["children"], known, bodies)


def _validate_figure_body(node: dict[str, object], bodies: dict[str, Draft202012Validator]) -> None:
    """A figure's one child is its kind's body; see document.schema.json ($defs/figureBodies)."""
    [body] = node["children"]
    kind = node["attrs"]["kind"]
    owner = "src/obs/document.schema.json ($defs/figureBodies)"
    if body["type"] != kind or kind not in bodies:
        raise DocumentError(
            f"Invalid Document: a {kind} figure's body is of type {body['type']!r}; its type is the "
            f"figure's kind, one of {', '.join(sorted(bodies))}. See {owner}.")
    error = schema_error(list(bodies[kind].iter_errors(body["attrs"])), "Invalid Document", owner,
                         field=f"figure body {kind}")
    if error:
        raise DocumentError(str(error)) from None


def read_document(path: Path, reference: dict[str, object]) -> dict[str, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DocumentError(f"Invalid Document {path}: {error}") from error
    validate_document(document, reference)
    return document


def write_document(document: dict[str, object], path: Path, reference: dict[str, object]) -> None:
    validate_document(document, reference)
    _write(document, path)


def _write(document: dict[str, object], path: Path) -> None:
    write_output(path, json.dumps(document, indent=2) + "\n")


def call_adapter(adapter_name: str, configuration_path: Path, document_path: Path,
                 destination: Path, capability_reference_path: Path, options: Sequence[str] = ()) -> None:
    adapter, arguments = _adapter(adapter_name, configuration_path, options)
    reference = read_capability_reference(capability_reference_path)
    _deliver(adapter, arguments, configuration_path, read_document(document_path, reference), document_path,
             destination, reference)


def _adapter(name: str, configuration_path: Path, options: Sequence[str]) -> tuple[dict[str, object], list[str]]:
    """The adapter's manifest and the arguments its declared ``options`` give."""
    adapter = load_adapter(name, configuration_path)
    return adapter, option_arguments(adapter, adapter_manifest_path(name, configuration_path), list(options))


def _deliver(adapter: dict[str, object], arguments: list[str], configuration_path: Path,
             document: dict[str, object], document_path: Path, destination: Path,
             reference: dict[str, object], label: str = "") -> None:
    """Start the adapter on the validated ``document``, which ``document_path`` holds, with the
    standard ``arguments`` (``--vault-root``) and its options' arguments after DESTINATION. On
    success its stderr lines follow on ours, each after ``label`` and its name (cli.md, One-call build)."""
    adapter_name = adapter["name"]
    if adapter["contractVersion"] != document["schemaVersion"]:
        raise AdapterError(
            f"Adapter {adapter_name!r} contract version {adapter['contractVersion']} does not "
            f"match Document schema version {document['schemaVersion']}."
        )
    required = _capability_closure(set(document["capabilities"]), reference)
    unsupported = sorted(required - set(adapter["capabilities"]))
    if unsupported:
        raise AdapterError(
            f"Adapter {adapter_name!r} does not support Document capabilities: "
            f"{', '.join(unsupported)}."
        )
    try:
        completed = subprocess.run(
            [*adapter["command"], str(document_path.resolve()), str(destination.resolve()), *arguments],
            cwd=configuration_path.parent,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise AdapterError(f"Cannot start adapter {adapter_name!r}: {error}") from error
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        suffix = f": {detail}" if detail else ""
        raise AdapterError(f"Adapter {adapter_name!r} exited with code {completed.returncode}{suffix}")
    for line in completed.stderr.splitlines():
        if line.strip():
            print(f"{label}{adapter_name}: {line}", file=sys.stderr)


def _capability_closure(requested: set[str], reference: dict[str, object]) -> set[str]:
    dependencies = {item["id"]: set(item["dependsOn"]) for item in reference["capabilities"]}
    required = set(requested)
    pending = list(requested)
    while pending:
        capability = pending.pop()
        for dependency in dependencies[capability]:
            if dependency not in required:
                required.add(dependency)
                pending.append(dependency)
    return required


ADAPTER_CONFIGURATION = "adapters.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="obs-document",
        description="Validate a JSON Document and deliver it to a configured adapter.",
        epilog="One-call build: obs-document --source spec/manifest.md --adapter html "
               "--destination out.html --execute-commands",
    )
    parser.add_argument("--document", type=Path,
                        help="JSON Document to read, or to write from --source; with --source and "
                             "--adapter it is optional, and without it the Document is a temporary "
                             "file the build removes.")
    parser.add_argument("--source", type=Path, action="append",
                        help="Manifest note, or vault folder holding it (input.manifestFilename of the vault's project "
                             "configuration, else of --config, default manifest.md), to parse into --document. Repeat --source, each followed by its "
                             "--destination, to build several artifacts with --adapter in one call, in "
                             "argument order; every other option applies to each.")
    parser.add_argument("--config", type=Path,
                        help="Core configuration JSON for --source. The vault's project configuration "
                             "(input.projectConfigFilename, default cfg.json), read on every build, overrides "
                             "its keys; the Document carries that file's other keys to the adapter.")
    parser.add_argument("--execute-commands", action="store_true",
                        help="Authorize running the cmd fences of --source from its vault root: "
                             "producers (cmd silent) before conversion, then each other fence, "
                             "whose captured output the Document carries. Review the commands "
                             "first; without this a cmd fence fails the build.")
    parser.add_argument("--embed-source", action="store_true",
                        help="Disclose the source data of --source: the Document carries the vault's "
                             "source files (sourceArchive), every file below the manifest's folder "
                             "except hidden, generated and compiled ones, for an adapter that embeds a "
                             "source archive. Nothing scans them for secrets: inspect the vault first.")
    parser.add_argument("--adapter", help="Configured adapter name.")
    parser.add_argument("--adapter-config", type=Path, default=Path(ADAPTER_CONFIGURATION),
                        help=f"Adapter configuration JSON (default: {ADAPTER_CONFIGURATION} in the "
                             "current folder).")
    parser.add_argument("--capability-reference", type=Path, default=PACKAGED_CAPABILITY_REFERENCE,
                        help="Capability reference JSON (default: the one this package ships, "
                             "generated from spec/capabilities when it was built).")
    parser.add_argument("--destination", type=Path, action="append",
                        help="Adapter output destination; once per --source.")
    parser.add_argument("--serve", action="store_true",
                        help="After the build, serve the artifact with the command the adapter declares (serve in "
                             "its adapter.json) and exit with its exit code; it prints where to open it.")
    parser.add_argument("--wait", action="store_true",
                        help="With --serve: the server exits after the reader's first answers, printing them.")
    parser.add_argument("--timeout", metavar="S",
                        help="With --serve --wait: the server fails after S seconds without answers.")
    parser.add_argument("--answers", type=Path,
                        help="With --source: a reader's answers file (what --serve --wait prints and the served "
                             "artifact's server writes); the chapters that ask carry their verdicts, so the artifact "
                             "is the decision record.")
    parser.add_argument("--adapter-option", action="append", default=[], metavar="NAME=VALUE",
                        help="Pass an option the adapter declares in its adapter.json (options); "
                             "repeatable. A boolean option takes true or false; a vault-file option ID=PATH, "
                             "PATH a file of the vault.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    options = build_parser().parse_args(argv)
    sources, destinations = options.source or [], options.destination or []
    try:
        if len(sources) > 1:
            _check_several(options, sources, destinations)
        elif len(destinations) > 1:
            raise DocumentError("--destination is repeated without as many --source: each --source pairs with "
                                "the --destination that follows it. Give one --source per --destination.")
        options.source = sources[0] if sources else None
        options.destination = destinations[0] if destinations else None
        if options.execute_commands and not options.source:
            raise DocumentError("--execute-commands is only used with --source.")
        if options.embed_source and not options.source:
            raise DocumentError("--embed-source is only used with --source: it archives the vault --source "
                                "names. Build the Document from its manifest with --source.")
        if options.adapter and options.destination is None:
            raise DocumentError("--destination is missing: --adapter writes the artifact there. "
                                "Name the output file with --destination.")
        if options.document is None and not (options.source and options.adapter):
            raise DocumentError("--document is missing: without --source it is the Document to read, and "
                                "--source without --adapter writes it. Name the JSON Document with --document, "
                                "or build an artifact with --adapter and --destination.")
        if not options.source and not options.adapter:
            raise DocumentError("--adapter is required when --source is not supplied.")
        if options.answers and not options.source:
            raise DocumentError("--answers is only used with --source: the answers go into the Document built from "
                                "the manifest. Build it with --source.")
        if options.adapter_option and not options.adapter:
            raise DocumentError("--adapter-option is only used with --adapter.")
        if options.wait and not options.serve:
            raise DocumentError("--wait is only used with --serve: the server waits for the reader's answers. "
                                "Add --serve, or drop --wait.")
        if options.timeout is not None and not options.wait:
            raise DocumentError("--timeout is only used with --serve --wait: it bounds the wait for the reader's "
                                "answers. Add --wait, or drop --timeout.")
        if options.serve and (not options.adapter or len(sources) > 1):
            raise DocumentError("--serve serves the one artifact --adapter writes. Build one --source or --document "
                                "with --adapter and --destination, or drop --serve.")
        adapter, arguments = None, []
        if options.adapter:  # Before the build: an undeclared option fails at once.
            adapter, arguments = _adapter(options.adapter, options.adapter_config, options.adapter_option)
        if options.serve and "serve" not in adapter:
            raise DocumentError(f"--serve needs a serve command, and adapter {options.adapter!r} "
                                f"({adapter_manifest_path(options.adapter, options.adapter_config)}) declares none. "
                                f"Drop --serve, or declare serve in that manifest; see {SERVE_OWNER}.")
        reference = read_capability_reference(options.capability_reference)
        if not options.source:
            vault_file = next((item for item in arguments if isinstance(item, VaultFile)), None)
            if vault_file is not None:
                raise DocumentError(f"--adapter-option {vault_file.option!r}: names a file of the vault, and "
                                    f"--document has none. Build from the manifest with --source; see "
                                    f"{ADAPTER_OPTIONS_OWNER}.")
            _deliver(adapter, arguments, options.adapter_config, read_document(options.document, reference),
                     options.document, options.destination, reference)
            return _serve(adapter, options) if options.serve else 0
        if len(sources) == 1:
            _build(options, options.source, options.destination, reference, adapter, arguments)
            return _serve(adapter, options) if options.serve else 0
        for source, destination in zip(sources, destinations):  # cli.md, Several documents per call.
            try:
                _build(options, source, destination, reference, adapter, arguments, f"--source {source}: ")
            except (AdapterError, DocumentError) as error:
                raise DocumentError(f"--source {source}: {error}") from error
    except (AdapterError, DocumentError, InputError) as error:
        raise SystemExit(f"obs-document: {error}") from error
    return 0


SERVE_OWNER = "spec/design_input/cli.md (One-call build)"


def _serve(adapter: dict[str, object], options: argparse.Namespace) -> int:
    """Run the adapter's serve command on the artifact it wrote, its output on ours; its exit code."""
    command = [*adapter["serve"], str(options.destination.resolve()), *(["--wait"] if options.wait else []),
               *(["--timeout", options.timeout] if options.timeout is not None else [])]
    sys.stdout.flush()
    try:
        return subprocess.run(command, cwd=options.adapter_config.parent, check=False).returncode
    except OSError as error:
        raise AdapterError(f"--serve: cannot start adapter {adapter['name']!r}'s serve command {command[0]!r}: "
                           f"{error}. Install the adapter, or drop --serve; see {SERVE_OWNER}.") from error
    except KeyboardInterrupt:
        return 0


def _check_several(options: argparse.Namespace, sources: list[Path], destinations: list[Path]) -> None:
    """Several --source build one artifact each; see cli.md, Several documents per call."""
    if not options.adapter:
        raise DocumentError("several --source need --adapter: each builds the artifact of the --destination "
                            "that follows it. Name the adapter with --adapter, or give one --source.")
    if options.document is not None:
        raise DocumentError("--document names one Document, but several --source build one each, each into a "
                            "temporary file. Drop --document, or give one --source to keep its Document.")
    if len(destinations) != len(sources):
        raise DocumentError(f"{len(sources)} --source but {len(destinations)} --destination: each --source pairs "
                            f"with the --destination that follows it. Give one --destination per --source.")


def _build(options: argparse.Namespace, source: Path, destination: Path | None, reference: dict[str, object],
           adapter: dict[str, object] | None, given: list[str | VaultFile], label: str = "") -> None:
    """Build the Document of ``source`` and, with an ``adapter``, its artifact at ``destination``;
    ``label`` leads each adapter warning (cli.md, Several documents per call)."""
    try:
        source = manifest_note(source, options.config)
    except VaultError as error:
        raise DocumentError(str(error)) from error
    vault = source.resolve().parent
    if adapter is not None and destination.resolve().is_relative_to(vault):
        raise DocumentError(f"--destination {destination} is inside the vault {vault}: the artifact would become "
                            f"a file of the vault it is built from (spec/design_input/cli.md, One-call build). "
                            f"Name a --destination outside {vault}.")
    delivery = ["--adapter", options.adapter, "--destination", destination.name] if adapter is not None else []
    arguments, files, recorded = [], [], {}
    for item in given:  # A vault-file option resolves inside this source's vault (cli.md, Adapter options).
        if isinstance(item, VaultFile):
            passed, path = item.resolved(vault)
            arguments += passed
            files.append(path)
            recorded[item.option] = f"{item.name}={item.id}={path}"
        else:
            arguments.append(item)
    for option in options.adapter_option:  # The record names the vault file by its vault path only.
        delivery += ["--adapter-option", recorded.get(option, option)]
    document = build_document(source, reference, options.config, options.execute_commands, options.embed_source,
                              delivery, files, options.answers)
    for diagnostic in document["diagnostics"]:
        if diagnostic["level"] == "warning":
            print(f"obs-document: warning: {diagnostic['message']}", file=sys.stderr)
    with ExitStack() as stack:
        document_path = options.document
        if document_path is None:
            folder = stack.enter_context(tempfile.TemporaryDirectory(prefix="obs-document-"))
            document_path = Path(folder) / "document.json"
        _write(document, document_path)  # build_document validated it.
        if adapter is not None:  # The vault root as given, for the adapter's messages only.
            _deliver(adapter, ["--vault-root", str(source.parent), *arguments],
                     options.adapter_config, document, document_path, destination, reference, label)


if __name__ == "__main__":
    raise SystemExit(main())
