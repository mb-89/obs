"""No test can hang the suite: each test has its tier's timeout (test/bounds.py)."""
import math
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
    assert bounds.TIMEOUTS == {tier: math.ceil(bounds.MULTIPLIER * seconds / 10) * 10
                               for tier, seconds in bounds.SLOWEST.items()}
    assert (bounds.SLOWEST, bounds.SOURCES) == bounds.derive(bounds.COMMITTED, bounds._recorded_runs(), bounds.RUNS,
                                                                bounds.CAP_FACTOR)


COMMITTED = {"unit": 10.9, "browser": 6.0}


def _run(**slowest) -> dict:
    """One recorded run (test/suite.py, record_durations) whose slowest test of each tier is given."""
    return {f"test.x::{tier}": [tier, seconds] for tier, seconds in slowest.items()}


def test_a_slow_hosts_recorded_runs_raise_its_bound() -> None:
    slowest, sources = bounds.derive(COMMITTED, [[_run(browser=11.5)], [_run(browser=3.0)]], runs=10, factor=2)
    assert slowest == {"unit": 10.9, "browser": 11.5}
    assert sources == {"unit": "committed", "browser": "recorded"}


def test_without_records_the_committed_bounds_apply() -> None:
    assert bounds.derive(COMMITTED, [], runs=10, factor=2) == (COMMITTED, {"unit": "committed", "browser": "committed"})


def test_only_the_last_runs_count_and_once_there_are_enough_they_alone_set_the_bound() -> None:
    old, recent = _run(browser=30.0), [_run(browser=2.0, unit=1.0), _run(browser=4.0, unit=0.5)]
    slowest, sources = bounds.derive(COMMITTED, [[old, *recent]], runs=2, factor=2)
    assert slowest == {"unit": 1.0, "browser": 4.0}
    assert sources == {"unit": "recorded", "browser": "recorded"}


def test_a_tier_with_fewer_recorded_runs_falls_back_to_its_committed_bound() -> None:
    slowest, sources = bounds.derive(COMMITTED, [[_run(browser=2.0, unit=1.0), _run(browser=4.0)]], runs=2, factor=2)
    assert slowest == {"unit": 10.9, "browser": 4.0}
    assert sources == {"unit": "committed", "browser": "recorded"}


def test_records_above_the_cap_raise_the_bound_no_further_than_the_cap() -> None:
    slowest, sources = bounds.derive(COMMITTED, [[_run(browser=30.0)]], runs=10, factor=2)
    assert slowest["browser"] == 12.0 and sources["browser"] == "recorded"


def test_a_test_above_its_tiers_cap_is_named_and_one_below_it_is_not() -> None:
    run = {"test.x::slow": ["browser", 12.5], "test.x::loaded": ["browser", 11.9], "test.x::fast": ["unit", 1.0]}
    [message] = bounds.over_cap(run, COMMITTED, factor=2)
    assert message.startswith("test/bounds.py: test.x::slow took 12.5 s, over the browser tier's cap of 12.0 s")
    assert "COMMITTED" in message and "CAP_FACTOR" in message


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
    assert bounds.EXPLAINED_SOURCES[bounds.SOURCES["unit"]] in result.stdout, "it names where its tier's bound came from"


def test_the_running_test_is_named_in_the_run_folder_while_it_runs(tmp_path: Path, request) -> None:
    item = request.node
    with bounds.running(item, str(tmp_path)):
        assert bounds.running_tests(tmp_path, item.config.rootpath) == [item.nodeid]
        assert bounds.running_tests(tmp_path, tmp_path) == []
    assert bounds.running_tests(tmp_path, item.config.rootpath) == []
