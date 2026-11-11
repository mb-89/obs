"""The complete suite runs in parallel workers without losing its tier summary or module sharing."""
from collections import Counter
from types import SimpleNamespace

import pytest

import bounds
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

    run = tmp_path / "run"
    reports = {part: suite.part_command(part, ["--durations=10"], {"SE_TEST_REPORTS": str(tmp_path)}, run)
               for part in suite.PARTS}
    unnamed = suite.part_command(suite.ROOT, [], {}, run)

    assert [argument for argument in reports[suite.ROOT] if argument.startswith("--junitxml=")] == [
        f"--junitxml={tmp_path / 'core.xml'}"]
    assert {argument for command in reports.values() for argument in command
            if argument.startswith("--junitxml=")} == {
        f"--junitxml={tmp_path / (suite.part_name(part).replace('/', '-') + '.xml')}" for part in suite.PARTS}
    assert [argument for argument in unnamed if argument.startswith("--junitxml")] == [
        f"--junitxml={run / 'core.xml'}"], "without se's directory, the report goes into the run's folder"


def test_a_part_with_browser_tests_runs_more_workers_than_cpus_and_every_other_part_one_per_cpu(tmp_path) -> None:
    """A part with a Node test package (its browser tests) waits on its pages' frames much of its
    time, so it runs BROWSER_WORKERS_PER_CPU workers per CPU, rounded up; every other part runs one per CPU."""
    import math
    import os

    def workers(part) -> str:
        command = suite.part_command(part, [], {}, tmp_path)
        assert command.count("-n") == 1, command
        return command[command.index("-n") + 1]

    browsers = {package.parents[1] for package in suite.NODE_PACKAGES}
    assert browsers and suite.ROOT not in browsers
    assert 1 < suite.BROWSER_WORKERS_PER_CPU <= 2
    for part in suite.PARTS:
        expected = str(math.ceil(suite.BROWSER_WORKERS_PER_CPU * suite.cpus())) if part in browsers else "auto"
        assert workers(part) == expected


def test_a_part_with_browser_tests_counts_the_cpus_the_process_may_use(tmp_path, monkeypatch) -> None:
    """Pinned to two of a host's four CPUs (taskset, a shared runner), the browser part deals its
    workers for the two it may use, as a 2-CPU runner would, not for the host's four."""
    import os

    browser = next(package.parents[1] for package in suite.NODE_PACKAGES)
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    monkeypatch.setattr(os, "sched_getaffinity", lambda pid: {0, 1}, raising=False)

    command = suite.part_command(browser, [], {}, tmp_path)
    assert command[command.index("-n") + 1] == "3"


def _junit(path, cases) -> None:
    path.write_text("<testsuites><testsuite>" + "".join(
        f'<testcase classname="test.x" name="{name}" time="{seconds}"/>' for name, seconds in cases)
        + "</testsuite></testsuites>", encoding="utf-8")


def test_the_suite_records_each_groups_test_time_from_a_parts_report(tmp_path, monkeypatch) -> None:
    """A group's weight is its tests' time in the part's last report; a group the report does not
    name keeps its earlier weight."""
    monkeypatch.setattr(suite, "WEIGHTS", tmp_path / "weights")
    report = tmp_path / "core.xml"
    _junit(report, [("one@test/test_a.py", 1.0), ("two[x@y]@test/test_a.py", 2.5), ("three@own", 4.0)])
    assert suite.record_weights(report) == {"test/test_a.py": 3.5, "own": 4.0}

    _junit(report, [("one@test/test_a.py", 0.5), ("four", 9.0)])

    assert suite.record_weights(report) == {"test/test_a.py": 0.5, "own": 4.0}
    assert suite.record_weights(tmp_path / "missing.xml") == {}


def _tiered_junit(path, cases) -> None:
    """A part's JUnit report whose cases name their tier, as test/bounds.py's ``mark`` has them do;
    a case is (name, tier, seconds, outcome), outcome an element such as "failure" or None."""
    path.write_text("<testsuites><testsuite>" + "".join(
        f'<testcase classname="test.x" name="{name}" time="{seconds}">'
        + (f'<properties><property name="tier" value="{tier}"/></properties>' if tier else "")
        + (f"<{outcome}/>" if outcome else "") + "</testcase>"
        for name, tier, seconds, outcome in cases) + "</testsuite></testsuites>", encoding="utf-8")


