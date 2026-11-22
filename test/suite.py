"""Run the complete suite: the core's, each part in its own pytest.

Reader: whoever runs or changes the complete suite, and CI.

It runs every test of the core except the external tier's, which needs
hand-supplied inputs (test/tiers.py). Its time budget is `[tests]` in `se.toml`.

Each part tests only itself, with its own `pyproject.toml` settings and `conftest.py`, so each
runs as its own pytest process from its own folder, its tests spread over one worker process
per CPU, a part with browser tests over BROWSER_WORKERS_PER_CPU per CPU (pytest-xdist,
`-n auto --dist loadgroup`: a module's tests share a worker; groups start
in collection order, so a part can start its longest tests first). The parts run side by side,
so a short part fills the CPUs a long part leaves idle while it builds its inputs; each part's
output is printed when it ends. Every part runs to its end even when another fails; the exit
code is non-zero when any part failed. The parts share one build of obs's spec: the suite makes a
folder for the run, names it in `OBS_SPEC_BUILD` for every part, prints how often
test/spec_build.py built each kind there, fails where one kind was built twice, and removes the
folder at the end. `--shard i/n` runs the i-th of n shards of every part, so CI can spread the
suite over n jobs: each part keeps that shard of its xdist groups, dealt by their committed
weights (keep_shard), and a shard's run
is checked against the tiers' caps but not recorded. It names its host (its CPU count and model) as it starts, and where the parts
took longer than `[tests] target_seconds` or `limit_seconds`, a whole run `[tests] shards` times
each as se's gate judges it (budget), it says so as it ends, naming the numbers it judged by and the
SLOWEST_NAMED slowest tests of the parts' reports (slowest_tests), on GitHub Actions also as a
warning annotation; it does not fail on that (quality.md, Testing boundaries). As it ends it also
names, the same way and without failing, each test far slower than its tier's typical time
(outlying, test/bounds.py's outliers). Each test has its timeout (test/bounds.py); the whole run has a cap,
CAP_SECONDS, at which a part still running is interrupted, so its pytest writes its JUnit report of
the tests it finished, then stopped with every process it started once it ends or
INTERRUPT_GRACE_SECONDS pass; the suite adds the tests it was running to that report, names the
part, those tests and the tests that failed before them, and fails. Arguments are passed on to every
part's pytest, for example `--durations=20`. Each part writes its JUnit XML report as `<part>.xml`
(`core.xml`): where `SE_TEST_REPORTS` names a directory, there, from which se's
`work_tickets.py suite` names the slowest tests, otherwise in the run's folder. Each part's
`conftest.py` names its worker count there as the `workers` testsuite property (record_workers),
by which se divides the part's test time. From each report the suite records each xdist group's
test time as the part's weights (WEIGHTS, record_weights); each part's `conftest.py` deals its
groups heaviest first by them (heaviest_first), and by the committed weights (SHARD_WEIGHTS) where
no record exists.
Beside them it records each passed test's tier and time per run (record_durations), from which
test/bounds.py derives each tier's timeout; a part whose test ran past its tier's cap fails. A run
that did not complete (incomplete) records neither, and the suite names the part and the reason.

A part may depend on a Node package, its `test/browser/package-lock.json` (the core holds none
today); the core's diagram renderers are built into its package by its build (hatch_build.py). An
adapter's browser tests run on Playwright's headless shell (HEADLESS_SHELL), which an adapter's
repository sets up with this command in the core's checkout it tests against. `--setup`, its only argument then, installs the packages, and the shell with
Playwright (BROWSER_INSTALL) where Playwright's browsers folder (PLAYWRIGHT_BROWSERS_PATH, else
Playwright's default) holds none, so a machine that has one downloads nothing; it runs no part; se.toml's `[tests] setup` runs it before the suite, timed apart from the budget.
A package is installed with `npm ci` when its `node_modules` is missing or was installed from
another lockfile: after each install the lockfile's SHA-256 is stored in `node_modules/` as
`.obs-installed-lockfile`, so a warm checkout installs nothing. A failed install names the
lockfile and the command to run by hand. The suite itself installs nothing: where a package is
not installed from its current lockfile, it names the package and the setup command, and no
part runs. A focused run (`uv run pytest` in a part's folder) needs no setup step: each part's
`conftest.py` calls `set_up_focused_run` from `pytest_sessionstart`, which installs, as `--setup`
does, every package not installed from its current lockfile, under a lock shared by the parts.

    uv run python test/suite.py --setup
    uv run python test/suite.py
    uv run python test/suite.py --shard 1/2
    uv run python test/suite.py --measure-weights <run folder>...

`--measure-weights` prints SHARD_WEIGHTS and TIER_WEIGHTS measured from the JUnit reports of the
CI runs it names (measure_weights), to paste over them.
"""
import contextlib
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import warnings
import xml.etree.ElementTree as ElementTree
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
# The suite's parts: the core alone, since every adapter is a component that tests itself in its own
# repository (spec/design_input/architecture.md, Repository layout).
PARTS = [ROOT]
SETUP = "--setup"
# `--measure-weights <run folder>...`: print SHARD_WEIGHTS and TIER_WEIGHTS measured from runs' reports.
MEASURE = "--measure-weights"
SETUP_COMMAND = f"uv run python test/suite.py {SETUP}"
PARALLEL = ["--dist", "loadgroup", "--no-loadscope-reorder"]
REPORTS_VARIABLE = "SE_TEST_REPORTS"
# `--shard i/n`: run only the i-th of n shards of every part (keep_shard), named to the parts here.
SHARD = "--shard"
# Every environment variable of the suite's own starts with this; no test of the suite inherits one
# (test/conftest.py, suite_environment).
VARIABLE_PREFIX = "OBS_SUITE_"
SHARD_VARIABLE = f"{VARIABLE_PREFIX}SHARD"
# Each part's Node test package, where it has one.
NODE_PACKAGES = [part / "test" / "browser" for part in PARTS
                 if (part / "test" / "browser" / "package-lock.json").is_file()]
