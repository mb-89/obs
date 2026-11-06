"""The build hook of the core's package: it writes the package data the core generates.

Reader: whoever changes how the core is built or what it ships.

Each build of the `obs` distribution, editable (`uv sync`) or not, writes two kinds of package
data and ships them; the core reads them through `importlib.resources`. They are generated, so
they are ignored and never edited; `[tool.uv] cache-keys` in pyproject.toml makes `uv sync` and
`uv run` build again when an input changes.

- `src/obs/capability-reference.json`, from the capability notes in `spec/capabilities`, with the
  generator `obs.capabilities` and its coverage data; obs-document reads it when no
  `--capability-reference` is given. test/test_capabilities.py fails when the shipped file is stale.
- `src/obs/vendor/diagrams/`, the diagram renderers that `obs.diagram.RENDERERS` names, unpacked
  from the tarballs `src/obs/diagrams/package-lock.json` pins (only those packages' own, checked
  against its integrity; not their dependencies), each npm package with its licence
  (spec/design_input/input-model.md, Figure input direction).
"""
import base64
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

NOTES = Path("spec") / "capabilities"
CAPABILITY_REFERENCE = Path("src") / "obs" / "capability-reference.json"
DIAGRAMS = Path("src") / "obs" / "diagrams"
"""The renderers' npm package: its lockfile pins them."""
VENDOR = Path("src") / "obs" / "vendor" / "diagrams"
"""The packaged renderers, each file at its path below node_modules."""


class BuildError(Exception):
    """Package data could not be built: ``source`` is its input, ``remedy`` how to fix it."""

    def __init__(self, source: Path, field: str, problem: str, remedy: str):
        self.source, self.field, self.remedy = source, field, remedy
        super().__init__(f"obs build (hatch_build.py): {source}: {field}: {problem}. Remedy: {remedy}.")


def _source_module(root: Path, name: str):
    """A core module from the source tree; it and what it imports need only pyyaml."""
    sys.path.insert(0, str(root / "src"))
    try:
        return __import__(name, fromlist=["_"])
    finally:
        sys.path.remove(str(root / "src"))


def _lockfile_packages(lockfile: Path) -> dict:
    """The lockfile's ``packages``: each installed package by its path, with its version and integrity."""
    return json.loads(lockfile.read_text(encoding="utf-8"))["packages"]


def pinned_files(package: Path, files: list[str], work: Path, run=subprocess.run) -> Path:
    """Unpack ``files``, paths below node_modules, from the tarballs of the npm packages they belong
    to, at the versions the lockfile of ``package`` pins, into ``work``; the node_modules folder.

    Only those packages' own tarballs are fetched (one ``npm pack``, from npm's cache where it has
    them), not their dependencies, and each is checked against the lockfile's integrity, whole, before
    the listed files are extracted from it as a stream."""
    lockfile = package / "package-lock.json"
    remedy = f"install Node.js and check that npm reaches its registry, then build again; {lockfile} pins it"
    pinned = _lockfile_packages(lockfile)
    names = sorted({_npm_package(file) for file in files})
    for name in names:
        if f"node_modules/{name}" not in pinned:
            raise BuildError(lockfile, f"packages.node_modules/{name}", "the lockfile pins no such package",
                             f"add {name} to {package / 'package.json'} and run npm install there")
    npm = shutil.which("npm")
    if npm is None:
        raise BuildError(lockfile, "npm pack", "npm is not on PATH", remedy)
    tarballs = work / "tarballs"
    tarballs.mkdir()
    result = run([npm, "pack", "--json", "--prefer-offline", "--pack-destination", str(tarballs),
                  *(f"{name}@{pinned[f'node_modules/{name}']['version']}" for name in names)], cwd=work,
                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise BuildError(lockfile, "npm pack", f"failed (exit code {result.returncode}):\n{result.stderr}{result.stdout}",
                         remedy)
    installed = work / "node_modules"
    for name, packed in zip(names, json.loads(result.stdout)):
        tarball = (tarballs / packed["filename"]).read_bytes()
        integrity = pinned[f"node_modules/{name}"]["integrity"]
        if f"sha512-{base64.b64encode(hashlib.sha512(tarball).digest()).decode()}" != integrity:
            raise BuildError(lockfile, f"packages.node_modules/{name}.integrity",
                             f"the tarball npm fetched, {packed['filename']}, is not the one the lockfile pins",
                             "clear npm's cache with `npm cache clean --force`, then build again")
        wanted = {file.removeprefix(f"{name}/"): file for file in files if _npm_package(file) == name}
        # A stream, read only as far as the last listed file: the members it does not ship are
        # neither indexed nor extracted (mermaid's LICENSE is its last member, so it is inflated whole).
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r|gz") as archive:
            for member in archive:
                file = wanted.pop(member.name.removeprefix("package/"), None) if member.isfile() else None
                if file is not None:
                    target = installed / file
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.extractfile(member).read())
                    if not wanted:
                        break
    return installed


def _npm_package(file: str) -> str:
    """The npm package a path below node_modules belongs to: its first segment, two where scoped."""
    parts = file.split("/")
    return "/".join(parts[:2] if parts[0].startswith("@") else parts[:1])


def diagram_files(root: Path) -> list[str]:
    """Every file the packaged renderers hold, below node_modules: what the renderers serve, and
    each npm package's licence."""
    renderers = _source_module(root, "obs.diagram").RENDERERS.values()
    served = sorted({file for renderer in renderers for file in renderer.files.values()})
    return sorted({*served, *(f"{_npm_package(file)}/LICENSE" for file in served)})


def build_diagrams(root: Path, run=subprocess.run) -> list[str]:
    """Fill VENDOR from the lockfile; the files written, relative to ``root``, for the wheel.

    Each file is replaced atomically and stale files are removed afterwards, so a process drawing
    diagrams while the package is built (an editable install's) never finds a file missing."""
    folder = root / VENDOR
    files = diagram_files(root)
    with tempfile.TemporaryDirectory(prefix="obs-build-") as work:
        installed = pinned_files(root / DIAGRAMS, files, Path(work), run)
        for file in files:
            if not (installed / file).is_file():
                raise BuildError(root / DIAGRAMS / "package-lock.json", file, "its pinned tarball holds no such file",
                                 "pin a version that has it, or change obs.diagram.RENDERERS to its new path")
        for file in files:
            target = folder / file
            target.parent.mkdir(parents=True, exist_ok=True)
            staged = target.with_name(f".{target.name}.{os.getpid()}")
            shutil.copy2(installed / file, staged)
            os.replace(staged, target)
    # A dot file is another build's file being staged.
    for path in folder.rglob("*"):
        if path.is_file() and not path.name.startswith(".") and path.relative_to(folder).as_posix() not in files:
            path.unlink()
    return [(VENDOR / file).as_posix() for file in files]


class PackageDataHook(BuildHookInterface):
    PLUGIN_NAME = "package-data"

    def initialize(self, version: str, build_data: dict) -> None:
        root = Path(self.root)
        capabilities = _source_module(root, "obs.capabilities")
        reference = capabilities.build_capability_reference(root / NOTES, root / NOTES / "coverage.json")
        (root / CAPABILITY_REFERENCE).write_text(json.dumps(reference, indent=2) + "\n", encoding="utf-8")
        build_data["artifacts"].append(CAPABILITY_REFERENCE.as_posix())
        build_data["artifacts"].extend(build_diagrams(root))
