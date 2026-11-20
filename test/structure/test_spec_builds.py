"""No core test builds obs's spec itself: it reads the run's one shared build.

Reader: whoever writes or changes a core test that reads obs's spec.

The owner is quality.md (Testing boundaries): obs's spec is built once per run by
test/spec_build.py, which also owns what counts as building it (``own_builds``). A test that needs
another build of the spec copies the vault, builds only that variant, and is named in
EXCEPTIONS with why; today the core has none.
"""
from pathlib import Path

import spec_build

TESTS = Path(__file__).parents[1]
# What denotes obs's checkout in a core test: the module constants, and the test folder's parent.
ROOTS = r"ROOT|PROJECT_ROOT|Path\(__file__\)(\.resolve\(\))?\.parents\[1\]"
# test name -> why it builds a variant of obs's spec itself.
EXCEPTIONS: dict[str, str] = {}


def test_no_core_test_builds_the_spec_itself() -> None:
    found = [violation for path in sorted(TESTS.glob("*.py")) if path.name != "spec_build.py"
             for violation in spec_build.own_builds(path, ROOTS, set(EXCEPTIONS))]
    assert found == [], "test/structure/test_spec_builds.py: " + "\n".join(found)


def test_the_check_names_each_way_a_test_builds_the_spec(tmp_path: Path) -> None:
    """The check is not vacuous: each builder on the spec vault, or on a copy, is named with its
    test and line; a stand-in for the build, the shared build and a build of another vault are not."""
    (tmp_path / "test_own_spec.py").write_text('''
import shutil
import subprocess
from pathlib import Path

from obs import document as core
from obs.document import build_document, main as obs_document

ROOT = Path(__file__).parents[1]
SPEC_MANIFEST = ROOT / "spec" / "manifest.md"


def test_in_process(tmp_path):
    build_document(SPEC_MANIFEST, {})


def test_one_call(tmp_path):
    obs_document(["--source", str(SPEC_MANIFEST), "--adapter", "html"])


def build_by_command(folder):
    root = ROOT
    subprocess.run(["uv", "run", "obs-document", "--source", str(root / "spec" / "manifest.md")])


def test_by_command(tmp_path):
    build_by_command(tmp_path)


def test_a_copy(tmp_path, spec_vault):
    core.main(["--source", str(spec_vault / "manifest.md"), "--document", str(tmp_path / "spec.json")])


def test_named_variant(tmp_path):
    vault = tmp_path / "spec"
    shutil.copytree(ROOT / "spec", vault)
    build_document(vault / "manifest.md", {})


def test_stand_in(monkeypatch, spec_document):
    monkeypatch.setattr(core, "build_document", lambda *_arguments: spec_document)
    obs_document(["--source", str(SPEC_MANIFEST), "--adapter", "fixture"])


def test_shared(spec_document):
    assert spec_document["chapters"]


def test_another_vault(tmp_path):
    capabilities = ROOT / "spec" / "capabilities"
    build_document(tmp_path / "vault" / "manifest.md", capabilities)
''', encoding="utf-8")
    found = spec_build.own_builds(tmp_path / "test_own_spec.py", ROOTS, {"test_named_variant"})
    assert [line.split(":")[0] for line in found] == [
        "test_in_process", "test_one_call", "build_by_command", "test_a_copy"]
    assert all("test/spec_build.py" in line for line in found)
    assert "test_own_spec.py:14" in found[0]
    assert spec_build.own_builds(tmp_path / "test_own_spec.py", ROOTS, {"test_gone"})[-1].startswith(
        "test_gone: test_own_spec.py has no such test")
