"""What bounds each test, so that no test can hang the complete suite.

Reader: whoever changes a test tier, a timeout, or how test/suite.py names a hanging test;
quality.md, Testing boundaries, owns the rule.

Every test of the core and of every adapter gets its tier's timeout (TIMEOUTS) as a
pytest-timeout mark, unless it carries its own; each part's conftest.py calls ``mark`` after its
tiers are assigned. A tier's timeout is MULTIPLIER times its slowest test (setup, call and
teardown) in the complete suite, rounded up to whole tens of seconds. SLOWEST holds those
measurements, derived at import from the runs test/suite.py recorded on this host (``derive``,
the last RUNS of each part) and falling back to the committed measurement (COMMITTED) where a
tier has fewer recorded runs; a loaded host's runs raise its own bounds, and nobody types one.
The committed measurement caps the derived one at CAP_FACTOR times it: a test past that fails the
suite (``over_cap``), so a slowly regressing test cannot raise its own timeout. A test past its
timeout fails; ``explain`` adds to its report its name, its timeout, its tier and this file.
A test far slower than its tier's typical time (``outliers``, OUTLIER_FACTOR) loosens that bound
for every other test of the tier; test/suite.py names each one in a warning as the run ends.

While a test runs, ``running`` names it in the run's folder (the folder test/suite.py makes, in
RUNNING), one file per test process, so test/suite.py, when its cap is reached, names the
tests each part was still running (``running_tests``).
"""
import contextlib
import math
import os
from pathlib import Path

import pytest

# The committed slowest test of each tier, in seconds, keyed cheapest first as test/tiers.py
# orders TIERS, which SLOWEST falls back to where a host has fewer recorded runs (derive): on a
# fresh CI runner, always. So it is measured on two CPUs, as CI's runners give the suite about:
# on the 4-CPU Linux container of 2026-11-11 (Intel Xeon @ 2.10GHz) pinned to two of them,
# unit, dom, browser and build are the slowest test of each tier over two runs of the complete
# suite, `SE_TEST_REPORTS=<folder> taskset -c 0,1 uv run python test/suite.py`, from each part's
# JUnit report (setup, call and teardown, passed tests only), rounded up to a tenth of a second.
# Unit was measured again so, once no worker rebuilt the spec privately; dom, browser and build
# keep their earlier measurement, since the same runs' lower browser bound (20 s) failed CI on a
# test that takes about a second here.
# External is unmeasured: its tests need data outside the repository, so the complete suite never
# runs them; it keeps 22.8, the slowest test once measured above the browser tier (2026-11-06).
COMMITTED = {"unit": 13.3, "dom": 7.8, "browser": 12.6, "build": 32.2, "external": 22.8}
# How many of a part's recorded runs (test/suite.py, record_durations) the suite keeps and SLOWEST
# is derived from.
RUNS = 10
# A record-derived slowest test may not exceed this multiple of its tier's committed one; a test
# past it fails the suite (over_cap), so a slowly regressing test cannot raise its own timeout.
CAP_FACTOR = 3
# A test slower than this multiple of its tier's typical time in a run (outliers) is named in a
# warning, which does not fail the run: the sign of a test in the wrong tier.
OUTLIER_FACTOR = 3
# Each tier's timeout is this multiple of its slowest test: room for a slower machine or a
# busier run, while a hanging test still fails well before test/suite.py's cap.
MULTIPLIER = 3


def derive(committed: dict[str, float], parts_runs: list[list[dict[str, list]]], runs: int, factor: float):
    """Each tier's slowest test over each part's last ``runs`` recorded runs (a run maps each test
    to its tier and seconds; a run with no test timed counts for nothing), and where each came from,
    "recorded" or "committed". A tier recorded in fewer than ``runs`` runs keeps its committed value
    where that is slower; no recorded value exceeds ``factor`` times the committed one (over_cap
    fails the run that records one)."""
    samples = {tier: [] for tier in committed}
    for part_runs in parts_runs:
        # A run with no tests or no timings (an old one recorded from a crashed part) counts for nothing.
        timed = [run for run in part_runs if any(seconds > 0 for _, seconds in run.values())]
        for run in timed[-runs:]:
            slowest_in_run = {}
            for tier, seconds in run.values():
                slowest_in_run[tier] = max(seconds, slowest_in_run.get(tier, 0.0))
            for tier, seconds in slowest_in_run.items():
                samples.setdefault(tier, []).append(seconds)
    slowest, sources = {}, {}
    for tier, seconds in committed.items():
        recorded = min(max(samples[tier], default=0.0), factor * seconds)
        enough = len(samples[tier]) >= runs
        slowest[tier] = recorded if enough else max(recorded, seconds)
        sources[tier] = "recorded" if enough or recorded > seconds else "committed"
    return slowest, sources


def over_cap(run: dict[str, list], committed: dict[str, float], factor: float) -> list[str]:
    """For each test of a recorded run slower than ``factor`` times its tier's committed slowest
    test, a message naming it, its time, the cap and the remedy."""
    return [f"test/bounds.py: {test} took {seconds} s, over the {tier} tier's cap of {round(factor * committed[tier], 3)} s "
            f"(CAP_FACTOR {factor} times COMMITTED {committed[tier]} s). Remedy: find what made it slower and "
            "make it fast again, or, where it rightly takes longer, measure COMMITTED again by the method its "
            "comment in test/bounds.py names."
            for test, (tier, seconds) in sorted(run.items()) if seconds > factor * committed.get(tier, math.inf)]


