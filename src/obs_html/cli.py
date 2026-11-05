from time import perf_counter

_STARTED = perf_counter()  # before the imports, so --timings can report their cost

import argparse
import re
import subprocess
import sys
import tempfile
import textwrap
from functools import partial
from importlib.metadata import version
from pathlib import Path
from typing import Callable, NamedTuple, Sequence

from jsonschema import SchemaError, ValidationError

from obs.producers import run_producers
from obs_html.comments import CommentError, extract_comments
from obs_html.config import Config, load_config
from obs_html.content import ContentError, read_manifest
from obs_html.commands import run_command
from obs_html.renderer import render_artifact
from obs_html.artifact_data import chapter_html, html_text, same_artifact_content
from obs_html.reproduction import (
    embed_archive, embed_payload_runtime, embedded_archive, source_archive,
)
from obs_html.timings import STAGES, load_baselines, recording, slower_stages, stage


_IMPORTED = perf_counter()
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = PROJECT_ROOT / "spec"
DEFAULT_CONFIG = Path(__file__).with_name("cfg.json")
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "data_output" / "document.html"
_RUNTIME_ID = re.compile(r"[a-z][a-z0-9-]{0,63}")


class ArtifactBuild(NamedTuple):
    source: Path
    output: Path
    runtime: tuple[str, Path] | None


def resolve_manifest(source: Path, manifest_filename: str) -> Path:
    return source / manifest_filename if source.is_dir() else source


def _repository_provenance(path: Path) -> dict[str, str]:
    path = path.resolve()

    def git(*arguments: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(path), *arguments], check=True, capture_output=True, text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        return result.stdout.strip() or None

    root = git("rev-parse", "--show-toplevel")
    if root is None:
        return {"name": path.name, "version": "unknown", "commit": "unknown"}
    repository = Path(root)
    return {
        "name": repository.name,
        "version": git("describe", "--tags", "--always", "--dirty") or "unknown",
        "commit": git("rev-parse", "--short", "HEAD") or "unknown",
    }


def _generator_provenance() -> dict[str, str]:
    """Prefer the checkout's git description; installed copies fall back to the package version."""
    provenance = _repository_provenance(PROJECT_ROOT)
    if provenance["version"] == "unknown":
        provenance["version"] = version("obs-html")
    return provenance


def _stage_help() -> str:
    names = ", ".join(f"{name} ({description})" for name, description in STAGES.items())
    return textwrap.fill(f"Stages: {names}.", width=86, initial_indent="  ", subsequent_indent="  ")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="obs-html",
        description="Generate HTML artifacts from an Obsidian-compatible Markdown vault.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""Generation:
  With no operation flag, generate one portable HTML artifact.
  Default source: {DEFAULT_SOURCE}
  Default output: {DEFAULT_OUTPUT}
  Default configuration: {DEFAULT_CONFIG}
  A source folder resolves its configured manifest filename. Its optional project
  configuration merges over packaged settings. Output must be outside the vault.
  Command fences require --execute-commands; review authored commands first.
  --embed-attachments embeds files marked with ![label](file) or ![[file]] as
  downloads; without it they render like plain links. Plain links never embed.
  --check validates input and rendering without writing output or executing commands.
  It validates command syntax, not command results; do not combine it with execution.
  Paragraph warnings go to stderr, never into the HTML.

Several artifacts:
  Repeat --source/--output pairs to build several artifacts in one process, in
  argument order; this saves a Python start per artifact. A failure stops the call;
  artifacts built before it stay written. --trusted-runtime-bundle, when used,
  repeats once per --source in the same order; every other option applies to all
  artifacts. --check needs no --output.

Timings:
  --timings prints "Timing: STAGE SECONDS s (OUTPUT)" after each artifact, and
  imports, generator provenance and total for the whole call without (OUTPUT).
{_stage_help()}
  Durations are exclusive; stages without work are omitted.

