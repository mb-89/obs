from __future__ import annotations

import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import subprocess
from importlib.resources import files
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile
from zlib import error as ZlibError

from obs_html_interim.config import Config
from obs_html_interim.content import ContentError, manifest_presentation
from obs_html_interim.artifact_data import ARTIFACT_PATTERN, decode_artifact_data, encode_artifact_data, prepare_artifact_scripts


ARCHIVE_NAME = "obs-html-source.zip"
ARCHIVE_PATTERN = re.compile(r'<script id="obs-source-archive" type="application/octet-stream">([A-Za-z0-9+/=\s]+)</script>')
URI_ATTRIBUTE = re.compile(
    r"""(?P<prefix>\b(?:src|href)\s*=\s*)(?P<quote>["'])"""
    r"""(?P<uri>data:[^"'\s<>]+;base64,[A-Za-z0-9+/=]+)(?P=quote)""", re.IGNORECASE,
)
ASSET_REFERENCE = re.compile(r"""\b(?:src|href)\s*=\s*["']obs-asset:([^"']+)["']""", re.IGNORECASE)
ASSET_MIME = re.compile(r"(?:image/[a-z0-9.+-]+|application/(?:pdf|octet-stream|json)|text/plain)")
EXCLUDED_DIRECTORIES = {
    "__pycache__", "data_output", "design_output", "node_modules", "site-packages", "__pypackages__",
}
COMPILED_SUFFIXES = {".pyc", ".pyo", ".exe", ".dll", ".so", ".dylib", ".o", ".obj", ".class"}
# New runtime files and schemas accompany uncommitted development builds.
RUNTIME_ADDITIONS = (
    "src/obs_html_interim/payloads.js", "src/obs_html_interim/artifact_data.py", "src/obs_html_interim/artifact-data.js",
    "src/obs_html_interim/note-profile.schema.json", "src/obs_html_interim/canonical-transaction.js",
    "src/obs_html_interim/guided-card.js", "src/obs_html_interim/hover-card.js",
    "src/obs_html_interim/zip-rewrite.js", "src/obs_html_interim/running-header.js",
    "src/obs_html_interim/semantic_assets.py", "src/obs_html_interim/assets.js", "src/obs_html_interim/assets.json",
    "src/obs_html_interim/assets.schema.json", "src/obs_html_interim/icons/filter.svg", "src/obs_html_interim/icons/expand.svg",
)


def _source_paths(root: Path, inventory: list[str] | None = None) -> list[Path]:
    if inventory is None:
        try:
            result = subprocess.run(
                ["git", "-C", str(root), "ls-files", "-z", "--", "."],
                capture_output=True, check=False,
            )
            inventory = result.stdout.decode("utf-8").split("\0") if result.returncode == 0 else []
        except FileNotFoundError:
            inventory = []
        inventory = [name for name in inventory if name]
        if not inventory:
            inventory = _snapshot_paths(root)
    paths = []
    environments: dict[Path, bool] = {}
    for name in sorted(set(inventory)):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ContentError(f"Invalid source inventory path: {name}")
        if (any(part.startswith(".") or part.casefold() in EXCLUDED_DIRECTORIES or
                part.casefold().endswith((".egg-info", ".dist-info")) for part in relative.parts)
                or relative.suffix.lower() in COMPILED_SUFFIXES):
            continue
        inside_environment = False
        for parent in relative.parents:
            directory = root / parent
            if directory not in environments:
                environments[directory] = (directory / "pyvenv.cfg").is_file()
            inside_environment = inside_environment or environments[directory]
        if inside_environment:
            continue
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ContentError(f"Archive source escapes its boundary or is a symlink: {relative}")
        if not path.is_file():
            raise ContentError(f"Archive source inventory member is missing: {relative}")
        paths.append(path)
    return paths


def _snapshot_paths(root: Path) -> list[str]:
    return [path.relative_to(root).as_posix() for path in root.rglob("*")
            if path.is_file() or path.is_symlink()]


def _artifact_data(artifact: str) -> tuple[re.Match[str], dict]:
    match = ARTIFACT_PATTERN.search(artifact)
    if not match:
        raise ContentError("Cannot read embedded assets: document data is missing.")
    return match, decode_artifact_data(artifact)


