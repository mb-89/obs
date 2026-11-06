"""No test can hang the suite: each test has its tier's timeout (test/bounds.py)."""
import os
import subprocess
import sys
from pathlib import Path

import bounds
import tiers

TEST = Path(__file__).parent


def test_every_test_has_its_tier_timeout(request) -> None:
    items = request.session.items
    assert items
    wrong = [item.nodeid for item in items
             if [mark.args[0] for mark in item.iter_markers("timeout")][:1] != [bounds.TIMEOUTS[bounds.tier(item)]]]
    assert wrong == []


def test_each_test_names_its_tier_in_its_report(request) -> None:
    """The suite records each test's time by the tier its report names (test/suite.py, record_durations)."""
    assert (bounds.TIER_PROPERTY, bounds.tier(request.node)) in request.node.user_properties


def test_the_bounds_name_every_tier() -> None:
    assert tuple(bounds.SLOWEST) == tiers.TIERS
    assert all(bounds.TIMEOUTS[tier] >= bounds.MULTIPLIER * seconds for tier, seconds in bounds.SLOWEST.items())


def test_a_test_past_its_timeout_fails_naming_itself_and_its_timeout(tmp_path: Path) -> None:
    (tmp_path / "conftest.py").write_text("""
import pytest
import bounds

def pytest_collection_modifyitems(items):
    bounds.mark(items)

@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    bounds.explain(item, report)
    return report
""", encoding="utf-8")
    (tmp_path / "test_hangs.py").write_text("""
import threading
import pytest

@pytest.mark.timeout(1)
def test_waits_forever():
    threading.Event().wait()

def test_next():
    pass
""", encoding="utf-8")
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join([str(TEST), os.environ.get("PYTHONPATH", "")])}
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp_path)],
                            cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=60)

    assert result.returncode == 1, result.stdout
    assert "1 failed, 1 passed" in result.stdout
    assert "test/bounds.py: test_hangs.py::test_waits_forever ran past its timeout of 1 s (tier unit" in result.stdout


def test_the_running_test_is_named_in_the_run_folder_while_it_runs(tmp_path: Path, request) -> None:
    item = request.node
    with bounds.running(item, str(tmp_path)):
        assert bounds.running_tests(tmp_path, item.config.rootpath) == [item.nodeid]
        assert bounds.running_tests(tmp_path, tmp_path) == []
    assert bounds.running_tests(tmp_path, item.config.rootpath) == []