Reproduction sources:
  --embed-source discloses non-hidden vault files, including scripts and data not
  in the TOC, plus generator sources, README, bootstrap wrappers, effective settings,
  a rebuild script and uv.lock (exact direct/transitive dependencies and hashes).
  Requires the generator checkout. Dotfiles (except CSS snippets the manifest
  lists), caches and generated data_output/design_output directories are
  excluded; symlinks are rejected.
  This is not a secret scanner: inspect all included files before sharing.
  External tools, network assets, Python and an OS are not bundled; dependencies
  may need downloading. Build timestamps prevent a byte-identical output promise.
  --check --embed-source validates the archive without writing it.
  Extracted bundles carry their own REPRODUCE.txt instructions.
  --trusted-runtime-bundle ID=PATH explicitly trusts one local JavaScript
  application bundle inside the selected vault. The bundle is embedded directly
  in the HTML; --embed-source additionally retains it for source reproduction.
  Authored Markdown, Base definitions, metadata and ordinary assets cannot opt in.

PDF operations:
  --export-pdf HTML renders existing HTML with local Chrome/Edge/Chromium
  or Playwright Chromium, carrying its embedded source ZIP into the PDF.
  If no browser is installed: uv run playwright install chromium
  --attach-source-to-pdf PDF requires --source-artifact HTML with an embedded ZIP.
  It attaches that ZIP to a saved PDF without rerendering its pages.
  Both operations require explicit --output file.pdf and preserve their inputs.
  They cannot be combined with --source, --config, --check, --execute-commands,
  --embed-source or --extract-comments. --source-artifact is attachment-only.
  Encrypted/signed PDFs and duplicate source-attachment names are rejected when
  attaching. Viewer support for ZIP attachments varies; PDF/A is not promised.
  Generation refuses an --output ending in .pdf; export the generated HTML instead.
  Browser printing alone cannot attach sources. In the HTML, Settings + exports
  offers Download source ZIP and Attach source ZIP to PDF: select the PDF you saved
  to attach locally and download a new copy. Keep companion HTML for omitted-note links.

Rendered check:
  --check-rendered HTML opens existing HTML in local Chrome/Edge/Chromium or
  Playwright Chromium as a reader would, waits until it reports ready or error,
  then prints console errors and uncaught page errors to stderr and the status,
  error count and printed page count (the --export-pdf print path) to stdout.
  It fails (exit 2) on any console error, an error status or no status within
  execution.renderedCheckTimeoutSeconds of --config. It writes nothing and
  cannot be combined with generation, PDF or extraction options.

Printing a chapter:
  --print-chapter HTML ID prints the chapter whose id is ID from an existing built
  artifact to stdout, as the generator stored it, without starting a browser. Chapter
  ids are the note slugs of the artifact's table of contents. --chapter-format text
  prints plain text, one line per block, instead of HTML. An unknown ID fails (exit 2)
  and lists the available ids. It writes nothing and cannot be combined with
  generation, PDF, rendered-check or extraction options.

Comment extraction:
  --extract-comments HTML reads the review JSON island without executing scripts
  or changing Markdown, and writes deterministic comment candidates to stdout.
  Generation settings are unused. Cannot combine with --check or --embed-source.

Examples:
  obs-html --source vault --output document.html
  obs-html --source a --output a.html --source b --output b.html --timings
  obs-html --source vault --check
  obs-html --source vault --output document.html --embed-source
  obs-html --export-pdf document.html --output document.pdf
  obs-html --check-rendered document.html
  obs-html --print-chapter document.html intro --chapter-format text
  obs-html --attach-source-to-pdf document.pdf --source-artifact document.html --output with-source.pdf
  obs-html --extract-comments reviewed.html

Exit status:
  0: success (including --help); 2: invalid options, input or operation failure.
