"""The core's build hook packages the diagram renderers from their lockfile, or names the lockfile
and the remedy where it cannot (hatch_build.py; input-model, Figure input direction).

Reader: whoever changes how the core is built or what it ships. The installed wheel's drawing is
tested in adapters/html/test/test_installed_wheel.py.
"""
import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
LOCKFILE = ROOT / "src" / "obs" / "diagrams" / "package-lock.json"


@pytest.fixture
def hook(monkeypatch):
    """hatch_build.py, imported without hatchling, which only the package's build environment holds."""
    interface = types.ModuleType("hatchling.builders.hooks.plugin.interface")
    interface.BuildHookInterface = object
    monkeypatch.setitem(sys.modules, "hatchling.builders.hooks.plugin.interface", interface)
    spec = importlib.util.spec_from_file_location("obs_build_hook", ROOT / "hatch_build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_build_packages_every_served_renderer_file_and_each_npm_package_licence(hook) -> None:
    from obs.diagram import RENDERERS

    files = hook.diagram_files(ROOT)

    assert {file for renderer in RENDERERS.values() for file in renderer.files.values()} < set(files)
    assert {"mermaid/LICENSE", "@plantuml/core/LICENSE"} < set(files)


def test_a_build_without_npm_names_the_lockfile_and_the_remedy(hook, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(hook.shutil, "which", lambda name: None)

    with pytest.raises(hook.BuildError) as failure:
        hook.build_diagrams(ROOT)

    assert (failure.value.source, failure.value.field) == (LOCKFILE, "npm pack")
    assert "Node.js" in failure.value.remedy


def test_a_failed_npm_pack_names_the_lockfile_and_what_npm_said(hook, monkeypatch) -> None:
    monkeypatch.setattr(hook.shutil, "which", lambda name: "/fake/bin/npm")

    def npm(command, cwd, **_):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="npm said why\n")

    with pytest.raises(hook.BuildError) as failure:
        hook.build_diagrams(ROOT, run=npm)

    assert (failure.value.source, failure.value.field) == (LOCKFILE, "npm pack")
    assert "npm said why" in str(failure.value)


def test_the_build_fetches_only_the_pinned_tarballs_of_the_served_packages(hook, monkeypatch) -> None:
    """npm ci installed the renderers' whole dependency tree (about 160 MB) to ship a few files; the
    build fetches only the tarballs of the packages it serves files from, at their pinned versions."""
    monkeypatch.setattr(hook.shutil, "which", lambda name: "/fake/bin/npm")
    lock = json.loads(LOCKFILE.read_text(encoding="utf-8"))["packages"]
    commands = []

    def npm(command, cwd, **_):
        commands.append(command)
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="stop here")

    with pytest.raises(hook.BuildError):
        hook.build_diagrams(ROOT, run=npm)

    assert len(commands) == 1
    assert commands[0][:2] == ["/fake/bin/npm", "pack"]
    assert sorted(argument for argument in commands[0] if "@" in argument[1:]) == sorted(
        f"{name}@{lock[f'node_modules/{name}']['version']}" for name in ("@plantuml/core", "mermaid"))


def test_a_tarball_that_is_not_the_pinned_one_names_its_integrity(hook, monkeypatch) -> None:
    monkeypatch.setattr(hook.shutil, "which", lambda name: "/fake/bin/npm")

    def npm(command, cwd, **_):
        destination = Path(command[command.index("--pack-destination") + 1])
        packed = []
        for spec in command[command.index("--pack-destination") + 2:]:
            filename = f"{spec.lstrip('@').replace('/', '-')}.tgz"
            (destination / filename).write_bytes(b"not the pinned tarball")
            packed.append({"filename": filename})
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(packed), stderr="")

    with pytest.raises(hook.BuildError) as failure:
        hook.build_diagrams(ROOT, run=npm)

    assert failure.value.source == LOCKFILE
    assert failure.value.field in {"packages.node_modules/@plantuml/core.integrity",
                                   "packages.node_modules/mermaid.integrity"}


def test_a_tarball_without_a_served_file_names_the_lockfile_and_the_file(hook, monkeypatch) -> None:
    import base64
    import hashlib
    import io
    import tarfile

    monkeypatch.setattr(hook.shutil, "which", lambda name: "/fake/bin/npm")
    lock = json.loads(LOCKFILE.read_text(encoding="utf-8"))["packages"]
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        tar.addfile(tarfile.TarInfo("package/package.json"), io.BytesIO(b""))
    empty = buffer.getvalue()
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(empty).digest()).decode()
    monkeypatch.setattr(hook, "_lockfile_packages",
                        lambda lockfile: {key: {**entry, "integrity": integrity} for key, entry in lock.items()})

    def npm(command, cwd, **_):
        destination = Path(command[command.index("--pack-destination") + 1])
        packed = []
        for spec in command[command.index("--pack-destination") + 2:]:
            filename = f"{spec.lstrip('@').replace('/', '-')}.tgz"
            (destination / filename).write_bytes(empty)
            packed.append({"filename": filename})
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(packed), stderr="")

    with pytest.raises(hook.BuildError) as failure:
        hook.build_diagrams(ROOT, run=npm)

    assert failure.value.source == LOCKFILE
    assert failure.value.field == hook.diagram_files(ROOT)[0]
