"""Run the complete suite: the core's and every integrated adapter's, each in its own pytest.

Reader: whoever runs or changes the complete suite, and CI.

It runs every test of the core and of every adapter except the external tier's, which needs
hand-supplied inputs (test/tiers.py). Its time budget is `[tests]` in `se.toml`.

Each part tests only itself, with its own `pyproject.toml` settings and `conftest.py`, so each
runs as its own pytest process from its own folder, its tests spread over one worker process
per CPU (pytest-xdist, `-n auto --dist loadgroup`: a module's tests share a worker; groups start
in collection order, so a part can start its longest tests first). The parts run side by side,
so a short part fills the CPUs a long part leaves idle while it builds its inputs; each part's
output is printed when it ends. Every part runs to its end even when another fails; the exit
code is non-zero when any part failed. The parts share one build of obs's spec: the suite makes a
folder for the run, names it in `OBS_SPEC_BUILD` for every part, prints how often
test/spec_build.py built each kind there, fails where one kind was built twice, and removes the
folder at the end. `--shard i/n` runs the i-th of n shards of every part, so CI can spread the
suite over n jobs: each part keeps that shard of its xdist groups (keep_shard), and a shard's run
is checked against the tiers' caps but not recorded. It names its host (its CPU count and model) as it starts, and where the parts
took longer than `[tests] limit_seconds` it says so as it ends, on GitHub Actions also as a warning
annotation; it does not fail on that (quality.md, Testing boundaries). Each test has its timeout (test/bounds.py); the whole run has a cap,
CAP_SECONDS, at which a part still running is stopped, with every process it started, and the
suite names the part and the tests it was running and fails. Arguments are passed on to every
part's pytest, for example `--durations=20`. Each part writes its JUnit XML report as `<part>.xml`
(`core.xml`, `adapters-html.xml`): where `SE_TEST_REPORTS` names a directory, there, from which se's
`work_tickets.py suite` names the slowest tests, otherwise in the run's folder. Each part's
`conftest.py` names its worker count there as the `workers` testsuite property (record_workers),
by which se divides the part's test time. From each report the suite records each xdist group's
test time as the part's weights (WEIGHTS, record_weights); each part's `conftest.py` deals its
groups heaviest first by them (heaviest_first), and keeps its own order where no record exists.
Beside them it records each passed test's tier and time per run (record_durations), from which
test/bounds.py derives each tier's timeout; a part whose test ran past its tier's cap fails. A run
that did not complete (incomplete) records neither, and the suite names the part and the reason.

The parts depend on Node packages: each part's `test/browser/package-lock.json`
(today `adapters/html/test/browser` alone); the core's diagram renderers and the html
adapter's maths library are built into their packages by each package's build (hatch_build.py,
adapters/html/hatch_build.py). The adapters' browser tests run on Playwright's headless shell
(HEADLESS_SHELL). `--setup`, its only argument then, installs the packages, and the shell with
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
import xml.etree.ElementTree as ElementTree
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The core, then each integrated adapter folder under adapters/.
PARTS = [ROOT, *sorted(path.parent for path in (ROOT / "adapters").glob("*/pyproject.toml"))]
SETUP = "--setup"
SETUP_COMMAND = f"uv run python test/suite.py {SETUP}"
PARALLEL = ["-n", "auto", "--dist", "loadgroup", "--no-loadscope-reorder"]
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
# The run's cap, in seconds: past any run that ends ([tests] limit_seconds in se.toml) and past
# every test's timeout (test/bounds.py), so a hanging test fails by its own timeout first.
CAP_SECONDS = 300
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


def part_command(part: Path, arguments: list[str], environment, run_folder: Path) -> list[str]:
    """The pytest command of one part, which writes its JUnit report (part_report)."""
    return [sys.executable, "-m", "pytest", "-q", *PARALLEL, *arguments,
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


def keep_shard(config, items, bounds) -> None:
    """From a part's ``pytest_collection_modifyitems``, after it named each test's xdist group: on a
    shard, keep only its groups and deselect the rest. The groups are dealt to the n shards in
    turn and back again (1, ..., n, n, ..., 1), the most expensive tier first (test/tiers.py's
    order, as test/bounds.py's ``tier`` names it) and the group with more tests first within a
    tier, then by name: the same split on every host, with or without recorded weights, which a
    fresh CI runner has none of. ``bounds`` is test/bounds.py as the part's conftest.py loaded it."""
    named = shard()
    # A pytest a test starts inherits the variable; only a part's own run is sharded.
    if named is None or config.rootpath.resolve() not in {part.resolve() for part in PARTS}:
        return
    index, count = named

    def group(item) -> str:
        mark = item.get_closest_marker("xdist_group")
        return mark.args[0] if mark.args else mark.kwargs.get("name")

    groups: dict[str, list] = {}
    for item in items:
        groups.setdefault(group(item), []).append(item)
    order = list(bounds.TIMEOUTS)
    ranked = sorted(groups, key=lambda name: (-max(order.index(bounds.tier(item)) for item in groups[name]),
                                              -len(groups[name]), name))
    turn = [*range(count), *reversed(range(count))]
    ours = {name for number, name in enumerate(ranked) if turn[number % len(turn)] == index - 1}
    deselected = [item for item in items if group(item) not in ours]
    if deselected:
        config.hook.pytest_deselected(items=deselected)
    items[:] = [item for item in items if group(item) in ours]


def heaviest_first(part: Path, items) -> None:
    """From a part's ``pytest_collection_modifyitems``, after it named each test's xdist group:
    order the tests by their group's recorded weight, heaviest first, since xdist deals the groups
    in the order the tests come. A group without a weight comes first, in its order; without a
    record of the part the order stays as it is."""
    record = WEIGHTS / f"{part_name(part.resolve()).replace('/', '-')}.json"
    if not record.is_file():
        return
    weights = json.loads(record.read_text(encoding="utf-8"))

    def weight(item) -> float:
        mark = item.get_closest_marker("xdist_group")
        group = mark.args[0] if mark.args else mark.kwargs.get("name")
        return weights.get(group, math.inf)

    items.sort(key=lambda item: -weight(item))


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
    running at the cap (CAP_SECONDS) is stopped, and its output ends naming the tests it ran then.
    A part whose recorded test ran past its tier's cap (test/bounds.py, over_cap) fails, naming it."""
    import bounds  # Only here: an adapter's conftest.py loads this module without test/ on its path.

    command = part_command(part, arguments, os.environ, run_folder)
    process = subprocess.Popen(command, cwd=part, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", start_new_session=os.name != "nt")
    head = f"== {part_name(part)}: {' '.join(command[1:])} in {part}\n"
    try:
        output, _ = process.communicate(timeout=CAP_SECONDS)
    except subprocess.TimeoutExpired:
        running = ", ".join(bounds.running_tests(run_folder, part)) or "no test (collecting, or ending its session)"
        stop(process)
        output, _ = process.communicate()
        return 1, (f"{head}{output}test/suite.py: {part_name(part)} reached the suite's cap of {CAP_SECONDS} s "
                   f"(CAP_SECONDS) and was stopped while running {running}. Remedy: run that test alone in "
                   f"{part} with `uv run pytest <test>` and find what it waits for.\n")
    report = part_report(part, os.environ, run_folder)
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


def stop(process: subprocess.Popen) -> None:
    """Stop the process and every process it started: its xdist workers, their browsers and drivers."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
    else:
        import signal

        os.killpg(process.pid, signal.SIGKILL)


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
    else:
        print(f"test/suite.py: Node test packages {packages} are installed from their lockfiles.")
    state = "installed" if browser_installed else "is installed"
    print(f"test/suite.py: the browser tests' engine (HEADLESS_SHELL) {state} in {browsers}.")
    return 0


def limit_seconds() -> float:
    """The suite's time limit, `[tests] limit_seconds` in se.toml, which owns it."""
    import tomllib

    return tomllib.loads((ROOT / "se.toml").read_text(encoding="utf-8"))["tests"]["limit_seconds"]


def host() -> str:
    """The CPUs this run has, and their model where the platform names it."""
    import platform

    model = platform.processor()
    with contextlib.suppress(OSError):
        model = next((line.split(":", 1)[1].strip() for line in open("/proc/cpuinfo", encoding="utf-8")
                      if line.startswith("model name")), model)
    return f"{os.cpu_count()} CPUs" + (f" ({model})" if model else "")


def overrun(seconds: float, limit: float, environment) -> list[str]:
    """The lines that say the parts took longer than the limit: one, and on GitHub Actions also
    its warning annotation. The suite does not fail on it: CI runners differ in speed (quality.md,
    Testing boundaries)."""
    if seconds <= limit:
        return []
    line = (f"test/suite.py: the parts took {seconds:.1f} s, over the suite's {limit:g} s limit "
            "([tests] limit_seconds in se.toml)")
    annotation = f"::warning title=Suite over its time limit::{line}"
    return [line, annotation] if environment.get("GITHUB_ACTIONS") == "true" else [line]


def main(arguments: list[str], clock=time.monotonic) -> int:
    if SETUP in arguments:
        return setup(arguments, clock)
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
            del os.environ[spec_build.RUN_FOLDER]
            os.environ.pop(SHARD_VARIABLE, None)
        builds = spec_build.counts(Path(shared))
    took = clock() - started
    print(f"test/suite.py: parts took {took:.1f} s.")
    for line in overrun(took, limit_seconds(), os.environ):
        print(line)
    built = ", ".join(f"{kind} {builds[kind]}" for kind in spec_build.BUILDS)
    print(f"test/suite.py: obs's spec was built this run (test/spec_build.py): {built}.")
    if any(count > 1 for count in builds.values()):
        print(f"test/suite.py: obs's spec was built more than once this run ({built}); test/spec_build.py "
              "builds each kind once per run. Remedy: find the build whose inputs changed during the run "
              "(test/spec_build.py, INPUTS) and keep it from writing outside the vault's design_output.",
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
