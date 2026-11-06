"""What bounds each test, so that no test can hang the complete suite.

Reader: whoever changes a test tier, a timeout, or how test/suite.py names a hanging test;
quality.md, Testing boundaries, owns the rule.

Every test of the core and of every adapter gets its tier's timeout (TIMEOUTS) as a
pytest-timeout mark, unless it carries its own; each part's conftest.py calls ``mark`` after its
tiers are assigned. A tier's timeout is MULTIPLIER times its slowest test (setup, call and
teardown) in the complete suite, rounded up to whole tens of seconds. SLOWEST holds those
measurements, derived at import from the runs test/suite.py recorded on this host (``derive``,
the last RUNS of each part) and falling back to the committed measurement (COMMITTED) where a
tier has fewer recorded runs; a loaded host's runs raise its own bounds, and nobody types one. A test past its timeout fails; ``explain`` adds to its report its name, its timeout,
its tier and this file.

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
# orders TIERS, which SLOWEST falls back to where a host has fewer recorded runs (derive). Measured
# on the 4-CPU Linux container of 2026-11-06: unit, dom and browser from two runs of the complete
# suite (`uv run python test/suite.py`, each part's JUnit report: setup, call and teardown), again
# after the core's controller started the run's shared build of the spec as its session started; e2e,
# which the complete suite leaves out, from the core's `uv run pytest -m "e2e or browser" -n 4 --durations=12` (call). The external tier needs
# data outside the repository and was not measured; it takes the e2e tier's measurement.
COMMITTED = {"unit": 10.9, "dom": 1.9, "browser": 6.0, "e2e": 22.8, "external": 22.8}
# How many of a part's recorded runs (test/suite.py, record_durations) the suite keeps and SLOWEST
# is derived from.
RUNS = 10
# Each tier's timeout is this multiple of its slowest test: room for a slower machine or a
# busier run, while a hanging test still fails well before test/suite.py's cap.
MULTIPLIER = 3


def derive(committed: dict[str, float], parts_runs: list[list[dict[str, list]]], runs: int):
    """Each tier's slowest test over each part's last ``runs`` recorded runs (a run maps each test
    to its tier and seconds), and where each came from, "recorded" or "committed". A tier recorded
    in fewer than ``runs`` runs keeps its committed value where that is slower."""
    samples = {tier: [] for tier in committed}
    for part_runs in parts_runs:
        for run in part_runs[-runs:]:
            slowest_in_run = {}
            for tier, seconds in run.values():
                slowest_in_run[tier] = max(seconds, slowest_in_run.get(tier, 0.0))
            for tier, seconds in slowest_in_run.items():
                samples.setdefault(tier, []).append(seconds)
    slowest, sources = {}, {}
    for tier, seconds in committed.items():
        recorded = max(samples[tier], default=0.0)
        enough = len(samples[tier]) >= runs
        slowest[tier] = recorded if enough else max(recorded, seconds)
        sources[tier] = "recorded" if enough or recorded > seconds else "committed"
    return slowest, sources


def _recorded_runs() -> list[list[dict[str, list]]]:
    """test/suite.py's recorded runs, loaded by its path: an adapter's conftest.py loads this module
    without test/ on its path."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("suite", Path(__file__).with_name("suite.py"))
    suite = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(suite)
    return suite.recorded_runs()


# Each tier's slowest test, derived from the recorded runs at import, and where it came from.
SLOWEST, SOURCES = derive(COMMITTED, _recorded_runs(), RUNS)
TIMEOUTS = {tier: math.ceil(MULTIPLIER * seconds / 10) * 10 for tier, seconds in SLOWEST.items()}
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
    """Name the test, its timeout and its tier in the report of a test past its timeout."""
    if not timed_out(report):
        return
    seconds = item.get_closest_marker("timeout").args[0]
    report.sections.append(("test/bounds.py", (
        f"test/bounds.py: {item.nodeid} ran past its timeout of {seconds} s (tier {tier(item)}, TIMEOUTS) and "
        "failed. Remedy: run it alone to find what it waits for; where it has grown slower, measure its tier "
        "again (SLOWEST) rather than raising its timeout by hand.")))


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
