"""The core's build hook packages the diagram renderers from their lockfile, or names the lockfile
and the remedy where it cannot (hatch_build.py; input-model, Figure input direction).

Reader: whoever changes how the core is built or what it ships. The installed wheel's drawing is
tested in adapters/html/test/test_installed_wheel.py.
"""
import importlib.util
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

    assert (failure.value.source, failure.value.field) == (LOCKFILE, "npm ci")
    assert "Node.js" in failure.value.remedy


def test_a_failed_npm_ci_names_the_lockfile_and_what_npm_said(hook, monkeypatch) -> None:
    monkeypatch.setattr(hook.shutil, "which", lambda name: "/fake/bin/npm")

    def npm(command, cwd, **_):
        return subprocess.CompletedProcess(command, 1, stdout="npm said why\n")

    with pytest.raises(hook.BuildError) as failure:
        hook.build_diagrams(ROOT, run=npm)

    assert (failure.value.source, failure.value.field) == (LOCKFILE, "npm ci")
    assert "npm said why" in str(failure.value)


def test_an_install_without_a_served_file_names_the_lockfile_and_the_file(hook, monkeypatch) -> None:
    monkeypatch.setattr(hook.shutil, "which", lambda name: "/fake/bin/npm")

    def npm(command, cwd, **_):
        return subprocess.CompletedProcess(command, 0, stdout="")

    with pytest.raises(hook.BuildError) as failure:
        hook.build_diagrams(ROOT, run=npm)

    assert failure.value.source == LOCKFILE
    assert failure.value.field == hook.diagram_files(ROOT)[0]