def test_the_suite_records_each_passed_tests_tier_and_time_per_run(tmp_path, monkeypatch) -> None:
    """Each run appends its passed tests' tier and time to the part's record, keeping the last
    runs; a failed or skipped test, or one without a tier, is not a measurement."""
    monkeypatch.setattr(suite, "WEIGHTS", tmp_path / "weights")
    report = tmp_path / "core.xml"
    _tiered_junit(report, [("one@g", "unit", 1.5, None), ("two", "browser", 6.25, None),
                           ("hung", "unit", 30.0, "failure"), ("skip", "dom", 0.0, "skipped"),
                           ("untiered", None, 2.0, None)])

    assert suite.record_durations(report, keep=2) == {"test.x::one@g": ["unit", 1.5], "test.x::two": ["browser", 6.25]}
    _tiered_junit(report, [("one@g", "unit", 2.0, None)])
    suite.record_durations(report, keep=2)
    _tiered_junit(report, [("one@g", "unit", 3.0, None)])

    assert suite.record_durations(report, keep=2) == {"test.x::one@g": ["unit", 3.0]}
    assert suite.recorded_runs() == [[{"test.x::one@g": ["unit", 2.0]}, {"test.x::one@g": ["unit", 3.0]}]]
    assert suite.record_durations(tmp_path / "missing.xml", keep=2) == {}
    assert suite.recorded_runs() == [[{"test.x::one@g": ["unit", 2.0]}, {"test.x::one@g": ["unit", 3.0]}]]


def test_a_part_whose_test_ran_over_its_tiers_cap_fails_naming_it(tmp_path, monkeypatch) -> None:
    """A record-derived bound may not grow past its cap (test/bounds.py, CAP_FACTOR): the part fails."""
    import sys

    import bounds

    monkeypatch.setattr(suite, "WEIGHTS", tmp_path / "weights")
    report = tmp_path / "core.xml"
    cap = round(bounds.CAP_FACTOR * bounds.COMMITTED["unit"], 3)
    _tiered_junit(report, [("slow", "unit", round(cap + 1, 3), None), ("fine", "unit", round(cap - 1, 3), None)])
    monkeypatch.setattr(suite, "part_command", lambda *_: [sys.executable, "-c", "pass"])
    monkeypatch.setattr(suite, "part_report", lambda *_: report)

    code, output = suite.run_part(suite.ROOT, [], tmp_path)

    assert code == 1
    assert f"test/bounds.py: test.x::slow took {round(cap + 1, 3)} s, over the unit tier's cap of {cap} s" in output
    assert "test.x::fine" not in output


_COLLECTION_ERROR = ('<testcase classname="" name="test.test_broken" time="0.0">'
                     '<error message="collection failure">ImportError</error></testcase>')


@pytest.mark.parametrize(("exit_code", "cases", "reason"), [
    (1, _COLLECTION_ERROR, "a test module failed to collect"),
    (2, '<testcase classname="test.x" name="one" time="1.0"/>', "pytest exited with code 2"),
    (3, '<testcase classname="test.x" name="one" time="1.0"/>', "pytest exited with code 3"),
    (5, "", "it ran no tests"),
    (0, None, "it wrote no JUnit report"),
], ids=["collection-error", "interrupted", "internal-error", "no-tests", "no-report"])
def test_a_part_whose_run_did_not_complete_records_no_run_and_says_so(tmp_path, monkeypatch, exit_code, cases,
                                                                        reason) -> None:
    """A crashed, interrupted or empty run is no measurement: recorded, it would shift the derived bounds."""
    import sys

    monkeypatch.setattr(suite, "WEIGHTS", tmp_path / "weights")
    report = tmp_path / "core.xml"
    _tiered_junit(report, [("one@g", "unit", 1.5, None)])
    suite.record_durations(report, keep=2)
    before = suite.recorded_runs()
    report.unlink()
    if cases is not None:
        report.write_text(f"<testsuites><testsuite>{cases}</testsuite></testsuites>", encoding="utf-8")
    monkeypatch.setattr(suite, "part_command", lambda *_: [sys.executable, "-c", f"raise SystemExit({exit_code})"])
    monkeypatch.setattr(suite, "part_report", lambda *_: report)

    _, output = suite.run_part(suite.ROOT, [], tmp_path)

    assert suite.recorded_runs() == before
    assert f"test/suite.py: core: this run is not recorded: {reason}" in output