""",
    )
    parser.add_argument(
        "--embed-source", action="store_true",
        help="Embed a ZIP of non-hidden vault inputs and generator sources (discloses source data).",
    )
    parser.add_argument(
        "--embed-attachments", action="store_true",
        help="Embed files marked with ![label](file) or ![[file]] as downloads.",
    )
    parser.add_argument(
        "--trusted-runtime-bundle", metavar="ID=PATH", action="append",
        help="Explicitly embed one trusted JavaScript runtime from inside the vault.",
    )
    parser.add_argument(
        "--export-pdf", type=Path, metavar="HTML",
        help="Export existing HTML to PDF, automatically carrying its embedded source ZIP.",
    )
    parser.add_argument(
        "--attach-source-to-pdf", type=Path, metavar="PDF",
        help="Attach an HTML artifact's source ZIP to an already printed PDF.",
    )
    parser.add_argument(
        "--source-artifact", type=Path, metavar="HTML",
        help="HTML containing the archive for --attach-source-to-pdf.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate source without writing output or executing command fences.",
    )
    parser.add_argument(
        "--check-rendered", type=Path, metavar="HTML",
        help="Open existing HTML headless; report console errors and printed pages.",
    )
    parser.add_argument(
        "--print-chapter", nargs=2, metavar=("HTML", "ID"),
        help="Print one chapter of an existing artifact by id.",
    )
    parser.add_argument(
        "--chapter-format", choices=("html", "text"),
        help="Print the --print-chapter chapter as html (default) or plain text.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        action="append",
        help="Vault folder or manifest note (defaults to this tool's spec folder); repeatable.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        action="append",
        help="Output file: HTML for generation; explicit file.pdf for PDF operations; "
             "repeatable with --source.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Cross-cutting configuration file (defaults to the packaged cfg.json).",
    )
    parser.add_argument(
        "--style",
        type=Path,
        metavar="FOLDER",
        help="Style module folder containing style.css; overrides input.styleFolder.",
    )
    parser.add_argument(
        "--execute-commands",
        action="store_true",
        help="Execute cmd fences while generating derived content.",
    )
    parser.add_argument(
        "--extract-comments",
        type=Path,
        metavar="HTML",
        help="Print comment candidates from returned reviewed HTML.",
    )
    parser.add_argument(
        "--timings",
        action="store_true",
        help="Print the duration of each internal stage.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = list(argv) if argv is not None else sys.argv[1:]
    options = parser.parse_args(args)
    started = perf_counter()
    supplied = {argument.split("=", 1)[0] for argument in args if argument.startswith("--")}

    try:
        if options.chapter_format and not options.print_chapter:
            parser.error("--chapter-format requires --print-chapter HTML ID.")
        if options.print_chapter:
            if (options.check_rendered or options.export_pdf or options.attach_source_to_pdf
                    or options.source_artifact or options.check or options.execute_commands
                    or options.embed_source or options.embed_attachments or options.extract_comments
                    or options.trusted_runtime_bundle or options.source or options.output
                    or options.timings):
                parser.error("--print-chapter cannot be combined with generation, PDF, "
                             "rendered-check or extraction options.")
            artifact_path, chapter_id = Path(options.print_chapter[0]), options.print_chapter[1]
            try:
                html = chapter_html(artifact_path.read_text(encoding="utf-8"), chapter_id)
            except (ContentError, OSError) as error:
                raise ContentError(f"--print-chapter {artifact_path}: {error}") from error
            print(html_text(html) if options.chapter_format == "text" else html, end="")
            return 0
        if options.check_rendered:
            if (options.export_pdf or options.attach_source_to_pdf or options.source_artifact
                    or options.check or options.execute_commands or options.embed_source
                    or options.embed_attachments
                    or options.extract_comments or options.trusted_runtime_bundle
                    or options.source or options.output):
                parser.error("--check-rendered cannot be combined with generation, PDF or extraction options.")
            config = load_config(options.config)
            from obs_html.pdf import check_rendered
            _print_timings(options, {"imports": _IMPORTED - _STARTED})
            with recording() as recorded:
                result = check_rendered(options.check_rendered, config.rendered_check_timeout_seconds)
            for error in result.console_errors:
                print(f"Console error: {error}", file=sys.stderr)
            print(f"Rendered {options.check_rendered.resolve()}: status {result.status}, "
                  f"{len(result.console_errors)} console errors, {result.pages} pages.")
            _print_timings(options, recorded.durations, options.check_rendered.resolve())
            _print_timings(options, {"total": _total(started)})
            if result.status != "ready" or result.console_errors:
                failures = [f"status {result.status}"] if result.status != "ready" else []
                if result.console_errors:
                    failures.append(f"{len(result.console_errors)} console errors")
                raise ContentError(f"Rendered check failed: {', '.join(failures)}.")
            return 0
        if options.export_pdf or options.attach_source_to_pdf:
            if (options.export_pdf and options.attach_source_to_pdf or options.check
                    or options.execute_commands or options.embed_source or options.extract_comments
                    or options.trusted_runtime_bundle or options.embed_attachments
                    or options.source or "--config" in supplied):
                parser.error("PDF operations cannot be combined with generation or extraction options.")
            if not options.output or len(options.output) > 1 or options.output[0].suffix.lower() != ".pdf":
                parser.error("PDF operations require one explicit --output file.pdf.")
            output = options.output[0]
            from obs_html.pdf import attach_archive, export_pdf
            if options.export_pdf:
                if options.source_artifact:
                    parser.error("--source-artifact is only used with --attach-source-to-pdf.")
                if output.resolve() == options.export_pdf.resolve():
                    parser.error("PDF output must not overwrite the source HTML.")
            elif not options.source_artifact:
                parser.error("--attach-source-to-pdf requires --source-artifact HTML.")
            elif output.resolve() in {options.attach_source_to_pdf.resolve(), options.source_artifact.resolve()}:
                parser.error("PDF output must be a new file, not an input.")
            _print_timings(options, {"imports": _IMPORTED - _STARTED})
            with recording() as recorded:
                if options.export_pdf:
                    pdf = export_pdf(options.export_pdf)
                else:
                    archive = embedded_archive(options.source_artifact.read_text(encoding="utf-8"))
                    if archive is None:
                        raise ContentError("Source HTML has no embedded source archive.")
                    pdf = attach_archive(options.attach_source_to_pdf.read_bytes(), archive)
                _write_if_changed(output.resolve(), pdf)
            print(f"Generated PDF {output.resolve()}.")
            _print_timings(options, recorded.durations, output.resolve())
            _print_timings(options, {"total": _total(started)})
            return 0
        if options.source_artifact:
            parser.error("--source-artifact requires --attach-source-to-pdf.")
        if options.extract_comments and options.embed_source:
            parser.error("--embed-source cannot be combined with comment extraction.")
        if options.check and (options.execute_commands or options.extract_comments is not None):
            parser.error("--check cannot be combined with execution or comment extraction.")
        builds = _builds(parser, options)
        if options.extract_comments is not None:
            print(extract_comments(options.extract_comments.resolve()), end="")
            return 0
    except (CommentError, ContentError, OSError, ValueError, SchemaError, ValidationError) as error:
        parser.error(str(error))

    _print_timings(options, {"imports": _IMPORTED - _STARTED})
    with recording() as recorded:
        with stage("provenance"):
            generator = _generator_provenance()
    _print_timings(options, recorded.durations)
    baselines = load_baselines() if options.timings else {}
    for build in builds:
        with recording() as recorded:
            try:
                chapters, output_path, config = _build_artifact(options, build, generator)
            except (CommentError, ContentError, OSError, ValueError, SchemaError, ValidationError) as error:
                parser.error(f"{build.source}: {error}" if len(builds) > 1 else str(error))
        if options.check:
            print(f"Checked {chapters} chapters; no output written and no commands executed.")
        else:
            print(f"Generated {output_path} from {chapters} chapters.")
        _print_timings(options, recorded.durations, output_path)
        for message in slower_stages(recorded.durations, baselines, config.timing_relative_threshold,
                                     config.timing_absolute_threshold_seconds):
            print(f"Warning: {output_path}: {message}", file=sys.stderr)
    _print_timings(options, {"total": _total(started)})
    return 0


def _builds(parser: argparse.ArgumentParser, options: argparse.Namespace) -> list[ArtifactBuild]:
    sources = options.source or [DEFAULT_SOURCE]
    outputs = options.output or (
        [DEFAULT_OUTPUT] * len(sources) if options.check or len(sources) == 1 else []
    )
    if len(outputs) != len(sources):
        parser.error("Give one --output per --source.")
    for output in outputs:
        if output.suffix.lower() == ".pdf":
            parser.error(
                f"--output {output}: generation writes HTML, not PDF. Generate HTML first "
                f"(--output {output.with_suffix('.html')}), then run "
                f"--export-pdf {output.with_suffix('.html')} --output {output}."
            )
    if not options.check:
        resolved = [output.resolve() for output in outputs]
        for index, output in enumerate(outputs):
            if resolved[index] in resolved[:index]:
                parser.error(f"--output {output}: each artifact needs its own --output; "
                             "give each --source a different --output.")
    bundles = options.trusted_runtime_bundle or [None] * len(sources)
    if len(bundles) != len(sources):
        parser.error("Give one --trusted-runtime-bundle per --source, or none.")
    runtimes = []
    for bundle in bundles:
        if bundle is None:
            runtimes.append(None)
            continue
        runtime_id, separator, runtime_path = bundle.partition("=")
        if not separator or not _RUNTIME_ID.fullmatch(runtime_id) or not runtime_path:
            parser.error("--trusted-runtime-bundle must use the form ID=PATH.")
        runtimes.append((runtime_id, Path(runtime_path)))
    return [ArtifactBuild(*build) for build in zip(sources, outputs, runtimes, strict=True)]


def _build_artifact(
    options: argparse.Namespace, build: ArtifactBuild, generator: dict[str, str],
) -> tuple[int, Path, Config]:
    with stage("parse"):
        defaults = load_config(options.config)
        source = build.source
        project_root = source if source.is_dir() else source.parent
        project_config_path = project_root / defaults.project_config_filename
        config = load_config(
            options.config,
            project_config_path if project_config_path.is_file() else None,
        )
        manifest_path = resolve_manifest(source, config.manifest_filename).resolve()
        style_folder = options.style or (
            project_root / config.style_folder if config.style_folder is not None else None
        )
        with stage("producers"):
            run_producers(
                manifest_path.parent,
                authorized=options.execute_commands and not options.check,
                timeout_seconds=config.command_timeout_seconds,
            )
        trusted_runtime_source = None
        if build.runtime:
            trusted_runtime_id, trusted_runtime_path = build.runtime
            resolved_runtime = trusted_runtime_path.resolve(strict=True)
            if (trusted_runtime_path.is_symlink() or not resolved_runtime.is_file() or
                    not resolved_runtime.is_relative_to(manifest_path.parent.resolve())):
                raise ContentError("Trusted application runtime must be a regular file inside the selected vault.")
            if resolved_runtime.suffix.lower() != ".js":
                raise ContentError("Trusted application runtime must be a .js file.")
            trusted_runtime_source = (trusted_runtime_id, resolved_runtime.read_text(encoding="utf-8"))
        manifest = read_manifest(manifest_path)
    chapters = manifest.chapters
    output_path = build.output.resolve()
    vault_root = manifest_path.parent
    if output_path.is_relative_to(vault_root):
        raise ContentError("Output must be outside the source vault.")
    command_runner = (
        _check_command if options.check else
        partial(
            run_command,
            cwd=vault_root,
            timeout_seconds=config.command_timeout_seconds,
        )
        if options.execute_commands
        else None
    )
    with stage("provenance"):
        target = _repository_provenance(vault_root)
    with stage("render"):
        artifact = render_artifact(
            manifest_path,
            chapters,
            command_runner,
            facet_distinct_ratio=config.facet_distinct_ratio,
            bordered_tags=config.bordered_tags,
            table_page_size=config.table_page_size,
            table_column_minimum_pixels=config.table_column_minimum_pixels,
            table_compact_column_minimum_pixels=config.table_compact_column_minimum_pixels,
            table_icon_width_pixels=config.table_icon_width_pixels,
            table_detail_font_size_points=config.table_detail_font_size_points,
            dock_pane_minimum_pixels=config.dock_pane_minimum_pixels,
            hover_card=config.hover_card,
            print_setup=config.print_setup,
            print_ready_timeout_milliseconds=config.print_ready_timeout_milliseconds,
            filter_presets=config.filter_presets,
            reading=config.reading,
            figures=config.figures,
            figure_references=config.figure_references,
            embed_pdfs=config.embed_pdfs,
            data_compression=config.data_compression,
            asset_index=config.asset_index,
            inactive_icon_opacity=config.inactive_icon_opacity,
            guided_card=config.guided_card,
            css_snippet_folder=config.css_snippet_folder,
            style_folder=style_folder,
            trusted_runtime_bundle=trusted_runtime_source,
            warning_handler=lambda message: print(f"Warning: {message}", file=sys.stderr),
            manifest=manifest,
            generator_provenance=generator,
            target_provenance=target,
            embed_attachments=options.embed_attachments,
        )
        if trusted_runtime_source:
            artifact = embed_payload_runtime(artifact)
    if options.embed_source:
        with stage("source-archive"):
            artifact = embed_archive(artifact, source_archive(
                vault_root, manifest_path, PROJECT_ROOT, config, options.execute_commands,
                (trusted_runtime_id, resolved_runtime.relative_to(vault_root).as_posix())
                if trusted_runtime_source else None,
                options.embed_attachments,
            ))
    if not options.check:
        _write_if_changed(output_path, artifact, partial(_same_artifact, artifact))
    return len(chapters), output_path, config


def _total(started: float) -> float:
    return _IMPORTED - _STARTED + perf_counter() - started


def _print_timings(
    options: argparse.Namespace, durations: dict[str, float], label: Path | None = None,
) -> None:
    if not options.timings:
        return
    suffix = f" ({label})" if label else ""
    for name, seconds in durations.items():
        print(f"Timing: {name} {seconds:.3f} s{suffix}")

def _check_command(command: str) -> str:
    if not command.strip():
        raise ContentError("A cmd fence cannot be empty.")
    return ""


def _same_artifact(artifact: str, existing: bytes) -> bool:
    try:
        return same_artifact_content(artifact, existing.decode("utf-8"))
    except UnicodeDecodeError:
        return False


@stage("write")
def _write_if_changed(
    output_path: Path, content: str | bytes, unchanged: Callable[[bytes], bool] | None = None,
) -> bool:
    """Atomically replace output_path unless it already holds this content.

    Rewriting identical bytes makes on-access antivirus scanners check the file again.
    ``unchanged`` may accept existing bytes that differ only in volatile build data.
    """
    data = content if isinstance(content, bytes) else content.encode("utf-8")
    try:
        existing = output_path.read_bytes() if output_path.is_file() else None
    except OSError:
        existing = None
    if existing is not None and (existing == data or unchanged is not None and unchanged(existing)):
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(data)
            temporary_path = Path(temporary.name)
        temporary_path.replace(output_path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()
    return True


if __name__ == "__main__":
    raise SystemExit(main())