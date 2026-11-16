"""Vault files a Document carries beyond its notes: the CSS snippets and, on request, the source
archive; see architecture "CSS snippets" and "Source archive"."""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tomllib
from collections.abc import Sequence
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


PACKAGE = Path(__file__).resolve().parent
"""The running obs package, whose checkout names the commit that rebuilds an artifact."""
LOCKFILES = ("*uv.lock", "*package-lock.json")
"""The Git pathspecs of the lockfiles whose versions the archive records."""


def source_archive(vault_root: Path, assets: list[dict[str, object]], snippets: list[dict[str, str]],
                   arguments: Sequence[str], style: dict[str, str] | None = None,
                   option_files: Sequence[str] = ()) -> dict[str, object]:
    """The Document's ``sourceArchive``: each source file below ``vault_root`` and each CSS snippet
    file, with its bytes or with the id of the asset that already holds them, and the ``build``
    record of the running obs, the call's ``arguments`` that rebuild the artifact and the ``style``
    the manifest declares (architecture, Declared style). The vault-relative ``option_files`` the
    call's vault-file options name are source files even where hidden (cli.md, Adapter options)."""
    held = {asset["path"]: asset["id"] for asset in assets if "path" in asset}
    files = []
    paths = _source_paths(vault_root) + [vault_root / snippet["path"] for snippet in snippets]
    paths += [vault_root / name for name in option_files]
    for path in sorted(set(paths), key=lambda path: path.relative_to(vault_root).as_posix()):
        relative = path.relative_to(vault_root).as_posix()
        if relative in held:
            files.append({"path": relative, "asset": held[relative]})
        else:
            files.append({"path": relative, "data": base64.b64encode(path.read_bytes()).decode("ascii")})
    return {"files": files, "build": {**generator(PACKAGE), "arguments": list(arguments),
                                      **({"style": style} if style is not None else {})}}


def generator(package: Path) -> dict[str, object]:
    """The public repository, commit and lockfile versions of the Git checkout holding ``package``."""
    checkout = Path(_git(package, "rev-parse", "--show-toplevel"))
    commit = _git(checkout, "rev-parse", "HEAD")
    repository = public_repository(_git(checkout, "config", "--get", "remote.origin.url", missing_ok=True),
                                   checkout)
    lockfiles = {}
    for name in sorted(filter(None, _git(checkout, "ls-files", "-z", "--", *LOCKFILES).split("\0"))):
        text = (checkout / name).read_text(encoding="utf-8")
        if name.endswith("uv.lock"):
            lockfiles[name] = {item["name"]: item["version"] for item in tomllib.loads(text).get("package", [])
                               if "version" in item}
        else:
            lockfiles[name] = {path.removeprefix("node_modules/"): item["version"]
                               for path, item in json.loads(text).get("packages", {}).items()
                               if path and "version" in item}
    return {"repository": repository, "commit": commit, "lockfiles": lockfiles}


_REMOTE = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*)://(?:[^@/]*@)?(?P<host>[^/:]+)(?::(?P<port>\d*))?(?P<path>/.*)?",
                     re.IGNORECASE)
_SCP = re.compile(r"(?:[^@/:]+@)?(?P<host>[^/:]{2,}):(?P<path>.*)")
_HTTP = frozenset({"http", "https"})
_SSH = frozenset({"ssh", "git+ssh", "ssh+git", "git"})


def public_repository(origin: str | None, checkout: object = "obs's checkout") -> str:
    """The ``https://<host>/<owner>/<repository>`` an ``origin`` remote URL names, https, http or ssh,
    without its credentials, trailing ``.git`` or ``/``; architecture, Repository from the origin.
    ``checkout`` names the checkout the origin belongs to in the error."""
    text = (origin or "").strip()
    remote, scp = _REMOTE.fullmatch(text), _SCP.fullmatch(text)
    if remote and remote["scheme"].lower() in _HTTP:
        port = f":{remote['port']}" if remote["port"] else ""
        scheme, host, path = remote["scheme"].lower(), remote["host"] + port, remote["path"]
    elif remote and remote["scheme"].lower() in _SSH:
        scheme, host, path = "https", remote["host"], remote["path"]
    elif scp and "://" not in text and "/" not in text.split(":", 1)[0]:
        scheme, host, path = "https", scp["host"], scp["path"]
    else:
        scheme = host = path = None
    path = (path or "").strip("/").removesuffix(".git").strip("/")
    if not host or not path:
        found = f"is {text!r}, which names" if text else "is missing, so it names"
        raise SourceError(f"obs-document --embed-source: the origin remote of {checkout} {found} no hosted "
                          f"repository the source archive can record. Add the https or ssh URL obs was cloned "
                          f"from with git remote add origin <URL> (or git remote set-url origin <URL>); see "
                          f"{OWNER}.")
    return f"{scheme}://{host.lower()}/{path}"


def _git(folder: Path, *arguments: str, missing_ok: bool = False) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(folder), *arguments], capture_output=True, text=True,
                                encoding="utf-8")
    except FileNotFoundError as error:
        raise SourceError(f"obs-document --embed-source: git is not installed, so obs in {folder} cannot name "
                          f"the commit that rebuilds the artifact. Install git; see {OWNER}.") from error
    if missing_ok and result.returncode == 1 and not result.stderr.strip():
        return None
    if result.returncode:
        raise SourceError(f"obs-document --embed-source: obs runs from {folder}, which is no Git checkout, so it "
                          f"cannot name the commit that rebuilds the artifact ({result.stderr.strip()}). Run obs "
                          f"from a clone of its repository (uv run in the clone); see {OWNER}.")
    return result.stdout.strip("\n")


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