def test_without_records_no_runs_are_recorded(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(suite, "WEIGHTS", tmp_path / "missing")
    assert suite.recorded_runs() == []


class _Grouped:
    def __init__(self, nodeid, group):
        self.nodeid = nodeid
        self.mark = pytest.mark.xdist_group(group).mark

    def get_closest_marker(self, name):
        return self.mark if name == "xdist_group" else None


def test_groups_are_dealt_heaviest_first_by_their_recorded_weights(tmp_path, monkeypatch) -> None:
    """xdist deals the groups in the order the tests come; an unrecorded group comes first, and a
    part without a record, as on a fresh CI runner, is ordered by the committed weights, a group
    they do not name by its tests' tier weights, keeping its order among equals."""
    monkeypatch.setattr(suite, "WEIGHTS", tmp_path)
    monkeypatch.setattr(suite, "SHARD_WEIGHTS", {"core": {"test/c.py": 9.0, "test/new.py": 0.5}})
    monkeypatch.setattr(suite, "TIER_WEIGHTS", {"unit": 1.0, "dom": 2.0, "browser": 3.0, "external": 4.0})
    items = [_Grouped("test/a.py::one", "test/a.py"), _Grouped("test/b.py::two", "test/b.py"),
             _Grouped("test/a.py::three", "test/a.py"), _Grouped("test/new.py::four", "test/new.py"),
             _Grouped("test/c.py::five", "test/c.py")]
    suite.heaviest_first(suite.ROOT, items, bounds)
    assert [item.nodeid for item in items] == ["test/c.py::five", "test/a.py::one", "test/a.py::three",
                                               "test/b.py::two", "test/new.py::four"], "committed, then tiers"

    (tmp_path / "core.json").write_text('{"test/a.py": 1.0, "test/b.py": 7.5, "test/c.py": 3.0}',
                                        encoding="utf-8")
    suite.heaviest_first(suite.ROOT, items, bounds)

    assert [item.nodeid for item in items] == ["test/new.py::four", "test/b.py::two", "test/c.py::five",
                                               "test/a.py::one", "test/a.py::three"]


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
    monkeypatch.setattr(suite, "part_command", lambda part, *_: [sys.executable, "-c", hang])
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


@pytest.mark.parametrize("on_actions", [False, True])
def test_the_suite_names_its_host_and_says_when_its_parts_took_longer_than_the_limit(monkeypatch, capsys,
                                                                                    on_actions) -> None:
    import os

    monkeypatch.setattr(suite, "run_part", lambda part, arguments, run_folder: (0, ""))
    monkeypatch.setattr(suite, "is_installed", lambda package: True)
    monkeypatch.setenv("GITHUB_ACTIONS", "true") if on_actions else monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    limit = suite.limit_seconds()
    times = iter([0.0, limit + 5.0])

    assert suite.main([], clock=lambda: next(times)) == 0
    out = capsys.readouterr().out
    assert f"test/suite.py: host: {os.cpu_count()} CPUs" in out
    over = (f"test/suite.py: the parts took {limit + 5.0:.1f} s, over the suite's {limit:g} s limit "
            "([tests] limit_seconds in se.toml)")
    assert over in out
    assert (f"::warning title=Suite over its time limit::{over}" in out) == on_actions


def test_the_suite_says_nothing_of_the_limit_or_the_target_within_them(monkeypatch, capsys) -> None:
    monkeypatch.setattr(suite, "run_part", lambda part, arguments, run_folder: (0, ""))
    monkeypatch.setattr(suite, "is_installed", lambda package: True)
    times = iter([0.0, suite.target_seconds() - 1.0])

    assert suite.main([], clock=lambda: next(times)) == 0
    out = capsys.readouterr().out
    assert "limit" not in out and "target" not in out and "slowest" not in out


def _write_report(path, cases) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("<testsuites><testsuite>" + "".join(
        f'<testcase classname="{classname}" name="{name}" time="{seconds}"/>' for classname, name, seconds in cases)
        + "</testsuite></testsuites>", encoding="utf-8")


@pytest.mark.parametrize(("over", "on_actions"), [("target", False), ("target", True), ("limit", True)])
def test_a_suite_past_its_target_or_limit_names_its_slowest_tests(monkeypatch, capsys, tmp_path, over,
                                                                   on_actions) -> None:
    def run_part(part, arguments, run_folder):
        cases = [("test.test_slow", "test_slowest", 9.5), ("test.test_slow", "test_quick", 0.1)]
        if part != suite.ROOT:
            cases = [(f"test.test_{index}", "test_middle", 1.0 + index / 2) for index in range(suite.SLOWEST_NAMED)]
        _write_report(suite.part_report(part, os.environ, run_folder), cases)
        return 0, ""

    import os

    monkeypatch.setattr(suite, "run_part", run_part)
    monkeypatch.setattr(suite, "is_installed", lambda package: True)
    monkeypatch.setenv(suite.REPORTS_VARIABLE, str(tmp_path))
    monkeypatch.setenv("GITHUB_ACTIONS", "true") if on_actions else monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    bound = suite.target_seconds() if over == "target" else suite.limit_seconds()
    took = (suite.target_seconds() + suite.limit_seconds()) / 2 if over == "target" else suite.limit_seconds() + 1.0
    times = iter([0.0, took])

    assert suite.main([], clock=lambda: next(times)) == 0
    out = capsys.readouterr().out
    line = (f"test/suite.py: the parts took {took:.1f} s, over the suite's {bound:g} s {over} "
            f"([tests] {over}_seconds in se.toml); its {suite.SLOWEST_NAMED} slowest tests:")
    assert line in out
    listed = out.split(line, 1)[1].splitlines()[1:suite.SLOWEST_NAMED + 1]
    assert listed[0] == "  9.50 s core test.test_slow::test_slowest"
    assert all(entry.startswith("  ") and " s " in entry for entry in listed)
    assert "test_quick" not in out, "only the slowest tests are named"
    seconds = [float(entry.split(" s ", 1)[0]) for entry in listed]
    assert seconds == sorted(seconds, reverse=True)
    title = "Suite over its time target" if over == "target" else "Suite over its time limit"
    assert (f"::warning title={title}::{line[:-1]}: 9.50 s core test.test_slow::test_slowest; " in out) == on_actions


@pytest.mark.parametrize("on_actions", [False, True])
def test_the_suite_names_a_test_far_slower_than_its_tiers_typical_time(monkeypatch, capsys, tmp_path,
                                                                       on_actions) -> None:
    """The tiers are taken over every part, and the run does not fail on it."""
    def run_part(part, arguments, run_folder):
        cases = [(f"usual_{index}", "unit", 2.0) for index in range(20)] if part == suite.ROOT else [
            ("builds_the_spec", "unit", 29.2), ("fast", "unit", 0.01)]
        _report(suite.part_report(part, os.environ, run_folder), cases)
        return 0, ""

    import os

    monkeypatch.setattr(suite, "run_part", run_part)
    monkeypatch.setattr(suite, "is_installed", lambda package: True)
    monkeypatch.setenv(suite.REPORTS_VARIABLE, str(tmp_path))
    monkeypatch.setenv("GITHUB_ACTIONS", "true") if on_actions else monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    assert suite.main([]) == 0
    out = capsys.readouterr().out
    [line] = [line for line in out.splitlines() if line.startswith("test/bounds.py: ")]
    part = suite.part_name(next(part for part in suite.PARTS if part != suite.ROOT)).replace("/", "-")
    assert line.startswith(f"test/bounds.py: {part} test.x::builds_the_spec took 29.2 s, over")
    assert (f"::warning title=Test far slower than its tier::{line}" in out) == on_actions


class _Tiered(_Grouped):
    def __init__(self, nodeid, group, tier="unit"):
        super().__init__(nodeid, group)
        self.tier_mark = getattr(pytest.mark, tier).mark

    def get_closest_marker(self, name):
        return self.mark if name == "xdist_group" else self.tier_mark if name == self.tier_mark.name else None


class _Deselecting:
    def __init__(self, rootpath=suite.ROOT):
        self.rootpath = rootpath
        self.deselected = []
        self.hook = SimpleNamespace(pytest_deselected=lambda items: self.deselected.extend(items))


def _shard_items():
    return [_Tiered("a.py::one", "a", "browser"), _Tiered("c.py::one", "c"), _Tiered("a.py::two", "a", "browser"),
            _Tiered("d.py::one", "d"), _Tiered("c.py::two", "c"), _Tiered("b.py::one", "b", "browser"),
            _Tiered("e.py::one", "e"), _Tiered("c.py::three", "c")]


def test_the_deal_puts_the_heaviest_group_on_the_lightest_shard_and_is_the_same_for_the_same_input() -> None:
    """Greedy largest-first: each group, heaviest first, goes to the shard with the least weight so
    far, ties to the lower-numbered shard and, among equal weights, by name; the order the groups
    come in changes nothing."""
    weights = {"a": 5.0, "b": 4.0, "c": 3.0, "d": 3.0, "e": 1.0, "f": 1.0}
    shards = suite.deal(weights, 2)
    assert shards == [{"a", "d", "f"}, {"b", "c", "e"}]
    assert suite.deal(dict(reversed(weights.items())), 2) == shards
    assert sorted(name for shard in suite.deal(weights, 3) for name in shard) == sorted(weights)


def test_each_test_lands_in_exactly_one_shard_dealt_by_committed_weights_else_tier_weights(monkeypatch) -> None:
    """A group with a committed weight is dealt by it (SHARD_WEIGHTS); one without, by its tests'
    tier weights (TIER_WEIGHTS). Every shard's job computes the same deal, so each test runs once."""
    monkeypatch.setattr(suite, "SHARD_WEIGHTS", {"core": {"c": 10.0, "e": 4.0}})
    monkeypatch.setattr(suite, "TIER_WEIGHTS", {"unit": 1.0, "dom": 2.0, "browser": 3.0, "external": 4.0})
    kept = {}
    for shard in (1, 2):
        monkeypatch.setenv(suite.SHARD_VARIABLE, f"{shard}/2")
        items, config = _shard_items(), _Deselecting()
        with pytest.warns(UserWarning, match="lacks the groups a, b, d;"):
            suite.keep_shard(config, items, bounds)
        kept[shard] = [item.nodeid for item in items]
        assert sorted(kept[shard] + [item.nodeid for item in config.deselected]) == sorted(
            item.nodeid for item in _shard_items())
    # c 10 (committed) -> 1; a 6 (two browser tests) -> 2; e 4 (committed) -> 2, now 10 each;
    # b 3 (one browser test) -> 1, the lower-numbered of equals; d 1 (one unit test) -> 2.
    assert kept == {1: ["c.py::one", "c.py::two", "b.py::one", "c.py::three"],
                    2: ["a.py::one", "a.py::two", "d.py::one", "e.py::one"]}
    assert not set(kept[1]) & set(kept[2])


def test_without_a_shard_every_test_is_kept(monkeypatch) -> None:
    items, config = _shard_items(), _Deselecting()
    suite.keep_shard(config, items, bounds)
    assert len(items) == len(_shard_items()) and config.deselected == []


def test_the_suite_runs_each_part_on_the_shard_it_names(monkeypatch, capsys) -> None:
    import os

    seen = []
    monkeypatch.setattr(suite, "run_part", lambda part, arguments, run_folder:
                        seen.append((os.environ.get(suite.SHARD_VARIABLE), arguments)) or (0, ""))
    monkeypatch.setattr(suite, "is_installed", lambda package: True)

    assert suite.main(["--shard", "2/3", "-x"]) == 0
    assert seen == [("2/3", ["-x"])] * len(suite.PARTS)
    assert "test/suite.py: shard 2 of 3" in capsys.readouterr().out
    assert suite.SHARD_VARIABLE not in os.environ


@pytest.mark.parametrize("shard", ["3/2", "0/2", "two", "1/0"])
def test_a_shard_outside_its_count_is_refused(monkeypatch, capsys, shard) -> None:
    monkeypatch.setattr(suite, "is_installed", lambda package: True)
    assert suite.main(["--shard", shard]) == 2
    assert f"test/suite.py: --shard {shard}" in capsys.readouterr().err


def test_a_shards_run_is_checked_against_the_cap_but_not_recorded(tmp_path, monkeypatch) -> None:
    """A shard's run holds part of the part's tests: recorded, it would lower its tiers' bounds."""
    import sys

    import bounds

    monkeypatch.setattr(suite, "WEIGHTS", tmp_path / "weights")
    monkeypatch.setenv(suite.SHARD_VARIABLE, "1/2")
    report = tmp_path / "core.xml"
    cap = bounds.CAP_FACTOR * bounds.COMMITTED["unit"]
    _tiered_junit(report, [("slow@g", "unit", cap + 1, None)])
    monkeypatch.setattr(suite, "part_command", lambda *_: [sys.executable, "-c", "raise SystemExit(5)"])
    monkeypatch.setattr(suite, "part_report", lambda *_: report)

    code, output = suite.run_part(suite.ROOT, [], tmp_path)

    assert code == 1 and "test.x::slow@g" in output
    assert not (tmp_path / "weights").exists()


def test_a_pytest_a_test_starts_is_not_sharded(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(suite.SHARD_VARIABLE, "2/2")
    items, config = _shard_items(), _Deselecting(rootpath=tmp_path)
    suite.keep_shard(config, items, bounds)
    assert len(items) == len(_shard_items()) and config.deselected == []


def test_the_suites_tests_pass_in_a_run_that_was_dealt_a_shard(tmp_path) -> None:
    """CI runs the suite with --shard, whose variable every test process inherits; the tests of the
    suite and its bounds do not see it (test/conftest.py, suite_environment). Rooted outside the
    parts, the inner pytest itself is not sharded (keep_shard) and runs every test named."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    import spec_build

    environment = {**os.environ, suite.SHARD_VARIABLE: "1/2"}
    environment.pop(spec_build.RUN_FOLDER, None)
    environment.pop(suite.REPORTS_VARIABLE, None)
    tests = [str(Path(__file__).with_name(name)) for name in ("test_parallel_suite.py", "test_bounds.py")]
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:xdist", "-p", "no:cacheprovider",
                             f"--rootdir={tmp_path}", "-k", "not dealt_a_shard", *tests],
                            cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=120)

    # Only this test is deselected (-k): no shard took the others away.
    assert result.returncode == 0 and " passed, 1 deselected" in result.stdout, result.stdout[-3000:]


def test_each_committed_group_that_names_a_module_names_one_of_its_parts() -> None:
    """A renamed or removed test module would leave its committed weight unused (SHARD_WEIGHTS)."""
    parts = {suite.part_name(part): part for part in suite.PARTS}
    missing = [f"{part}: {group}" for part, groups in suite.SHARD_WEIGHTS.items() for group in groups
               if group.endswith(".py") and not (parts[part] / group).is_file()]
    assert missing == []


def _report(path, cases) -> None:
    """A JUnit report of (name, tier, seconds) cases, as a part's pytest writes it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("<testsuites><testsuite>" + "".join(
        f'<testcase classname="test.x" name="{name}" time="{seconds}"><properties>'
        f'<property name="{bounds.TIER_PROPERTY}" value="{tier}"/></properties></testcase>'
        for name, tier, seconds in cases) + "</testsuite></testsuites>", encoding="utf-8")