# A part with a Node test package runs its browser tests, which wait on their pages' frames much of
# their time: it runs this many workers per CPU, rounded up, so the further workers fill that time;
# every other part runs one per CPU (part_command). Two per CPU fill it a little more, but stretch a
# single CPU-bound test past its tier's cap (test/bounds.py) while both parts run.
BROWSER_WORKERS_PER_CPU = 1.5
# The run's cap, in seconds: past any run that ends ([tests] limit_seconds times shards in
# se.toml, budget) and past every test's timeout (test/bounds.py), so a hanging test fails by its
# own timeout first.
CAP_SECONDS = 300
# At the cap, how long a part's pytest has, once interrupted, to end its session (its JUnit report and
# its failures) before the suite stops what is left of it: three times pytest-xdist's own wait for
# its workers to exit (NodeManager.EXIT_TIMEOUT, 10 s).
INTERRUPT_GRACE_SECONDS = 30
# In node_modules: the SHA-256 of the lockfile it was installed from.
INSTALLED_LOCKFILE = ".obs-installed-lockfile"


# The adapters' browser tests' engine (obs quality.md, Testing boundaries): Playwright's
# chromium-headless-shell. Playwright installs it in its browsers folder as
# <revision folder>/<platform folder>/<executable>; the newest revision installed is used.
HEADLESS_SHELL = ("chromium_headless_shell-*", "chrome-headless-shell-*",
                  "chrome-headless-shell.exe" if sys.platform == "win32" else "chrome-headless-shell")
BROWSER_INSTALL = [sys.executable, "-m", "playwright", "install", "chromium-headless-shell"]


class InstallError(Exception):
    """A Node test package could not be installed; the message names its lockfile and the remedy."""


def part_name(part: Path) -> str:
    return part.relative_to(ROOT).as_posix() if part != ROOT else "core"


def part_report(part: Path, environment, run_folder: Path) -> Path:
    """One part's JUnit report: in the directory the environment names, otherwise in the run's folder."""
    folder = Path(environment[REPORTS_VARIABLE]) if environment.get(REPORTS_VARIABLE) else run_folder
    return folder / f"{part_name(part).replace('/', '-')}.xml"


def cpus() -> int:
    """The CPUs this process may use: its affinity where the platform reports one (a pinned or
    shared runner), else the host's count, as pytest-xdist's ``-n auto`` counts them."""
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0))
    return os.cpu_count() or 1


def part_command(part: Path, arguments: list[str], environment, run_folder: Path) -> list[str]:
    """The pytest command of one part, with its workers (BROWSER_WORKERS_PER_CPU), which writes its
    JUnit report (part_report)."""
    browsers = any(package.parents[1] == part for package in NODE_PACKAGES)
    workers = str(math.ceil(BROWSER_WORKERS_PER_CPU * cpus())) if browsers else "auto"
    return [sys.executable, "-m", "pytest", "-q", "-n", workers, *PARALLEL, *arguments,
            f"--junitxml={part_report(part, environment, run_folder)}"]


# Each part's weights, `<part>.json`: each xdist group's test time in seconds in the part's last
# recorded run. Generated, so in data/data_output.
WEIGHTS = ROOT / "data" / "data_output" / "test-weights"


def record_weights(report: Path) -> dict[str, float]:
    """Record each xdist group's test time in a part's JUnit report (a case's name ends in
    ``@<group>``) as that group's weight, over its earlier one; the weights recorded."""
    if not report.is_file():
        return {}
    measured = Counter()
    for case in ElementTree.parse(report).iter("testcase"):
        name = case.get("name", "")
        if "@" in name:
            measured[name.rsplit("@", 1)[1]] += float(case.get("time") or 0)
    record = WEIGHTS / f"{report.stem}.json"
    weights = {**(json.loads(record.read_text(encoding="utf-8")) if record.is_file() else {}),
               **{group: round(seconds, 3) for group, seconds in measured.items()}}
    WEIGHTS.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps(weights, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return weights


def record_durations(report: Path, keep: int) -> dict[str, list]:
    """Append to a part's recorded runs, `<part>.runs.json` beside its weights, each passed test's
    tier (the case's property that test/bounds.py's ``mark`` writes, TIER_PROPERTY) and time in its
    JUnit report, keyed by the case, and keep the last ``keep`` runs; the run recorded, none where
    the part wrote no report. A failed or skipped test is no measurement."""
    import bounds  # Only here: an adapter's conftest.py loads this module without test/ on its path.

    record = WEIGHTS / f"{report.stem}.runs.json"
    if not report.is_file():
        return {}
    runs = json.loads(record.read_text(encoding="utf-8")) if record.is_file() else []
    run = measured_run(report)
    runs = [*runs, run][-keep:]
    WEIGHTS.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps(runs, indent=0, sort_keys=True) + "\n", encoding="utf-8")
    return run


def measured_run(report: Path) -> dict[str, list]:
    """Each passed test's tier and time in a part's JUnit report, keyed by the case; none where
    the part wrote no report."""
    import bounds  # Only here: an adapter's conftest.py loads this module without test/ on its path.

    if not report.is_file():
        return {}
    run = {}
    for case in ElementTree.parse(report).iter("testcase"):
        tier = next((prop.get("value") for prop in case.iter("property")
                     if prop.get("name") == bounds.TIER_PROPERTY), None)
        if tier and not any(case.find(outcome) is not None for outcome in ("failure", "error", "skipped")):
            run[f"{case.get('classname')}::{case.get('name')}"] = [tier, round(float(case.get("time") or 0), 3)]
    return run


