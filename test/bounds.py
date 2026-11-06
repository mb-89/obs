"""What bounds each test, so that no test can hang the complete suite.

Reader: whoever changes a test tier, a timeout, or how test/suite.py names a hanging test;
quality.md, Testing boundaries, owns the rule.

Every test of the core and of every adapter gets its tier's timeout (TIMEOUTS) as a
pytest-timeout mark, unless it carries its own; each part's conftest.py calls ``mark`` after its
tiers are assigned. A tier's timeout is MULTIPLIER times its slowest test (setup, call and
teardown) in the complete suite, rounded up to whole tens of seconds; SLOWEST holds those
measurements, so a test that grows past its tier's bound is measured again, not its bound raised
by hand. A test past its timeout fails; ``explain`` adds to its report its name, its timeout,
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

# The slowest test of each tier, in seconds, keyed cheapest first as test/tiers.py orders TIERS,
# on the 4-CPU Linux container of 2026-11-06: unit, dom and browser from two runs of the complete
# suite (`uv run python test/suite.py`, each part's JUnit report: setup, call and teardown); e2e,
# which the complete suite leaves out, from the core's `uv run pytest -m "e2e or browser" -n 4 --durations=12` (call). The external tier needs
# data outside the repository and was not measured; it takes the e2e tier's measurement.
SLOWEST = {"unit": 9.4, "dom": 4.0, "browser": 8.1, "e2e": 22.8, "external": 22.8}
# Each tier's timeout is this multiple of its slowest test: room for a slower machine or a
# busier run, while a hanging test still fails well before test/suite.py's cap.
MULTIPLIER = 3
TIMEOUTS = {tier: math.ceil(MULTIPLIER * seconds / 10) * 10 for tier, seconds in SLOWEST.items()}
# In the run's folder: one file per test process, naming the part and the test it runs.
RUNNING = "running"


def tier(item) -> str:
    """The test's tier: its most expensive tier mark, unit where it has none."""
    return next((name for name in reversed(TIMEOUTS) if item.get_closest_marker(name)), "unit")


def mark(items) -> None:
    """Give each test its tier's timeout, unless it carries its own timeout mark."""
    for item in items:
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
