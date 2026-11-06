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
folder at the end. Each test has its timeout (test/bounds.py); the whole run has a cap,
CAP_SECONDS, at which a part still running is stopped, with every process it started, and the
suite names the part and the tests it was running and fails. Arguments are passed on to every
part's pytest, for example `--durations=20`. Where `SE_TEST_REPORTS` names a directory, each part writes its JUnit
XML report there as `<part>.xml` (`core.xml`, `adapters-html.xml`), from which se's
`work_tickets.py suite` names the slowest tests; each part's `conftest.py` names its worker
count there as the `workers` testsuite property (record_workers), by which se divides the part's
test time.

The parts depend on Node packages: each part's `test/browser/package-lock.json`
(today `adapters/html/test/browser` alone); the core's diagram renderers and the html
adapter's maths library are built into their packages by each package's build (hatch_build.py,
adapters/html/hatch_build.py). `--setup`, its only argument then, installs them
and runs no part; se.toml's `[tests] setup` runs it before the suite, timed apart from the budget.
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
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The core, then each integrated adapter folder under adapters/.
PARTS = [ROOT, *sorted(path.parent for path in (ROOT / "adapters").glob("*/pyproject.toml"))]
SETUP = "--setup"
SETUP_COMMAND = f"uv run python test/suite.py {SETUP}"
PARALLEL = ["-n", "auto", "--dist", "loadgroup", "--no-loadscope-reorder"]
REPORTS_VARIABLE = "SE_TEST_REPORTS"
# Each part's Node test package, where it has one.
NODE_PACKAGES = [part / "test" / "browser" for part in PARTS
                 if (part / "test" / "browser" / "package-lock.json").is_file()]
# The run's cap, in seconds: past any run that ends ([tests] limit_seconds in se.toml) and past
# every test's timeout (test/bounds.py), so a hanging test fails by its own timeout first.
CAP_SECONDS = 300
# In node_modules: the SHA-256 of the lockfile it was installed from.
INSTALLED_LOCKFILE = ".obs-installed-lockfile"


class InstallError(Exception):
    """A Node test package could not be installed; the message names its lockfile and the remedy."""


def part_name(part: Path) -> str:
    return part.relative_to(ROOT).as_posix() if part != ROOT else "core"


def part_command(part: Path, arguments: list[str], environment) -> list[str]:
    """The pytest command of one part; it writes a JUnit report where the environment names a directory."""
    command = [sys.executable, "-m", "pytest", "-q", *PARALLEL, *arguments]
    if environment.get(REPORTS_VARIABLE):
        report = Path(environment[REPORTS_VARIABLE]) / f"{part_name(part).replace('/', '-')}.xml"
        command.append(f"--junitxml={report}")
    return command


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
    running at the cap (CAP_SECONDS) is stopped, and its output ends naming the tests it ran then."""
    command = part_command(part, arguments, os.environ)
    process = subprocess.Popen(command, cwd=part, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", start_new_session=os.name != "nt")
    head = f"== {part_name(part)}: {' '.join(command[1:])} in {part}\n"
    try:
        output, _ = process.communicate(timeout=CAP_SECONDS)
    except subprocess.TimeoutExpired:
        import bounds  # Only here: an adapter's conftest.py loads this module without test/ on its path.

        running = ", ".join(bounds.running_tests(run_folder, part)) or "no test (collecting, or ending its session)"
        stop(process)
        output, _ = process.communicate()
        return 1, (f"{head}{output}test/suite.py: {part_name(part)} reached the suite's cap of {CAP_SECONDS} s "
                   f"(CAP_SECONDS) and was stopped while running {running}. Remedy: run that test alone in "
                   f"{part} with `uv run pytest <test>` and find what it waits for.\n")
    return process.returncode, head + output


def stop(process: subprocess.Popen) -> None:
    """Stop the process and every process it started: its xdist workers, their browsers and drivers."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
    else:
        import signal

        os.killpg(process.pid, signal.SIGKILL)


def setup(arguments: list[str], clock) -> int:
    """Install the Node test packages not installed from their current lockfiles."""
    if arguments != [SETUP]:
        print(f"test/suite.py: {SETUP} takes no other arguments; run `{SETUP_COMMAND}`.", file=sys.stderr)
        return 2
    started = clock()
    try:
        installed = install_node_packages(NODE_PACKAGES)
    except InstallError as error:
        print(error, file=sys.stderr)
        return 1
    packages = ", ".join(package.relative_to(ROOT).as_posix() for package in installed or NODE_PACKAGES)
    if installed:
        print(f"test/suite.py: installed Node test packages {packages} in {clock() - started:.1f} s.")
    else:
        print(f"test/suite.py: Node test packages {packages} are installed from their lockfiles.")
    return 0


def main(arguments: list[str], clock=time.monotonic) -> int:
    if SETUP in arguments:
        return setup(arguments, clock)
    missing = [package for package in NODE_PACKAGES if not is_installed(package)]
    if missing:
        lockfiles = ", ".join(str(package / "package-lock.json") for package in missing)
        print(f"test/suite.py: Node test packages are not installed from their lockfiles {lockfiles}; "
              f"no part ran. Run the setup first: `{SETUP_COMMAND}` ([tests] setup in se.toml).",
              file=sys.stderr)
        return 1
    started = clock()
    names = [part_name(part) for part in PARTS]
    print(f"test/suite.py: running {', '.join(names)} side by side; each part's output follows "
          "when it ends.", flush=True)
    import spec_build  # Only here: an adapter's conftest.py loads this module without test/ on its path.

    failed = []
    with tempfile.TemporaryDirectory(prefix="obs-spec-build-") as shared:
        os.environ[spec_build.RUN_FOLDER] = shared  # Each part, and each of its workers, inherits it.
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
        builds = spec_build.counts(Path(shared))
    print(f"test/suite.py: parts took {clock() - started:.1f} s.")
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
