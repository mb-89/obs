"""Run the complete suite: the core's and every integrated adapter's, each in its own pytest.

Reader: whoever runs or changes the complete suite, and CI.

It runs every test of the core and of every adapter, except the core's browser and e2e tests of
the interim adapter (test/tiers.py selects them; the adapter's parity gate compares the interim
adapter): those run with `uv run pytest --gate`, which takes the same parallel options
(`-n auto --dist loadgroup`). Its time budget is `[tests]` in `se.toml`.

Each part tests only itself, with its own `pyproject.toml` settings and `conftest.py`, so each
runs as its own pytest process from its own folder, its tests spread over one worker process
per CPU (pytest-xdist, `-n auto --dist loadgroup`: a module's tests share a worker; groups start
in collection order, so a part can start its longest tests first). The parts run side by side,
so a short part fills the CPUs a long part leaves idle while it builds its inputs; each part's
output is printed when it ends. Every part runs to its end even when another fails; the exit
code is non-zero when any part failed. Arguments are passed on to every part's pytest, for
example `--durations=20`. Where `SE_TEST_REPORTS` names a directory, each part writes its JUnit
XML report there as `<part>.xml` (`core.xml`, `adapters-html.xml`), from which se's
`work_tickets.py suite` names the slowest tests. Install the Node test packages once first:
`npm --prefix test/browser ci` and `npm --prefix adapters/html/test/browser ci`.

    uv run python test/suite.py
"""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The core, then each integrated adapter folder under adapters/.
PARTS = [ROOT, *sorted(path.parent for path in (ROOT / "adapters").glob("*/pyproject.toml"))]
PARALLEL = ["-n", "auto", "--dist", "loadgroup", "--no-loadscope-reorder"]
REPORTS_VARIABLE = "SE_TEST_REPORTS"


def part_name(part: Path) -> str:
    return part.relative_to(ROOT).as_posix() if part != ROOT else "core"


def part_command(part: Path, arguments: list[str], environment) -> list[str]:
    """The pytest command of one part; it writes a JUnit report where the environment names a directory."""
    command = [sys.executable, "-m", "pytest", "-q", *PARALLEL, *arguments]
    if environment.get(REPORTS_VARIABLE):
        report = Path(environment[REPORTS_VARIABLE]) / f"{part_name(part).replace('/', '-')}.xml"
        command.append(f"--junitxml={report}")
    return command


def run_part(part: Path, arguments: list[str]) -> tuple[int, str]:
    """Run one part's pytest; its exit code and its output, headed by its command."""
    command = part_command(part, arguments, os.environ)
    result = subprocess.run(command, cwd=part, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    return result.returncode, f"== {part_name(part)}: {' '.join(command[1:])} in {part}\n{result.stdout}"


def main(arguments: list[str]) -> int:
    names = [part_name(part) for part in PARTS]
    print(f"test/suite.py: running {', '.join(names)} side by side; each part's output follows "
          "when it ends.", flush=True)
    failed = []
    with ThreadPoolExecutor(len(PARTS)) as pool:
        running = {pool.submit(run_part, part, arguments): part for part in PARTS}
        for finished in as_completed(running):
            code, output = finished.result()
            print(output, end="" if output.endswith("\n") else "\n", flush=True)
            if code:
                failed.append(part_name(running[finished]))
    if failed:
        failed.sort(key=names.index)
        print(f"test/suite.py: failed parts: {', '.join(failed)}. Remedy: rerun `uv run pytest` in each "
              "failed part's folder and fix what it reports.", file=sys.stderr)
        return 1
    print(f"test/suite.py: all {len(PARTS)} parts passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