# pytest's exit codes of a run that did not complete: interrupted, internal error, usage error.
INCOMPLETE_EXIT_CODES = (2, 3, 4)


def incomplete(returncode: int, report: Path) -> str | None:
    """Why a part's run is no measurement of its tests, so record_durations does not record it:
    it wrote no report, pytest did not complete (INCOMPLETE_EXIT_CODES), a test module failed to
    collect, or it ran no tests; None for a complete run."""
    if not report.is_file():
        return "it wrote no JUnit report"
    if returncode in INCOMPLETE_EXIT_CODES:
        return f"pytest exited with code {returncode}"
    cases = list(ElementTree.parse(report).iter("testcase"))
    if any(error.get("message") == "collection failure" for case in cases for error in case.iter("error")):
        return "a test module failed to collect"
    if not cases:
        return "it ran no tests"
    return None


def recorded_runs() -> list[list[dict[str, list]]]:
    """Each part's recorded runs (record_durations), oldest first."""
    return [json.loads(record.read_text(encoding="utf-8")) for record in sorted(WEIGHTS.glob("*.runs.json"))]


def shard() -> tuple[int, int] | None:
    """The shard the parts run, (i, n), from SHARD_VARIABLE; None where they run every test."""
    named = os.environ.get(SHARD_VARIABLE)
    if not named:
        return None
    index, count = (int(number) for number in named.split("/"))
    return index, count


# Each part's committed xdist-group weights, in seconds, by which keep_shard deals the groups to
# the shards and heaviest_first orders them on a host without a record: a fresh CI runner, always.
# So they are measured on CI, and pasted here from the output of
# `uv run python test/suite.py --measure-weights <run folder>...` (measure_weights), each folder
# holding the JUnit reports of both shards of one `test` workflow run, which CI uploads as the
# artifacts `junit-shard-<i>`. TIER_WEIGHTS, each tier's mean time per test there, weighs a group
# the table lacks; keep_shard warns of one, a nudge to measure again. Measured on runs
# 43587745132 (e941306), 43587606363 and 43587589145 (its landing, the same tree), 43587400285
# and 43587308111 (dd434ab, its work branch), 2026-11-14, on GitHub's 4-CPU ubuntu-latest runners.
# Download each attempt's artifacts before re-running it: a re-run drops them.
SHARD_WEIGHTS = {
    "core": {
        "test/test_diagram_figures.py": 13.78,
        "test/structure/test_public_spec.py": 10.31,
        "test/test_vault.py": 7.98,
        "test/test_parallel_suite.py": 6.86,
        "test/test_equation_figures.py": 6.31,
        "test/test_document_contract.py": 4.58,
        "test/test_hatch_build.py": 4.29,
        "test/test_note_inclusion.py": 3.1,
        "test/structure/test_spec_builds.py": 2.31,
        "test/test_bounds.py": 1.99,
        "test/test_core_input_contracts.py": 1.88,
        "test/test_document_sources.py": 1.27,
        "test/test_pugh_figure.py": 1.24,
        "test/test_cover_metadata.py": 1.08,
        "test/test_vault_file_options.py": 0.96,
        "test/test_core_namespace.py": 0.95,
        "test/test_command_fences.py": 0.93,
        "test/test_figure_descriptor_contract.py": 0.9,
        "test/test_bless.py": 0.87,
        "test/test_property_editor_projection.py": 0.74,
        "test/test_note_reader.py": 0.58,
        "test/test_quantity_units.py": 0.56,
        "test/test_bases_filter_conformance.py": 0.51,
        "test/structure/test_command_fences_stay_in_vault.py": 0.51,
        "test/test_node_ids.py": 0.51,
        "test/test_document_assets.py": 0.5,
        "test/test_expression_vectors.py": 0.45,
        "test/test_capabilities.py": 0.42,
        "test/structure/test_manifest.py": 0.39,
        "test/structure/test_core_spec_names_no_adapter.py": 0.39,
        "test/test_note_records.py": 0.27,
        "test/test_protected_fields_one_owner.py": 0.26,
        "test/test_document_style.py": 0.25,
        "test/test_paragraph_lint.py": 0.21,
        "test/test_project_config.py": 0.2,
        "test/test_spec_build.py": 0.2,
        "test/test_figure_warnings.py": 0.17,
        "test/test_repeated_adapter_options.py": 0.15,
        "test/test_ignored_notes.py": 0.15,
        "test/test_figure_references.py": 0.13,
        "test/structure/test_architecture.py": 0.13,
        "test/test_suite_node_packages.py": 0.1,
        "test/test_inline_round_trip.py": 0.08,
        "test/test_link_labels.py": 0.07,
        "test/test_record_projections.py": 0.06,
        "test/test_obsidian_comments.py": 0.06,
        "test/structure/test_repository.py": 0.04,
        "test/structure/test_input_model.py": 0.04,
        "test/test_producers.py": 0.04,
        "test/structure/test_node_modules.py": 0.03,
        "test/test_validation_once.py": 0.03,
        "test/test_tiers.py": 0.03,
        "test/structure/test_quality.py": 0.02,
        "test/test_attachment_date.py": 0.02,
        "test/test_network_guard.py": 0.01,
        "test/test_diagram_browser.py": 0.01,
        "test/test_adapter_extensions.py": 0.01,
        "test/structure/test_reviewed_copies.py": 0.0,
        "test/structure/test_cover_metadata.py": 0.0,
        "test/structure/test_registers.py": 0.0,
        "test/structure/test_profiles.py": 0.0,
        "test/structure/test_queries.py": 0.0,
        "test/structure/test_product.py": 0.0,
        "test/test_authored_artifact_browser.py": 0.0,
    },
}
TIER_WEIGHTS = {"unit": 0.077, "dom": 0.233, "browser": 1.212, "build": 2.208, "external": 2.208}


