"""Run the complete suite: the core's and every integrated adapter's, each in its own pytest.

Reader: whoever runs or changes the complete suite, and CI.

It runs every test of the core and of every adapter, except the core's browser and e2e tests of
the interim adapter (test/tiers.py selects them; the adapter's parity gate compares the interim
adapter): those run with `uv run pytest --gate`, which takes the same parallel options
(`-n auto --dist loadgroup`). Its time budget is `[tests]` in `se.toml`.

Each part tests only itself, with its own `pyproject.toml` settings and `conftest.py`, so each
runs as its own pytest process from its own folder, its tests spread over one worker process
per CPU (pytest-xdist, `-n auto --dist loadgroup`: a module's tests share a worker; groups start
in collection order, so a part can start its longest tests first). Every part
runs even when an earlier one fails; the exit code is non-zero when any part failed. Arguments
are passed on to every part's pytest, for example `--durations=20`. Install the Node test
packages once first: `npm --prefix test/browser ci` and `npm --prefix adapters/html/test/browser ci`.

    uv run python test/suite.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The core, then each integrated adapter folder under adapters/.
PARTS = [ROOT, *sorted(path.parent for path in (ROOT / "adapters").glob("*/pyproject.toml"))]
PARALLEL = ["-n", "auto", "--dist", "loadgroup", "--no-loadscope-reorder"]


def main(arguments: list[str]) -> int:
    failed = []
    for part in PARTS:
        name = part.relative_to(ROOT).as_posix() if part != ROOT else "core"
        command = [sys.executable, "-m", "pytest", "-q", *PARALLEL, *arguments]
        print(f"== {name}: {' '.join(command[1:])} in {part}", flush=True)
        if subprocess.run(command, cwd=part).returncode:
            failed.append(name)
    if failed:
        print(f"test/suite.py: failed parts: {', '.join(failed)}. Remedy: rerun `uv run pytest` in each "
              "failed part's folder and fix what it reports.", file=sys.stderr)
        return 1
    print(f"test/suite.py: all {len(PARTS)} parts passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