def typical(seconds: list[float]) -> float:
    """A tier's typical test time: ordering its tests' times from the fastest, the time of the test
    at which half the tier's test time is reached, a median of the tier's time rather than of its
    count of tests, which its many tests of a few milliseconds would set; 0 for no test."""
    total, reached = sum(seconds), 0.0
    for value in sorted(seconds):
        reached += value
        if reached >= total / 2:
            return value
    return 0.0


def outliers(run: dict[str, list], factor: float) -> list[str]:
    """For each test of a run slower than ``factor`` times its tier's typical time (typical) in that
    run, a warning naming it, its time, its tier's typical time and the remedy, slowest first: the
    sign of a test in the wrong tier, which loosens its tier's timeout for every other test of it."""
    times: dict[str, list[float]] = {}
    for tier, seconds in run.values():
        times.setdefault(tier, []).append(seconds)
    usual = {tier: typical(seconds) for tier, seconds in times.items()}
    return [f"test/bounds.py: {test} took {seconds} s, over {factor} times its {tier} tier's typical "
            f"{round(usual[tier], 3)} s (OUTLIER_FACTOR, typical). Remedy: check its tier by the rule in "
            "spec/design_input/quality.md, Testing boundaries, and mark the tier it belongs in, or make it "
            "faster."
            for test, (tier, seconds) in sorted(run.items(), key=lambda item: (-item[1][1], item[0]))
            if usual[tier] and seconds > factor * usual[tier]]


def _recorded_runs() -> list[list[dict[str, list]]]:
    """test/suite.py's recorded runs, loaded by its path: an adapter's conftest.py loads this module
    without test/ on its path."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("suite", Path(__file__).with_name("suite.py"))
    suite = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(suite)
    return suite.recorded_runs()


# Each tier's slowest test, derived from the recorded runs at import, and where it came from.
SLOWEST, SOURCES = derive(COMMITTED, _recorded_runs(), RUNS, CAP_FACTOR)
TIMEOUTS = {tier: math.ceil(MULTIPLIER * seconds / 10) * 10 for tier, seconds in SLOWEST.items()}
# How ``explain`` names where a tier's bound came from (SOURCES).
EXPLAINED_SOURCES = {"recorded": f"SLOWEST recorded on this host over its last {RUNS} runs, test/suite.py",
                     "committed": "SLOWEST committed as COMMITTED"}
# The JUnit testcase property naming a test's tier, from which test/suite.py records its time.
TIER_PROPERTY = "tier"
# In the run's folder: one file per test process, naming the part and the test it runs.
RUNNING = "running"


def tier(item) -> str:
    """The test's tier: its most expensive tier mark, unit where it has none."""
    return next((name for name in reversed(TIMEOUTS) if item.get_closest_marker(name)), "unit")


def mark(items) -> None:
    """Give each test its tier's timeout, unless it carries its own timeout mark, and name its tier
    in its report (TIER_PROPERTY)."""
    for item in items:
        item.user_properties.append((TIER_PROPERTY, tier(item)))
        if not item.get_closest_marker("timeout"):
            item.add_marker(pytest.mark.timeout(TIMEOUTS[tier(item)]))


def timed_out(report) -> bool:
    """Whether the report is of a test phase pytest-timeout stopped."""
    text = str(report.longrepr) if report.failed else ""
    return "Timeout" in text and "pytest-timeout" in text


def explain(item, report) -> None:
    """Name the test, its timeout, its tier and where its tier's bound came from in the report of a
    test past its timeout."""
    if not timed_out(report):
        return
    seconds = item.get_closest_marker("timeout").args[0]
    name = tier(item)
    report.sections.append(("test/bounds.py", (
        f"test/bounds.py: {item.nodeid} ran past its timeout of {seconds} s (tier {name}, TIMEOUTS from "
        f"{EXPLAINED_SOURCES[SOURCES[name]]}) and failed. Remedy: run it alone to find what it waits for; "
        "where it has grown slower, run it in the complete suite (test/suite.py), whose recorded runs raise "
        "its tier's bound (SLOWEST), rather than raising its timeout by hand.")))


@contextlib.contextmanager
def running(item, run_folder: str | None):
    """While the test runs, name it in the run's folder (RUNNING), where test/suite.py made one."""
    if not run_folder:
        yield
        return
    record = Path(run_folder) / RUNNING / f"{os.getpid()}.txt"
    record.parent.mkdir(exist_ok=True)
    record.write_text(f"{item.config.rootpath}\n{item.nodeid}", encoding="utf-8")
    try:
        yield
    finally:
        record.unlink(missing_ok=True)


def running_tests(run_folder: Path, part: Path) -> list[str]:
    """The tests the part's processes are running, as ``running`` names them in the run's folder."""
    found = []
    for record in sorted((run_folder / RUNNING).glob("*.txt")):
        with contextlib.suppress(OSError):
            root, nodeid = record.read_text(encoding="utf-8").split("\n", 1)
            if Path(root) == part:
                found.append(nodeid)
    return sorted(found)