def measure_weights(runs: list[Path]) -> str:
    """SHARD_WEIGHTS and TIER_WEIGHTS as source, from the JUnit reports of runs, one folder per run
    holding every shard's ``<part>.xml`` (in subfolders too): each xdist group's test time (a case's
    name ends in ``@<group>``; its time is setup, call and teardown) summed per run and averaged over
    the runs it ran in, and each tier's (TIER_PROPERTY) time per test over all of them. A tier no run
    ran weighs as the most expensive one measured."""
    import bounds  # Only here: an adapter's conftest.py loads this module without test/ on its path.

    parts = {part_name(part).replace("/", "-"): part_name(part) for part in PARTS}
    groups: dict[str, dict[str, list[float]]] = {name: {} for name in parts.values()}
    tiers: dict[str, list[float]] = {}
    for run in runs:
        measured = {name: Counter() for name in parts.values()}
        for report in sorted(run.rglob("*.xml")):
            if report.stem not in parts:
                continue
            for case in ElementTree.parse(report).iter("testcase"):
                name, seconds = case.get("name", ""), float(case.get("time") or 0)
                if "@" in name:
                    measured[parts[report.stem]][name.rsplit("@", 1)[1]] += seconds
                tier = next((prop.get("value") for prop in case.iter("property")
                             if prop.get("name") == bounds.TIER_PROPERTY), None)
                if tier:
                    tiers.setdefault(tier, []).append(seconds)
        for part, times in measured.items():
            for group, seconds in times.items():
                groups[part].setdefault(group, []).append(seconds)
    means = {tier: round(sum(times) / len(times), 3) for tier, times in tiers.items()}
    costliest = max(means, key=list(bounds.TIMEOUTS).index, default=None)
    tier_weights = {tier: means.get(tier, means.get(costliest, 0.0)) for tier in bounds.TIMEOUTS}
    lines = ["SHARD_WEIGHTS = {"]
    for part, measured in groups.items():
        lines.append(f"    {json.dumps(part)}: {{")
        lines += [f"        {json.dumps(group)}: {round(sum(times) / len(times), 2)},"
                  for group, times in sorted(measured.items(), key=lambda item: (-sum(item[1]) / len(item[1]), item[0]))]
        lines.append("    },")
    lines += ["}", f"TIER_WEIGHTS = {json.dumps(tier_weights)}"]
    return "\n".join(lines) + "\n"


def xdist_group(item) -> str:
    """The test's xdist group, which its part's conftest.py named."""
    mark = item.get_closest_marker("xdist_group")
    return mark.args[0] if mark.args else mark.kwargs.get("name")


def groups_of(items) -> dict[str, list]:
    """The tests by their xdist group, in the order they come."""
    groups: dict[str, list] = {}
    for item in items:
        groups.setdefault(xdist_group(item), []).append(item)
    return groups


def deal(weights: dict[str, float], count: int) -> list[set[str]]:
    """Deal the groups, each with its weight in seconds, to ``count`` shards: the heaviest first,
    each onto the shard with the least weight so far, ties to the lower-numbered shard, and groups of
    equal weight by name. The same weights always give the same shards, and each group lands in
    exactly one."""
    loads, shards = [0.0] * count, [set() for _ in range(count)]
    for name in sorted(weights, key=lambda name: (-weights[name], name)):
        lightest = min(range(count), key=lambda number: (loads[number], number))
        loads[lightest] += weights[name]
        shards[lightest].add(name)
    return shards


def shard_weights(part: str, groups: dict[str, list], bounds) -> dict[str, float]:
    """Each of a part's xdist groups' weight for the deal: its committed measurement (SHARD_WEIGHTS),
    else the sum of its tests' tier weights (TIER_WEIGHTS, by test/bounds.py's ``tier``)."""
    committed = SHARD_WEIGHTS.get(part, {})
    return {name: committed.get(name, sum(TIER_WEIGHTS[bounds.tier(item)] for item in items))
            for name, items in groups.items()}


def warn_unweighed(part: str, groups) -> None:
    """Warn, without failing, of each of a part's groups that SHARD_WEIGHTS lacks: it weighs its
    tests' TIER_WEIGHTS until the weights are measured again."""
    lacking = sorted(set(groups) - set(SHARD_WEIGHTS.get(part, {})))
    if lacking:
        warnings.warn(f"test/suite.py: {part}: SHARD_WEIGHTS lacks the groups {', '.join(lacking)}; they weigh "
                      "their tests' TIER_WEIGHTS. Remedy: measure the weights again as SHARD_WEIGHTS's comment "
                      f"names (`{MEASURE}`) and paste its output.", stacklevel=2)


def keep_shard(config, items, bounds) -> None:
    """From a part's ``pytest_collection_modifyitems``, after it named each test's xdist group: on a
    shard, keep only its groups and deselect the rest. The groups are dealt by their committed
    weights (shard_weights, deal), not by what this host recorded: every shard's job computes the
    deal for itself, so all of them must read the same input, and a fresh CI runner has no record.
    ``bounds`` is test/bounds.py as the part's conftest.py loaded it."""
    named = shard()
    # A pytest a test starts inherits the variable; only a part's own run is sharded.
    if named is None or config.rootpath.resolve() not in {part.resolve() for part in PARTS}:
        return
    index, count = named
    part, groups = part_name(config.rootpath.resolve()), groups_of(items)
    warn_unweighed(part, groups)
    ours = deal(shard_weights(part, groups, bounds), count)[index - 1]
    deselected = [item for item in items if xdist_group(item) not in ours]
    if deselected:
        config.hook.pytest_deselected(items=deselected)
    items[:] = [item for item in items if xdist_group(item) in ours]


