"""Vault files a Document carries beyond its notes: the CSS snippets and, on request, the source
archive; see architecture "CSS snippets" and "Source archive"."""
from __future__ import annotations

import base64
import os
from pathlib import Path


OWNER = "spec/design_input/architecture.md (Source archive)"
SNIPPETS_OWNER = "spec/design_input/architecture.md (CSS snippets)"
EXCLUDED_FOLDERS = frozenset({
    "__pycache__", "node_modules", "site-packages", "__pypackages__", "data_output", "design_output",
})
COMPILED_SUFFIXES = frozenset({".pyc", ".pyo", ".exe", ".dll", ".so", ".dylib", ".o", ".obj", ".class"})


class SourceError(ValueError):
    """Raised when the vault's CSS snippets or source files cannot be read."""


def css_snippets(vault_root: Path, folder: str) -> list[dict[str, str]]:
    """The Document's ``cssSnippets``: every ``.css`` file directly in the vault's snippet ``folder``."""
    snippets = []
    for path in sorted((vault_root / folder).glob("*.css"), key=lambda item: item.name):
        relative = path.relative_to(vault_root).as_posix()
        if not path.resolve().is_relative_to(vault_root.resolve()):
            raise SourceError(f"CSS snippet {relative} resolves outside the vault. Replace it with the file it "
                              f"points to, or remove it; see {SNIPPETS_OWNER}.")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise SourceError(f"CSS snippet {relative} is not UTF-8 text ({error.reason}). Save it as UTF-8; "
                              f"see {SNIPPETS_OWNER}.") from error
        snippets.append({"name": path.stem, "path": relative, "text": text})
    return snippets


def source_archive(vault_root: Path, assets: list[dict[str, object]],
                   snippets: list[dict[str, str]]) -> dict[str, object]:
    """The Document's ``sourceArchive``: each source file below ``vault_root`` and each CSS snippet
    file, with its bytes or with the id of the asset that already holds them."""
    held = {asset["path"]: asset["id"] for asset in assets if "path" in asset}
    files = []
    paths = _source_paths(vault_root) + [vault_root / snippet["path"] for snippet in snippets]
    for path in sorted(paths, key=lambda path: path.relative_to(vault_root).as_posix()):
        relative = path.relative_to(vault_root).as_posix()
        if relative in held:
            files.append({"path": relative, "asset": held[relative]})
        else:
            files.append({"path": relative, "data": base64.b64encode(path.read_bytes()).decode("ascii")})
    return {"files": files}


def _source_paths(vault_root: Path) -> list[Path]:
    paths = []
    for folder, folders, names in os.walk(vault_root):
        here = Path(folder)
        folders[:] = sorted(name for name in folders if not _excluded_folder(here / name))
        names = [name for name in names
                 if not name.startswith(".") and Path(name).suffix.lower() not in COMPILED_SUFFIXES]
        for name in [*folders, *names]:
            if (here / name).is_symlink():
                raise SourceError(
                    f"obs-document --embed-source: {(here / name).relative_to(vault_root).as_posix()} is a "
                    f"symlink, which the source archive never follows. Replace it with the file or folder "
                    f"it points to, or remove it; see {OWNER}.")
        paths.extend(here / name for name in names)
    return paths


def _excluded_folder(folder: Path) -> bool:
    name = folder.name
    return (name.startswith(".") or name.casefold() in EXCLUDED_FOLDERS
            or name.casefold().endswith((".egg-info", ".dist-info")) or (folder / "pyvenv.cfg").is_file())


def validate_source_archive(document: dict[str, object]) -> str | None:
    """The first ``sourceArchive`` file naming an asset the Document does not hold, as a message."""
    assets = {asset["id"] for asset in document["assets"]}
    for index, entry in enumerate(document.get("sourceArchive", {}).get("files", [])):
        if "asset" in entry and entry["asset"] not in assets:
            return (f"Invalid Document: sourceArchive.files[{index}].asset: names {entry['asset']!r}, which is no "
                    f"asset of the Document. Name an asset's id, or carry the file's bytes as data; see {OWNER}.")
    return None
