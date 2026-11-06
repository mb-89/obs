"""obs's spec, built once per run and shared by the core's and every adapter's tests.

Reader: a test that reads obs's spec Document or the interim reference's spec artifact, and
whoever changes how the suite builds them; quality.md, Testing boundaries, owns the rule.

Each kind in BUILDS is built at most once per run: ``document``, the spec's Document with its
capability reference, and ``interim``, the interim reference's artifact of the spec. The first
process of the run that asks builds it under a lock, in the run's folder, and every other
process, of any part, reads what it built. test/suite.py makes the run's folder and names it in
RUN_FOLDER for its parts; a focused run (a part's own pytest) builds in its pytest base folder.
A build's folder is named by a hash of its inputs (INPUTS: the spec vault without what its
producers write, the core's, the interim reference's and the HTML adapter's sources, and this
build), so changed inputs are never served a stale build. Each build appends its kind and key to
COUNTER in the run's folder, which test/suite.py reads at the run's end: where one kind was built
twice, the run fails.

Both builds run the spec's commands and producers in its vault, offline: the core's
test/offline_obs_document.py serves each remote image as a placeholder. They write only what
the producers write into the vault's generated design_output, as any build of the spec does.

A test that needs another build of the spec (another option, a copied vault) copies the vault
and builds only that variant. ``own_builds`` names a test that builds the spec itself; the
core's test/structure/test_spec_builds.py and the adapter's test/structure/test_quality.py
refuse one outside their named exceptions.
"""
import hashlib
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

from filelock import FileLock

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "spec"
# The variable test/suite.py names the run's folder in.
RUN_FOLDER = "OBS_SPEC_BUILD"
# In the run's folder: one line per build, its kind and its inputs' key.
COUNTER = "builds.txt"
# The Document build's files, in its folder.
DOCUMENT, CAPABILITIES = "spec.json", "capabilities.json"
# The interim reference's artifact, in its folder.
INTERIM = "reference.html"
# What a build reads, relative to ROOT; GENERATED parts of a path are no input.
INPUTS = ("spec", "src", "adapters/html/src", "adapters/html/spec", "adapters.json", "adapters/html/adapter.json",
          "uv.lock", "test/offline_obs_document.py", "test/spec_build.py")
GENERATED = {"design_output", "__pycache__", "node_modules"}
# The core's obs-document without the network.
OFFLINE_DOCUMENT = ROOT / "test" / "offline_obs_document.py"


class SpecBuildError(Exception):
    """A shared build of obs's spec failed; the message names the step, its command and its output."""


def _run(command: list[str], what: str) -> None:
    environment = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
    result = subprocess.run(command, cwd=ROOT, env=environment, text=True, encoding="utf-8",
                            capture_output=True, timeout=900)
    if result.returncode:
        raise SpecBuildError(f"test/spec_build.py: {what} failed: {' '.join(command)} (in {ROOT})\n"
                             f"{result.stdout[-2000:]}{result.stderr[-2000:]}")


def build_document(folder: Path) -> None:
    """obs's spec as the core's Document, with the capability reference built from its notes."""
    capabilities = SPEC / "capabilities"
    _run([sys.executable, "-m", "obs.capabilities", "--notes", str(capabilities),
          "--coverage", str(capabilities / "coverage.json"), "--output", str(folder / CAPABILITIES)],
         "building the capability reference with the core")
    _run([sys.executable, str(OFFLINE_DOCUMENT), "--document", str(folder / DOCUMENT),
          "--source", str(SPEC / "manifest.md"), "--capability-reference", str(folder / CAPABILITIES),
          "--execute-commands"], "building obs's spec Document with the core, without the network")


def build_interim(folder: Path) -> None:
    """obs's spec as the interim reference renders it."""
    _run([sys.executable, "-m", "obs_html_interim.cli", "--source", str(SPEC), "--output", str(folder / INTERIM),
          "--execute-commands"], "rendering obs's spec with the interim reference")


BUILDS = {"document": build_document, "interim": build_interim}
# The inputs' key, computed once per process.
_keys: dict[str, str] = {}


def inputs_key() -> str:
    """A hash of every input file's path and bytes."""
    if "inputs" not in _keys:
        digest = hashlib.sha256()
        for top in INPUTS:
            path = ROOT / top
            files = [path] if path.is_file() else sorted(path.rglob("*"))
            for file in files:
                parts = file.relative_to(ROOT).parts
                if GENERATED & set(parts) or any(part.startswith(".") for part in parts) or not file.is_file():
                    continue
                digest.update(file.relative_to(ROOT).as_posix().encode() + b"\0" + file.read_bytes() + b"\0")
        _keys["inputs"] = digest.hexdigest()[:16]
    return _keys["inputs"]


def base(tmp_path_factory) -> Path:
    """The run's folder: test/suite.py's, or in a focused run the pytest base folder all workers share."""
    if os.environ.get(RUN_FOLDER):
        return Path(os.environ[RUN_FOLDER])
    root = tmp_path_factory.getbasetemp()
    return root.parent if os.environ.get("PYTEST_XDIST_WORKER") else root


def built(run: Path, kind: str) -> Path:
    """The folder holding the run's build of ``kind`` (a key of BUILDS), built once and counted."""
    key = inputs_key()
    folder = run / f"{kind}-{key}"
    with FileLock(f"{folder}.lock"):
        if not (folder / ".built").is_file():
            folder.mkdir(parents=True, exist_ok=True)
            BUILDS[kind](folder)
            with (run / COUNTER).open("a", encoding="utf-8") as counter:
                counter.write(f"{kind} {key}\n")
            (folder / ".built").touch()
    return folder


def counts(run: Path) -> Counter:
    """How often each kind was built in the run's folder."""
    counter = run / COUNTER
    lines = counter.read_text(encoding="utf-8").splitlines() if counter.is_file() else []
    return Counter(line.split()[0] for line in lines if line.strip())