def heaviest_first(part: Path, items, bounds) -> None:
    """From a part's ``pytest_collection_modifyitems``, after it named each test's xdist group:
    order the tests by their group's weight, heaviest first, since xdist deals the groups in the
    order the tests come. The weight is the one this host recorded, where it recorded the part, and
    a group without one comes first; on a host without a record of the part, a fresh CI runner
    among them, it is the committed one (shard_weights). ``bounds`` is test/bounds.py as the part's
    conftest.py loaded it."""
    groups = groups_of(items)
    record = WEIGHTS / f"{part_name(part.resolve()).replace('/', '-')}.json"
    if record.is_file():
        recorded = json.loads(record.read_text(encoding="utf-8"))
        weights = {name: recorded.get(name, math.inf) for name in groups}
    else:
        weights = shard_weights(part_name(part.resolve()), groups, bounds)
    items.sort(key=lambda item: -weights[xdist_group(item)])


def lockfile_hash(package: Path) -> str:
    return hashlib.sha256((package / "package-lock.json").read_bytes()).hexdigest()


def is_installed(package: Path) -> bool:
    """Whether the package's node_modules was installed from its current lockfile."""
    marker = package / "node_modules" / INSTALLED_LOCKFILE
    return marker.is_file() and marker.read_text(encoding="utf-8").strip() == lockfile_hash(package)


def install_node_packages(packages: list[Path], run=subprocess.run) -> list[Path]:
    """Run `npm ci` for each package not installed from its current lockfile; the packages installed."""
    stale = [package for package in packages if not is_installed(package)]
    for package in stale:
        remedy = (f"Lockfile {package / 'package-lock.json'}: install it by hand with "
                  f"`npm --prefix {package} ci` and rerun the suite.")
        npm = shutil.which("npm")
        if npm is None:
            raise InstallError(f"test/suite.py: npm is not on PATH; install Node.js. {remedy}")
        result = run([npm, "ci"], cwd=package, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                     text=True, encoding="utf-8", errors="replace")
        if result.returncode:
            raise InstallError(f"test/suite.py: npm ci failed (exit code {result.returncode}). {remedy}\n"
                               f"{result.stdout}")
        (package / "node_modules" / INSTALLED_LOCKFILE).write_text(lockfile_hash(package), encoding="utf-8")
    return stale


# The JUnit testsuite property that holds a part's xdist worker count, which se's work_tickets.py
# suite divides the part's test time by.
WORKERS_PROPERTY = "workers"