def _share_archive_assets(data: dict, archive: bytes) -> None:
    with ZipFile(BytesIO(archive)) as source:
        members = {hashlib.sha256(source.read(info)).hexdigest(): info.filename
                   for info in source.infolist() if not info.is_dir()}
    assets = data.pop("embeddedAssets", {})

    def descriptor(uri: str) -> dict | None:
        header, encoded = uri.split(",", 1)
        try:
            raw = base64.b64decode(encoded, validate=True)
        except ValueError as error:
            raise ContentError(f"Invalid embedded asset encoding: {error}") from error
        digest = hashlib.sha256(raw).hexdigest()
        member = members.get(digest)
        if member is None:
            return None
        return {"archivePath": member, "mime": header[5:].split(";", 1)[0], "sha256": digest}

    for key, uri in list(assets.items()):
        if isinstance(uri, str):
            assets[key] = descriptor(uri) or uri

    def replace(match: re.Match[str]) -> str:
        uri = match["uri"]
        asset = descriptor(uri)
        if asset is None:
            return match[0]
        key = hashlib.sha256(uri.encode("ascii")).hexdigest()
        assets[key] = asset
        return f'{match["prefix"]}{match["quote"]}obs-asset:{key}{match["quote"]}'

    def transform(value: object) -> object:
        if isinstance(value, str):
            return URI_ATTRIBUTE.sub(replace, value)
        if isinstance(value, list):
            return [transform(item) for item in value]
        if isinstance(value, dict):
            return {key: transform(item) for key, item in value.items()}
        return value

    transformed = transform(data)
    data.clear()
    data.update(transformed)
    if assets:
        data["embeddedAssets"] = assets


def _validate_shared_assets(data: dict, archive: ZipFile) -> None:
    assets = data.get("embeddedAssets", {})
    if not isinstance(assets, dict):
        raise ContentError("Invalid embedded asset map.")
    for key, asset in assets.items():
        if not re.fullmatch(r"[a-f0-9]{64}", key):
            raise ContentError("Invalid embedded asset identifier.")
        if isinstance(asset, str):
            if not re.fullmatch(r"data:[^,\s]+;base64,[A-Za-z0-9+/=]+", asset):
                raise ContentError("Invalid embedded asset encoding.")
            continue
        if (not isinstance(asset, dict) or not isinstance(asset.get("archivePath"), str)
                or not isinstance(asset.get("mime"), str)
                or ASSET_MIME.fullmatch(asset["mime"]) is None
                or not re.fullmatch(r"[a-f0-9]{64}", str(asset.get("sha256", "")))):
            raise ContentError("Invalid embedded asset descriptor.")
        name = asset["archivePath"]
        if name.startswith(("/", "\\")) or "\\" in name or ".." in Path(name).parts:
            raise ContentError("Invalid embedded asset archive path.")
        try:
            raw = archive.read(name)
        except (KeyError, RuntimeError, NotImplementedError) as error:
            raise ContentError(f"Invalid embedded asset member {name}: {error}") from error
        if hashlib.sha256(raw).hexdigest() != asset["sha256"]:
            raise ContentError(f"Embedded asset digest mismatch: {name}")

    def validate_references(value: object) -> None:
        if isinstance(value, str):
            for match in ASSET_REFERENCE.finditer(value):
                if match[1] not in assets:
                    raise ContentError(f"Missing embedded asset reference: {match[1]}")
        elif isinstance(value, list):
            for item in value:
                validate_references(item)
        elif isinstance(value, dict):
            for item in value.values():
                validate_references(item)
    validate_references(data)


