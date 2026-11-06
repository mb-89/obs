"""Write a schema-valid Document and deliver it to an executable adapter."""
import argparse
import json
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from typing import Sequence

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from obs.adapter import AdapterError, adapter_manifest_path, load_adapter, option_arguments
from obs.input import schema_error
from obs.vault import VaultError, build_document as _build_document


DOCUMENT_SCHEMA_PATH = Path(__file__).with_name("document.schema.json")
FIGURE_SCHEMA_PATH = Path(__file__).with_name("figure.schema.json")
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
    execute_commands: bool = False,
) -> dict[str, object]:
    """Parse a vault into a schema-valid neutral Document.

    ``execute_commands`` authorizes running the vault's cmd fences; see capabilities/command-fences.
    """
    try:
        known = {item["id"] for item in reference["capabilities"]}
        document = _build_document(manifest_path, known, configuration_path, execute_commands)
        validate_document(document, reference)
    except VaultError as error:
        raise DocumentError(str(error)) from error
    return document


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


def validate_document(document: dict[str, object], reference: dict[str, object]) -> None:
    schema = json.loads(DOCUMENT_SCHEMA_PATH.read_text(encoding="utf-8"))
    figure_schema = json.loads(FIGURE_SCHEMA_PATH.read_text(encoding="utf-8"))
    registry = Registry().with_resource(
        FIGURE_SCHEMA_PATH.name, Resource.from_contents(figure_schema),
    )
    try:
        errors = list(Draft202012Validator(schema, registry=registry).iter_errors(document))
    except ValueError as error:
        raise DocumentError(f"Invalid Document: {error}") from error
    error = schema_error(errors, "Invalid Document", "src/obs/document.schema.json")
    if error:
        raise DocumentError(str(error)) from None
    known = {item["id"] for item in reference["capabilities"]}
    unknown = sorted(set(document["capabilities"]) - known)
    if unknown:
        raise DocumentError(f"Document uses unknown capabilities: {', '.join(unknown)}.")
    for chapter in document["chapters"]:
        _validate_node_capabilities(chapter["content"], known)
        _validate_chapter_capabilities(chapter["children"], known)


def _validate_chapter_capabilities(chapters: list[object], known: set[str]) -> None:
    for chapter in chapters:
        _validate_node_capabilities(chapter["content"], known)
        _validate_chapter_capabilities(chapter["children"], known)


def _validate_node_capabilities(nodes: list[object], known: set[str]) -> None:
    for node in nodes:
        if node["type"] not in STRUCTURAL_NODE_TYPES | known:
            raise DocumentError(f"Document node uses unknown capability: {node['type']}.")
        _validate_node_capabilities(node["children"], known)


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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


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
             reference: dict[str, object]) -> None:
    """Start the adapter on the validated ``document``, which ``document_path`` holds."""
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
    parser.add_argument("--source", type=Path, help="Manifest note to parse into --document.")
    parser.add_argument("--config", type=Path, help="Core configuration JSON for --source.")
    parser.add_argument("--execute-commands", action="store_true",
                        help="Authorize running the cmd fences of --source from its vault root: "
                             "producers (cmd silent) before conversion, then each other fence, "
                             "whose captured output the Document carries. Review the commands "
                             "first; without this a cmd fence fails the build.")
    parser.add_argument("--adapter", help="Configured adapter name.")
    parser.add_argument("--adapter-config", type=Path, default=Path(ADAPTER_CONFIGURATION),
                        help=f"Adapter configuration JSON (default: {ADAPTER_CONFIGURATION} in the "
                             "current folder).")
    parser.add_argument("--capability-reference", type=Path, default=PACKAGED_CAPABILITY_REFERENCE,
                        help="Capability reference JSON (default: the one this package ships, "
                             "generated from spec/capabilities when it was built).")
    parser.add_argument("--destination", type=Path, help="Adapter output destination.")
    parser.add_argument("--adapter-option", action="append", default=[], metavar="NAME=VALUE",
                        help="Pass an option the adapter declares in its adapter.json (options); "
                             "repeatable. A boolean option takes true or false.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    options = build_parser().parse_args(argv)
    try:
        if options.execute_commands and not options.source:
            raise DocumentError("--execute-commands is only used with --source.")
        if options.adapter and options.destination is None:
            raise DocumentError("--destination is missing: --adapter writes the artifact there. "
                                "Name the output file with --destination.")
        if options.document is None and not (options.source and options.adapter):
            raise DocumentError("--document is missing: without --source it is the Document to read, and "
                                "--source without --adapter writes it. Name the JSON Document with --document, "
                                "or build an artifact with --adapter and --destination.")
        if not options.source and not options.adapter:
            raise DocumentError("--adapter is required when --source is not supplied.")
        if options.adapter_option and not options.adapter:
            raise DocumentError("--adapter-option is only used with --adapter.")
        if options.adapter:  # Before the build: an undeclared option fails at once.
            adapter, arguments = _adapter(options.adapter, options.adapter_config, options.adapter_option)
        reference = read_capability_reference(options.capability_reference)
        with ExitStack() as stack:
            if not options.source:
                _deliver(adapter, arguments, options.adapter_config,
                         read_document(options.document, reference), options.document, options.destination,
                         reference)
                return 0
            document = build_document(options.source, reference, options.config, options.execute_commands)
            for diagnostic in document["diagnostics"]:
                if diagnostic["level"] == "warning":
                    print(f"obs-document: warning: {diagnostic['message']}", file=sys.stderr)
            document_path = options.document
            if document_path is None:
                folder = stack.enter_context(tempfile.TemporaryDirectory(prefix="obs-document-"))
                document_path = Path(folder) / "document.json"
            _write(document, document_path)  # build_document validated it.
            if options.adapter:
                _deliver(adapter, arguments, options.adapter_config, document, document_path,
                         options.destination, reference)
    except (AdapterError, DocumentError) as error:
        raise SystemExit(f"obs-document: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
