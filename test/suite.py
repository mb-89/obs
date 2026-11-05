"""Run the complete suite: the core's and every integrated adapter's, each in its own pytest.

Reader: whoever runs or changes the complete suite, and CI.

Each part tests only itself, with its own `pyproject.toml` settings and `conftest.py`, so each
runs as its own pytest process from its own folder. Every part runs even when an earlier one
fails; the exit code is non-zero when any part failed. Install the Node test packages once
first: `npm --prefix test/browser ci` and `npm --prefix adapters/html/test/browser ci`.

    uv run python test/suite.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The core, then each integrated adapter folder under adapters/.
PARTS = [ROOT, *sorted(path.parent for path in (ROOT / "adapters").glob("*/pyproject.toml"))]


def main() -> int:
    failed = []
    for part in PARTS:
        name = part.relative_to(ROOT).as_posix() if part != ROOT else "core"
        print(f"== {name}: pytest -q in {part}", flush=True)
        if subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=part).returncode:
            failed.append(name)
    if failed:
        print(f"test/suite.py: failed parts: {', '.join(failed)}. Remedy: rerun `uv run pytest` in each "
              "failed part's folder and fix what it reports.", file=sys.stderr)
        return 1
    print(f"test/suite.py: all {len(PARTS)} parts passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