def playwright_browsers(environment=os.environ) -> Path:
    """Playwright's browsers folder: PLAYWRIGHT_BROWSERS_PATH, else Playwright's default for this system."""
    if environment.get("PLAYWRIGHT_BROWSERS_PATH"):
        return Path(environment["PLAYWRIGHT_BROWSERS_PATH"])
    if sys.platform == "win32":
        return Path(environment["LOCALAPPDATA"]) / "ms-playwright"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return Path(environment.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "ms-playwright"


def headless_shell(browsers: Path) -> str | None:
    """The HEADLESS_SHELL executable of the newest revision installed in ``browsers``, or None."""
    revision, platform, executable = HEADLESS_SHELL
    found = sorted((int(re.sub(r"\D", "", folder.name) or 0), path)
                   for folder in browsers.glob(revision) for path in folder.glob(f"{platform}/{executable}"))
    return str(found[-1][1]) if found else None


def install_browser(browsers: Path, run=subprocess.run) -> bool:
    """Install HEADLESS_SHELL with Playwright where ``browsers`` holds none; whether it installed."""
    if headless_shell(browsers) is not None:
        return False
    result = run(BROWSER_INSTALL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode != 0 or headless_shell(browsers) is None:
        raise InstallError(f"test/suite.py: `{' '.join(BROWSER_INSTALL)}` did not install HEADLESS_SHELL in "
                           f"{browsers} (exit code {result.returncode}). Run it by hand and rerun the setup.\n"
                           f"{result.stdout}")
    return True


def record_workers(config) -> int | None:
    """From a part's ``pytest_sessionstart``: write the part's worker count, its xdist workers or 1
    without them, as WORKERS_PROPERTY of the JUnit report the run writes; the count written. An xdist
    worker leaves this to its controller, and a run without a report writes nothing."""
    from _pytest.junitxml import xml_key

    report = config.stash.get(xml_key, None)
    if hasattr(config, "workerinput") or report is None:
        return None
    distributed = config.getoption("dist", "no") != "no"
    workers = max(1, len(config.getoption("tx", None) or [])) if distributed else 1
    report.add_global_property(WORKERS_PROPERTY, workers)
    return workers


def set_up_focused_run(config, packages: list[Path] | None = None, run=None) -> list[Path]:
    """From a part's ``pytest_sessionstart``: install the Node test packages not installed from their
    current lockfiles; the packages installed. An xdist worker leaves this to its controller, and a
    failed install stops the run, naming its lockfile and the remedy."""
    import pytest
    from filelock import FileLock

    if hasattr(config, "workerinput"):
        return []
    lock = Path(tempfile.gettempdir()) / f"obs-node-setup-{hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]}.lock"
    try:
        with FileLock(lock):
            installed = install_node_packages(NODE_PACKAGES if packages is None else packages,
                                              run=run or subprocess.run)
    except InstallError as error:
        pytest.exit(str(error), returncode=1)
    reporter = getattr(config, "pluginmanager", None) and config.pluginmanager.get_plugin("terminalreporter")
    if installed and reporter:
        reporter.write_line("test/suite.py: installed Node test packages "
                            f"{', '.join(package.relative_to(ROOT).as_posix() for package in installed)} "
                            "for this run, from their lockfiles.")
    return installed


def run_part(part: Path, arguments: list[str], run_folder: Path) -> tuple[int, str]:
    """Run one part's pytest; its exit code and its output, headed by its command. A part still
    running at the cap (CAP_SECONDS) is interrupted, so its pytest ends its session and writes its
    report, then stopped (interrupt_and_stop); its report gets the tests it was running
    (capped_report), and its output ends naming them and its failures (cap_line).
    A part whose recorded test ran past its tier's cap (test/bounds.py, over_cap) fails, naming it."""
    import bounds  # Only here: an adapter's conftest.py loads this module without test/ on its path.

    command = part_command(part, arguments, os.environ, run_folder)
    report = part_report(part, os.environ, run_folder)
    started = time.time()
    process = subprocess.Popen(command, cwd=part, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", start_new_session=os.name != "nt")
    head = f"== {part_name(part)}: {' '.join(command[1:])} in {part}\n"
    try:
        output, _ = process.communicate(timeout=CAP_SECONDS)
    except subprocess.TimeoutExpired:
        running = bounds.running_tests(run_folder, part)
        output = interrupt_and_stop(process)
        # A report older than the part is an earlier run's: the reports' folder can outlive a run.
        written = (report.read_text(encoding="utf-8")
                   if report.is_file() and report.stat().st_mtime >= started else None)
        capped = capped_report(written, running, CAP_SECONDS)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(capped.xml, encoding="utf-8")
        return 1, head + output + cap_line(part_name(part), part, running, report, capped, CAP_SECONDS)
    unrecorded = incomplete(process.returncode, report)
    if shard() is None and unrecorded is None:
        record_weights(report)
        run = record_durations(report, keep=bounds.RUNS)
    else:  # A shard's run holds part of the part's tests: recorded, it would lower the derived bounds.
        run = measured_run(report)
    if shard() is None and unrecorded is not None:
        output += f"test/suite.py: {part_name(part)}: this run is not recorded: {unrecorded}.\n"
    capped = bounds.over_cap(run, bounds.COMMITTED, bounds.CAP_FACTOR)
    # A shard can hold no test of a part: pytest's "no tests ran" is no failure then.
    code = 0 if process.returncode == 5 and shard() is not None else process.returncode
    return (1 if capped else code), head + output + "".join(f"{message}\n" for message in capped)


def interrupt_and_stop(process: subprocess.Popen) -> str:
    """At the cap: interrupt the part's pytest alone (its controller, not its process group), as
    Ctrl-C does, so it ends its session, writing its JUnit report and its failures; wait for it up to
    INTERRUPT_GRACE_SECONDS, reading its output meanwhile, so an end of session past the pipe's
    buffer is not lost; then stop what is left (stop). On Windows, where no interrupt reaches one
    process alone, it stops it at once. Its output."""
    if os.name != "nt":
        import signal

        process.send_signal(signal.SIGINT)
        with contextlib.suppress(subprocess.TimeoutExpired):  # communicate keeps what it read.
            process.communicate(timeout=INTERRUPT_GRACE_SECONDS)
    stop(process)
    output, _ = process.communicate()
    return output


def stop(process: subprocess.Popen) -> None:
    """Stop the process and every process it started: its xdist workers, their browsers and drivers;
    a process group that has already ended is passed over."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
    else:
        import signal

        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)


def case_address(nodeid: str) -> tuple[str, str]:
    """The classname and name pytest's junitxml gives the test of this node id
    (_pytest.junitxml.mangle_test_address): the classname is the node id's parts before its last
    `::`, joined with `.`, the file's `/` as `.` and without `.py`; the name is its last part."""
    path, bracket, parameters = nodeid.partition("[")
    names = path.split("::")
    names[0] = re.sub(r"\.py$", "", names[0].replace("/", "."))
    names[-1] += bracket + parameters
    return ".".join(names[:-1]), names[-1]


class CappedReport(NamedTuple):
    """A capped part's JUnit report (capped_report): its XML, how many tests it finished (None where
    its pytest wrote no report in this run) and those of them that failed, as ``<classname>::<name>``."""
    xml: str
    finished: int | None
    failed: list[str]


def capped_message(cap: int) -> str:
    return f"stopped at the suite's cap of {cap} s (CAP_SECONDS)"


def capped_report(written: str | None, running: list[str], cap: int) -> CappedReport:
    """Complete a capped part's JUnit report: the one its pytest wrote in this run (``written``),
    without the case without a name it leaves for the test it was interrupted in, every other case as
    it wrote it, or, where it wrote none, a report of one testsuite; and one case per running test (a
    node id), holding an error that says the cap stopped it, its testsuite's ``tests`` and ``errors``
    grown by their count."""
    if written is None:
        root = ElementTree.Element("testsuites")
        ElementTree.SubElement(root, "testsuite", {"name": "pytest", "errors": "0", "failures": "0",
                                                   "skipped": "0", "tests": "0"})
    else:
        root = ElementTree.fromstring(written)
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    if not suites:
        suites = [ElementTree.SubElement(root, "testsuite", {"name": "pytest", "errors": "0", "failures": "0",
                                                             "skipped": "0", "tests": "0"})]
    for testsuite in suites:
        for case in [case for case in testsuite.findall("testcase") if not case.get("name")]:
            testsuite.remove(case)
    finished = [case for testsuite in suites for case in testsuite.findall("testcase")]
    failed = [f"{case.get('classname', '')}::{case.get('name')}" for case in finished
              if case.find("failure") is not None or case.find("error") is not None]
    last = suites[-1]
    for nodeid in running:
        classname, name = case_address(nodeid)
        case = ElementTree.SubElement(last, "testcase", {"classname": classname, "name": name})
        ElementTree.SubElement(case, "error", {"message": capped_message(cap)})
    for count in ("tests", "errors"):
        last.set(count, str(int(last.get(count) or 0) + len(running)))
    xml = '<?xml version="1.0" encoding="utf-8"?>' + ElementTree.tostring(root, encoding="unicode")
    return CappedReport(xml, None if written is None else len(finished), failed)


def cap_line(name: str, part: Path, running: list[str], report: Path, capped: CappedReport, cap: int) -> str:
    """The lines that end a capped part's output: the part, the tests it was running, what its report
    (capped_report) holds and which of the finished failed, and the remedy."""
    tests = ", ".join(running) or "no test (collecting, or ending its session)"
    line = (f"test/suite.py: {name} reached the suite's cap of {cap} s (CAP_SECONDS) and was stopped while "
            f"running {tests}.")
    if capped.finished is None:
        line += (f" It wrote no report of the tests it finished; its report {report} holds the "
                 f"{len(running)} it was running.\n")
    else:
        line += (f" Its report {report} holds the {capped.finished} tests it finished and the {len(running)} it "
                 "was running; ")
        line += (f"{len(capped.failed)} of the finished failed:\n" + "".join(f"  {test}\n" for test in capped.failed)
                 if capped.failed else "none of the finished failed.\n")
    return line + (f"Remedy: run that test alone in {part} with `uv run pytest <test>` and find what it "
                   "waits for.\n")


def setup(arguments: list[str], clock) -> int:
    """Install the Node test packages not installed from their current lockfiles, and the browser
    tests' engine where Playwright's browsers folder holds none."""
    if arguments != [SETUP]:
        print(f"test/suite.py: {SETUP} takes no other arguments; run `{SETUP_COMMAND}`.", file=sys.stderr)
        return 2
    started = clock()
    try:
        installed = install_node_packages(NODE_PACKAGES)
        browsers = playwright_browsers()
        browser_installed = install_browser(browsers)
    except InstallError as error:
        print(error, file=sys.stderr)
        return 1
    packages = ", ".join(package.relative_to(ROOT).as_posix() for package in installed or NODE_PACKAGES)
    if installed:
        print(f"test/suite.py: installed Node test packages {packages} in {clock() - started:.1f} s.")
    elif NODE_PACKAGES:
        print(f"test/suite.py: Node test packages {packages} are installed from their lockfiles.")
    else:
        print("test/suite.py: no part holds a Node test package.")
    state = "installed" if browser_installed else "is installed"
    print(f"test/suite.py: the browser tests' engine (HEADLESS_SHELL) {state} in {browsers}.")
    return 0


def tests_settings() -> dict:
    """se.toml's `[tests]`, which owns the suite's time budget."""
    import tomllib

    return tomllib.loads((ROOT / "se.toml").read_text(encoding="utf-8"))["tests"]


class Budget(NamedTuple):
    """The target and the limit a run is judged against, in seconds, and, where they are scaled by
    the shards, their timing as se's gate prints it; None where they are one shard's."""

    target: float
    limit: float
    timing: str | None


def budget(tests: dict, sharded: bool) -> Budget:
    """The budget of a run from se.toml's `[tests]` ``tests``. Its `target_seconds` and
    `limit_seconds` are each shard's: a shard's run (``sharded``) is judged against them, and a
    whole run, as se's gate judges it, against `shards` times each (default 1)."""
    shards = 1 if sharded else tests.get("shards", 1)
    target, limit = tests["target_seconds"] * shards, tests["limit_seconds"] * shards
    timing = (f"target {target:g} s, limit {limit:g} s, {shards} shards of {tests['limit_seconds']:g} s"
              if shards > 1 else None)
    return Budget(target, limit, timing)


# How many of its slowest tests the suite names when its parts took longer than the target.
SLOWEST_NAMED = 10


def slowest_tests(reports: list[Path], count: int = SLOWEST_NAMED) -> list[str]:
    """The ``count`` slowest tests of the parts' JUnit reports, slowest first, each as
    ``<seconds> s <part> <test>``, the part named by its report (part_report)."""
    cases = []
    for report in reports:
        if not report.is_file():
            continue
        for case in ElementTree.parse(report).iter("testcase"):
            test = f"{case.get('classname', '')}::{case.get('name', '')}"
            cases.append((float(case.get("time") or 0), report.stem, test))
    cases.sort(key=lambda case: -case[0])
    return [f"{seconds:.2f} s {part} {test}" for seconds, part, test in cases[:count]]


def outlying(reports: list[Path], environment) -> list[str]:
    """test/bounds.py's warnings (outliers) of the tests of the parts' JUnit reports slower than
    OUTLIER_FACTOR times their tier's typical time, the tiers taken over every part: each on a line
    of its own, and on GitHub Actions also as a warning annotation. The suite does not fail on them."""
    import bounds  # Only here: an adapter's conftest.py loads this module without test/ on its path.

    run = {f"{report.stem} {test}": timed for report in reports for test, timed in measured_run(report).items()}
    lines = bounds.outliers(run, bounds.OUTLIER_FACTOR)
    annotations = [f"::warning title=Test far slower than its tier::{line}" for line in lines]
    return [*lines, *(annotations if environment.get("GITHUB_ACTIONS") == "true" else [])]


def host() -> str:
    """The CPUs this run has, and their model where the platform names it."""
    import platform

    model = platform.processor()
    with contextlib.suppress(OSError):
        model = next((line.split(":", 1)[1].strip() for line in open("/proc/cpuinfo", encoding="utf-8")
                      if line.startswith("model name")), model)
    return f"{os.cpu_count()} CPUs" + (f" ({model})" if model else "")


def overrun(seconds: float, judged: Budget, environment, slowest: list[str]) -> list[str]:
    """The lines that say the parts took longer than the budget's target or limit, naming the slowest
    tests: one, each slowest test on a line of its own, and on GitHub Actions also the warning
    annotation. The suite does not fail on it: CI runners differ in speed (quality.md, Testing
    boundaries)."""
    if seconds <= judged.target:
        return []
    over, bound = ("limit", judged.limit) if seconds > judged.limit else ("target", judged.target)
    owner = (f"[tests] {over}_seconds in se.toml" if judged.timing is None
             else f"[tests] {over}_seconds times shards in se.toml: {judged.timing}")
    line = f"test/suite.py: the parts took {seconds:.1f} s, over the suite's {bound:g} s {over} ({owner})"
    if slowest:
        line += f"; its {len(slowest)} slowest tests:"
    listed = [f"  {test}" for test in slowest]
    annotation = (f"::warning title=Suite over its time {over}::{line[:-1] + ': ' if slowest else line}"
                  + "; ".join(slowest))
    return [line, *listed, *([annotation] if environment.get("GITHUB_ACTIONS") == "true" else [])]


def main(arguments: list[str], clock=time.monotonic) -> int:
    if SETUP in arguments:
        return setup(arguments, clock)
    if MEASURE in arguments:
        runs = [Path(folder) for folder in arguments[arguments.index(MEASURE) + 1:]]
        if not runs or not all(run.is_dir() for run in runs):
            print(f"test/suite.py: {MEASURE} names no run folder. Remedy: name one folder per CI run, each "
                  "holding its shards' JUnit reports (the artifacts junit-shard-<i>).", file=sys.stderr)
            return 2
        print(measure_weights(runs), end="")
        return 0
    named = None
    if SHARD in arguments:
        at = arguments.index(SHARD)
        named = arguments[at + 1] if at + 1 < len(arguments) else ""
        arguments = arguments[:at] + arguments[at + 2:]
        match = re.fullmatch(r"([1-9][0-9]*)/([1-9][0-9]*)", named)
        if not match or int(match[1]) > int(match[2]):
            print(f"test/suite.py: {SHARD} {named} names no shard. Remedy: name the i-th of n shards as "
                  f"`{SHARD} i/n`, 1 <= i <= n.", file=sys.stderr)
            return 2
    missing = [package for package in NODE_PACKAGES if not is_installed(package)]
    if missing:
        lockfiles = ", ".join(str(package / "package-lock.json") for package in missing)
        print(f"test/suite.py: Node test packages are not installed from their lockfiles {lockfiles}; "
              f"no part ran. Run the setup first: `{SETUP_COMMAND}` ([tests] setup in se.toml).",
              file=sys.stderr)
        return 1
    started = clock()
    names = [part_name(part) for part in PARTS]
    print(f"test/suite.py: host: {host()}.", flush=True)
    if named:
        index, count = named.split("/")
        print(f"test/suite.py: shard {index} of {count}: each part runs that shard of its groups "
              "(keep_shard).", flush=True)
    print(f"test/suite.py: running {', '.join(names)} side by side; each part's output follows "
          "when it ends.", flush=True)
    import spec_build  # Only here: an adapter's conftest.py loads this module without test/ on its path.

    failed = []
    # A test that runs main in a worker of the complete suite gets its own run's folder back.
    found = os.environ.get(spec_build.RUN_FOLDER)
    with tempfile.TemporaryDirectory(prefix="obs-spec-build-") as shared:
        os.environ[spec_build.RUN_FOLDER] = shared  # Each part, and each of its workers, inherits it.
        if named:
            os.environ[SHARD_VARIABLE] = named
        try:
            with ThreadPoolExecutor(len(PARTS)) as pool:
                running = {pool.submit(run_part, part, arguments, Path(shared)): part for part in PARTS}
                for finished in as_completed(running):
                    code, output = finished.result()
                    print(output, end="" if output.endswith("\n") else "\n", flush=True)
                    if code:
                        failed.append(part_name(running[finished]))
        finally:
            if found is None:
                del os.environ[spec_build.RUN_FOLDER]
            else:
                os.environ[spec_build.RUN_FOLDER] = found
            os.environ.pop(SHARD_VARIABLE, None)
        builds = spec_build.counts(Path(shared))
        took = clock() - started
        reports = [part_report(part, os.environ, Path(shared)) for part in PARTS]
        slowest = slowest_tests(reports)
        unusual = outlying(reports, os.environ)
    print(f"test/suite.py: parts took {took:.1f} s.")
    for line in [*overrun(took, budget(tests_settings(), sharded=bool(named)), os.environ, slowest), *unusual]:
        print(line)
    built = ", ".join(f"{kind} {builds[kind]}" for kind in spec_build.BUILDS)
    print(f"test/suite.py: obs's spec was built this run (test/spec_build.py): {built}.")
    if any(count > 1 for count in builds.values()):
        print(f"test/suite.py: obs's spec was built more than once this run ({built}); test/spec_build.py "
              "builds each kind once per run. Remedy: find the build whose inputs changed during the run "
              "(test/spec_build.py, INPUTS) and keep it from writing outside the vault's design_output; "
              f"where {spec_build.COUNTER} in the run's folder names a build outside it, find the test that "
              f"removed {spec_build.RUN_FOLDER} from that process.",
              file=sys.stderr)
        return 1
    if failed:
        failed.sort(key=names.index)
        print(f"test/suite.py: failed parts: {', '.join(failed)}. Remedy: rerun `uv run pytest` in each "
              "failed part's folder and fix what it reports.", file=sys.stderr)
        return 1
    print(f"test/suite.py: all {len(PARTS)} parts passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
