"""Runs the standalone Node unit tests (``test/*.test.js``) and syntax-checks every runtime ``.js``."""
import shutil
import subprocess
from pathlib import Path

import pytest

TEST_ROOT = Path(__file__).resolve().parent
NODE_TESTS = sorted(TEST_ROOT.glob("*.test.js"))
PACKAGE_ROOT = TEST_ROOT.parent / "src" / "obs_html"
RUNTIME_SCRIPTS = sorted(PACKAGE_ROOT.rglob("*.js"))


def test_node_unit_tests_are_present():
    assert {path.name for path in NODE_TESTS} >= {"canonical-transaction.test.js", "zip-rewrite.test.js"}


def test_runtime_scripts_include_bar_and_storage_runtimes():
    names = {path.relative_to(PACKAGE_ROOT).as_posix() for path in RUNTIME_SCRIPTS}
    assert names >= {"report.js", "storage.js", "reader-startup.js", "bars/comments.js",
                     "bars/filter.js", "bars/search.js", "bars/settings.js"}


@pytest.mark.parametrize("script", RUNTIME_SCRIPTS,
                         ids=lambda path: path.relative_to(PACKAGE_ROOT).as_posix())
def test_runtime_script_syntax(script: Path):
    if not shutil.which("node"):
        pytest.skip("Node.js is required for the runtime syntax check.")
    result = subprocess.run(["node", "--check", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("script", NODE_TESTS, ids=lambda path: path.name)
def test_node_unit(script: Path):
    if not shutil.which("node"):
        pytest.skip("Node.js is required for the runtime module unit tests.")
    result = subprocess.run(["node", str(script)], cwd=TEST_ROOT.parent, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
