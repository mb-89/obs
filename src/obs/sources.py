"""The vault's source files a Document carries on request; see architecture "Source archive"."""
from __future__ import annotations

import base64
import os
from pathlib import Path


OWNER = "spec/design_input/architecture.md (Source archive)"
EXCLUDED_FOLDERS = frozenset({
    "__pycache__", "node_modules", "site-packages", "__pypackages__", "data_output", "design_output",
})
COMPILED_SUFFIXES = frozenset({".pyc", ".pyo", ".exe", ".dll", ".so", ".dylib", ".o", ".obj", ".class"})


class SourceError(ValueError):
    """Raised when the vault's source files cannot be archived."""


def source_archive(vault_root: Path, assets: list[dict[str, object]]) -> dict[str, object]:
    """The Document's ``sourceArchive``: each source file below ``vault_root`` with its bytes, or
    with the id of the asset that already holds them."""
    held = {asset["path"]: asset["id"] for asset in assets if "path" in asset}
    files = []
    for path in _source_paths(vault_root):
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
    return sorted(paths, key=lambda path: path.relative_to(vault_root).as_posix())


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
