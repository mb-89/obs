"""The complete suite runs in parallel workers without losing its tier summary or module sharing."""
from collections import Counter
from types import SimpleNamespace

import pytest

import suite
import tiers
from conftest import group_by_module


def _config(**attributes):
    return SimpleNamespace(stash=pytest.Stash(), **attributes)


def test_the_controller_summarises_the_tiers_and_skips_its_workers_saw() -> None:
    controller = _config()
    for skips in ([("test/a.py::one", "no browser")], [("test/b.py::two", "no browser")]):
        worker = _config(workeroutput={})
        worker.stash[tiers._TIER_KEY] = {"test/a.py::one": "unit", "test/b.py::two": "browser"}
        worker.stash[tiers._DESELECTED_KEY] = Counter({"browser": 1})
        worker.stash[tiers._SKIPS_KEY] = skips
        tiers.worker_finish(worker)
        tiers.node_down(controller, SimpleNamespace(workeroutput=worker.workeroutput))

    assert controller.stash[tiers._TIER_KEY] == {"test/a.py::one": "unit", "test/b.py::two": "browser"}
    assert controller.stash[tiers._DESELECTED_KEY] == Counter({"browser": 1})
    assert controller.stash[tiers._SKIPS_KEY] == [("test/a.py::one", "no browser"),
                                                 ("test/b.py::two", "no browser")]


def test_a_module_runs_on_one_worker_unless_a_test_names_its_own_group() -> None:
    class Item:
        def __init__(self, nodeid, group=None):
            self.nodeid = nodeid
            self.marks = [pytest.mark.xdist_group(group).mark] if group else []

        def get_closest_marker(self, name):
            return next((mark for mark in self.marks if mark.name == name), None)

        def add_marker(self, marker):
            self.marks.append(marker.mark)

    items = [Item("test/test_a.py::one"), Item("test/test_a.py::two[x]"), Item("test/test_b.py::three", "own")]
    group_by_module(items)

    assert [item.get_closest_marker("xdist_group").args[0] for item in items] == [
        "test/test_a.py", "test/test_a.py", "own"]


def test_each_part_writes_its_junit_report_into_the_directory_se_names(tmp_path) -> None:
    import suite

    reports = {part: suite.part_command(part, ["--durations=10"], {"SE_TEST_REPORTS": str(tmp_path)})
               for part in suite.PARTS}
    unnamed = suite.part_command(suite.ROOT, [], {})

    assert [argument for argument in reports[suite.ROOT] if argument.startswith("--junitxml=")] == [
        f"--junitxml={tmp_path / 'core.xml'}"]
    assert {argument for command in reports.values() for argument in command
            if argument.startswith("--junitxml=")} == {
        f"--junitxml={tmp_path / (suite.part_name(part).replace('/', '-') + '.xml')}" for part in suite.PARTS}
    assert not [argument for argument in unnamed if argument.startswith("--junitxml")]


def test_the_parts_run_side_by_side_and_any_failed_part_fails_the_suite(monkeypatch, capsys) -> None:
    import threading

    import suite

    together = threading.Barrier(len(suite.PARTS), timeout=10)

    def run_part(part, arguments, run_folder):
        together.wait()
        return (1 if part == suite.ROOT else 0), f"== {suite.part_name(part)} {arguments}\n"

    monkeypatch.setattr(suite, "run_part", run_part)
    monkeypatch.setattr(suite, "is_installed", lambda package: True)

    assert suite.main(["-x"]) == 1
    output = capsys.readouterr()
    assert all(f"== {suite.part_name(part)} ['-x']" in output.out for part in suite.PARTS)
    assert "failed parts: core." in output.err


def test_a_part_past_the_suite_cap_is_stopped_naming_the_test_it_was_running(monkeypatch, capsys) -> None:
    import sys

    import suite

    # Each part's command names a test in the run's folder, as test/bounds.py does, and waits forever.
    hang = ("import os, pathlib, threading; record = pathlib.Path(os.environ['OBS_SPEC_BUILD'], 'running', "
            "str(os.getpid()) + '.txt'); record.parent.mkdir(exist_ok=True); "
            "record.write_text(os.getcwd() + '\\ntest/test_hangs.py::test_waits'); print('started', flush=True); "
            "threading.Event().wait()")
    monkeypatch.setattr(suite, "part_command", lambda part, arguments, environment: [sys.executable, "-c", hang])
    monkeypatch.setattr(suite, "is_installed", lambda package: True)
    monkeypatch.setattr(suite, "CAP_SECONDS", 1)

    assert suite.main([]) == 1
    output = capsys.readouterr()
    for part in suite.PARTS:
        assert (f"test/suite.py: {suite.part_name(part)} reached the suite's cap of 1 s (CAP_SECONDS) "
                "and was stopped while running test/test_hangs.py::test_waits") in output.out
    assert f"failed parts: {', '.join(map(suite.part_name, suite.PARTS))}." in output.err


class _Report:
    """A part's JUnit report as pytest's junitxml plugin holds it: its testsuite properties."""
    def __init__(self):
        self.properties = []

    def add_global_property(self, name, value):
        self.properties.append((name, value))


def _xdist_config(options, report=None, **attributes):
    from _pytest.junitxml import xml_key

    config = _config(getoption=lambda name, default=None: options.get(name, default), **attributes)
    if report is not None:
        config.stash[xml_key] = report
    return config


@pytest.mark.parametrize(("options", "workers"), [
    ({"dist": "loadgroup", "tx": ["popen"] * 4}, 4),
    ({"dist": "no", "tx": []}, 1),
    ({}, 1),
])
def test_a_part_writes_its_worker_count_as_its_reports_workers_property(options, workers) -> None:
    """se's work_tickets.py suite divides a part's test time by its report's `workers` property."""
    report = _Report()
    assert suite.record_workers(_xdist_config(options, report)) == workers
    assert report.properties == [(suite.WORKERS_PROPERTY, workers)]


def test_a_worker_or_a_run_without_a_report_writes_no_workers_property() -> None:
    report = _Report()
    assert suite.record_workers(_xdist_config({"dist": "load", "tx": ["popen"] * 2}, report, workerinput={})) is None
    assert suite.record_workers(_xdist_config({"dist": "load", "tx": ["popen"] * 2})) is None
    assert report.properties == []