def source_archive(vault: Path, manifest: Path, generator: Path, config: Config,
                   execute_commands: bool, trusted_runtime: tuple[str, str] | None = None,
                   embed_attachments: bool = False) -> bytes:
    generator_files = ("pyproject.toml", "uv.lock", "README.md", "RUNME.ps1", "RUNME.sh")
    for name in generator_files:
        if not (generator / name).is_file():
            raise ContentError(f"--embed-source requires the generator checkout; missing {name}.")
    inventory_file = generator.parent / "source-inventory.json"
    inventory = None
    if inventory_file.is_file():
        try:
            inventory = json.loads(inventory_file.read_text(encoding="utf-8"))
            if (not isinstance(inventory, dict) or set(inventory) != {"vault", "generator"}
                    or any(not isinstance(names, list) or
                           any(not isinstance(name, str) for name in names)
                           for names in inventory.values())):
                raise ValueError("expected vault/generator path lists")
        except (ValueError, TypeError) as error:
            raise ContentError(f"Invalid source inventory: {error}") from error
    vault_paths = _source_paths(vault, inventory["vault"] if inventory else _snapshot_paths(vault))
    if manifest.resolve() not in {path.resolve() for path in vault_paths}:
        raise ContentError("The selected source archive boundary excludes its manifest.")
    # Listed CSS snippets are declared inputs even inside the excluded dot folder.
    for name in manifest_presentation(manifest)["cssSnippets"]:
        snippet = vault / f"{config.css_snippet_folder}/{name}.css"
        if snippet not in vault_paths:
            vault_paths.append(snippet)
    package_paths = _source_paths(generator / "src" / "obs_html_interim",
                                  [name.removeprefix("src/obs_html_interim/") for name in inventory["generator"]
                                   if name.startswith("src/obs_html_interim/")] if inventory else None)
    generator_paths = package_paths + _source_paths(generator, list(generator_files))
    for name in RUNTIME_ADDITIONS:
        path = generator / name
        if path.is_file() and path not in generator_paths:
            generator_paths.append(path)
    settings = {
        "schemaVersion": 1,
        "input": {"manifestFilename": config.manifest_filename,
                  "projectConfigFilename": config.project_config_filename,
                  "figureReferences": config.figure_references,
                  "cssSnippetFolder": config.css_snippet_folder,
                  "styleFolder": config.style_folder},
        "execution": {"commandTimeoutSeconds": config.command_timeout_seconds,
                      "renderedCheckTimeoutSeconds": config.rendered_check_timeout_seconds},
        "timings": {"relativeThreshold": config.timing_relative_threshold,
                    "absoluteThresholdSeconds": config.timing_absolute_threshold_seconds},
        "artifact": {
            "facetDistinctRatio": config.facet_distinct_ratio,
            "filterPresets": [{"label": item.label, "expression": item.expression}
                              for item in config.filter_presets],
            "borderedTags": list(config.bordered_tags), "tablePageSize": config.table_page_size,
            "tableColumnMinimumPixels": config.table_column_minimum_pixels,
            "tableCompactColumnMinimumPixels": config.table_compact_column_minimum_pixels,
            "tableIconWidthPixels": config.table_icon_width_pixels,
            "tableDetailFontSizePoints": config.table_detail_font_size_points,
            "dockPaneMinimumPixels": config.dock_pane_minimum_pixels,
            "hoverCard": config.hover_card, "print": config.print_setup,
            "printReadyTimeoutMilliseconds": config.print_ready_timeout_milliseconds,
            "reading": config.reading,
            "figures": config.figures,
            "embedPdfs": config.embed_pdfs,
            "dataCompression": config.data_compression,
            "assetIndex": config.asset_index,
            "inactiveIconOpacity": config.inactive_icon_opacity,
            "guidedCard": config.guided_card,
        },
    }
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for root, prefix, paths in ((vault, "vault", vault_paths),
                                     (generator, "generator", generator_paths)):
            for path in paths:
                archive.writestr(f"{prefix}/{path.relative_to(root).as_posix()}", path.read_bytes())
        archive.writestr("source-inventory.json", json.dumps({
            "vault": [path.relative_to(vault).as_posix() for path in vault_paths],
            "generator": [path.relative_to(generator).as_posix() for path in generator_paths],
        }, separators=(",", ":")))
        archive.writestr("build-config.json", json.dumps(settings, indent=2))
        trusted_arguments = (
            ["--trusted-runtime-bundle", f"{trusted_runtime[0]}=vault/{trusted_runtime[1]}"]
            if trusted_runtime else []
        )
        # Rebuilds repeat the original attachment decision; it is a build flag, not vault content.
        flags = " --embed-source" + (" --embed-attachments" if embed_attachments else "")
        archive.writestr("reproduce.py", (
            "from pathlib import Path\nimport os\nimport sys\n"
            "from obs_html_interim.cli import main\n"
            "os.chdir(Path(__file__).resolve().parent)\n"
            f"args = ['--source', {('vault/' + manifest.name)!r}, '--output', 'document.html', "
            f"'--config', 'build-config.json', *{flags.split()!r}]\n"
            f"args.extend({trusted_arguments!r})\n"
            "if '--execute-commands' in sys.argv:\n    args.append('--execute-commands')\n"
            "raise SystemExit(main(args))\n"
        ))
        archive.writestr("REPRODUCE.txt", (
            "Source reproduction bundle\n\n"
            "From this extracted directory run:\n"
            "  uv run --project generator python reproduce.py\n\n"
            "Without uv/Python, consult generator/README.md (Install and Run) and use:\n"
            f"  PowerShell: ./generator/RUNME.ps1 --source ../vault/{manifest.name} "
            f"--config ../build-config.json --output ../document.html{flags}\n"
            f"  Unix: sh ./generator/RUNME.sh --source ../vault/{manifest.name} "
            f"--config ../build-config.json --output ../document.html{flags}\n\n"
            "Install uv first. uv obtains Python and the locked Python dependencies as needed.\n"
            "This archive does not include an OS, Python executables, external tools, network\n"
            "resources or files outside the original vault. Review the sources before execution.\n"
            f"Original generation authorized command fences: {execute_commands}.\n"
            "If required, explicitly append --execute-commands to the chosen rebuild command.\n"
            "Documents include build timestamps; byte-identical output is not promised.\n"
            + (f"The original builder explicitly selected trusted runtime {trusted_runtime[0]}; "
               "reproduce.py repeats that selection from the included vault source. "
               "Review that code before executing the reproduction script.\n" if trusted_runtime else "")
        ))
    return buffer.getvalue()