def test_the_weights_are_measured_from_ci_runs_reports_and_print_as_their_constants(tmp_path, capsys) -> None:
    """Each group's time summed per run and averaged over the runs; each tier's mean time per test,
    an unmeasured tier at the costliest measured one; printed as the source pasted over them."""
    first, second = tmp_path / "run-1", tmp_path / "run-2"
    _report(first / "junit-shard-1" / "core.xml", [("a@test/a.py", "unit", 1.0), ("b@test/a.py", "unit", 2.0)])
    _report(first / "junit-shard-2" / "core.xml", [("c@own", "browser", 4.0)])
    _report(first / "junit-shard-2" / "adapters-html.xml", [("d@test/d.py", "dom", 0.5)])
    _report(second / "core.xml", [("a@test/a.py", "unit", 2.0), ("b@test/a.py", "unit", 1.0), ("c@own", "browser", 2.0)])

    assert suite.main([suite.MEASURE, str(first), str(second)]) == 0
    constants = {}
    exec(capsys.readouterr().out, constants)  # The output is the source pasted into test/suite.py.

    assert constants["SHARD_WEIGHTS"] == {"core": {"test/a.py": 3.0, "own": 3.0},
                                          "adapters/html": {"test/d.py": 0.5}}
    assert constants["TIER_WEIGHTS"] == {"unit": 1.5, "dom": 0.5, "browser": 3.0, "build": 3.0, "external": 3.0}


def test_measuring_without_a_run_folder_is_refused(tmp_path, capsys) -> None:
    assert suite.main([suite.MEASURE]) == 2
    assert suite.main([suite.MEASURE, str(tmp_path / "missing")]) == 2
    assert f"test/suite.py: {suite.MEASURE}" in capsys.readouterr().err


def test_a_group_the_committed_weights_lack_is_dealt_by_tier_weights_with_a_warning(monkeypatch) -> None:
    monkeypatch.setattr(suite, "SHARD_WEIGHTS", {"core": {"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0}})
    monkeypatch.setenv(suite.SHARD_VARIABLE, "1/2")
    items, config = _shard_items(), _Deselecting()
    with pytest.warns(UserWarning, match=r"core: SHARD_WEIGHTS lacks the groups e;"):
        suite.keep_shard(config, items, bounds)
    assert len(items) + len(config.deselected) == len(_shard_items())