def embed_payload_runtime(artifact: str) -> str:
    if 'id="payload-script"' in artifact or 'id="zip-rewrite-script"' in artifact:
        if 'id="payload-script"' in artifact and 'id="zip-rewrite-script"' in artifact:
            return artifact
        raise ContentError("The canonical payload runtime is incomplete.")
    payload_runtime = files("obs_html_interim").joinpath("payloads.js").read_text(encoding="utf-8")
    zip_runtime = files("obs_html_interim").joinpath("zip-rewrite.js").read_text(encoding="utf-8")
    marker = '<script id="assets-script"' if 'id="assets-script"' in artifact else '<script id="artifact-script"'
    if marker not in artifact:
        raise ContentError("Cannot install the canonical payload runtime.")
    return prepare_artifact_scripts(artifact.replace(
        marker,
        f'<script id="zip-rewrite-script">{zip_runtime}</script>\n'
        f'<script id="payload-script">{payload_runtime}</script>\n'
        + marker,
        1,
    ))


def embed_archive(artifact: str, archive: bytes) -> str:
    artifact = embed_payload_runtime(artifact)
    match, data = _artifact_data(artifact)
    _share_archive_assets(data, archive)
    data["sourceArchiveComplete"] = True
    home = next(note for note in data["notes"] if note["slug"] == "home")
    bar = (
        '<aside class="content-card source-archive-bar" id="source-archive-download">'
        '<p>Download the source archive here: '
        '<a href="#source-archive-download" data-source-download>Download source ZIP</a>'
        '</p>'
        '</aside>'
    )
    home["html"] = home["html"].replace('<header class="document-heading">',
                                       '<header class="document-heading">' + bar, 1)
    compression = re.search(r'data-compression="([^"]+)"', match[1])
    serialized = encode_artifact_data(data, compression[1] if compression else "none")
    artifact = artifact[:match.start()] + serialized + artifact[match.end():]
    island = f'<script id="obs-source-archive" type="application/octet-stream">{base64.b64encode(archive).decode("ascii")}</script>'
    library = files("obs_html_interim").joinpath("vendor", "pdf-lib.min.js").read_text(encoding="utf-8")
    license_text = files("obs_html_interim").joinpath("vendor", "pdf-lib.LICENSE").read_text(encoding="utf-8")
    runtime = files("obs_html_interim").joinpath("archive.js").read_text(encoding="utf-8")
    artifact = artifact.replace('<script id="artifact-script"',
                            island + '<script id="artifact-script"', 1)
    scripts = (
        f'\n<script id="pdf-library-script">/* {license_text} */\n{library}</script>'
        f'\n<script id="archive-script">{runtime}</script>\n'
    )
    return prepare_artifact_scripts(artifact.replace("</body>", scripts + "</body>"))


def embedded_archive(artifact: str) -> bytes | None:
    match = ARCHIVE_PATTERN.search(artifact)
    if not match:
        if 'id="obs-source-archive"' in artifact:
            raise ContentError("Invalid embedded source archive data.")
        return None
    try:
        content = base64.b64decode(re.sub(r"\s", "", match[1]), validate=True)
        with ZipFile(BytesIO(content)) as archive:
            if archive.testzip() is not None:
                raise ContentError("Embedded source archive has a corrupt member.")
            if ARTIFACT_PATTERN.search(artifact):
                _validate_shared_assets(_artifact_data(artifact)[1], archive)
    except (ValueError, OSError, BadZipFile, RuntimeError, NotImplementedError, EOFError, ZlibError) as error:
        raise ContentError(f"Invalid embedded source archive: {error}") from error
    return content
