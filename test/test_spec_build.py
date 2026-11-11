"""obs's spec is built once per run and shared by the core's and every adapter's tests.

Owner: test/spec_build.py (the build, its inputs and its count) and test/suite.py (the run's
folder, and the check at the run's end); quality.md, Testing boundaries, owns the rule.
"""
import os
import threading
from pathlib import Path

import pytest

import spec_build
import suite


@pytest.fixture(autouse=True)
def own_run(monkeypatch):
    """This module's builds are stand-ins in run folders of their own, not builds of the run its
    process was started in (spec_build.STARTED_IN): a test that needs one names it."""
    monkeypatch.setattr(spec_build, "STARTED_IN", None, raising=False)


@pytest.fixture
def counted_builds(monkeypatch, tmp_path):
    """The shared builds with a stand-in build that records each call; its inputs are one file."""
    calls = []
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "note.md").write_text("A note.\n", encoding="utf-8")

    def build(folder: Path) -> None:
        calls.append(folder)
        (folder / "spec.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(spec_build, "ROOT", tmp_path)
    monkeypatch.setattr(spec_build, "INPUTS", ("inputs",))
    monkeypatch.setitem(spec_build.BUILDS, "document", build)
    monkeypatch.setattr(spec_build, "_keys", {})
    return calls, inputs


def test_the_spec_is_built_once_per_run_and_each_build_is_counted(counted_builds, tmp_path) -> None:
    calls, _inputs = counted_builds
    run = tmp_path / "run"
    run.mkdir()

    first = spec_build.built(run, "document")
    second = spec_build.built(run, "document")

    assert first == second and (first / "spec.json").is_file()
    assert len(calls) == 1
    assert spec_build.counts(run) == {"document": 1}


def test_changed_inputs_are_built_again_and_counted_again(counted_builds, tmp_path, monkeypatch) -> None:
    """The build's folder is named by its inputs: a changed input is never served a stale build."""
    calls, inputs = counted_builds
    run = tmp_path / "run"
    run.mkdir()
    first = spec_build.built(run, "document")

    (inputs / "note.md").write_text("A changed note.\n", encoding="utf-8")
    monkeypatch.setattr(spec_build, "_keys", {})
    second = spec_build.built(run, "document")

    assert first != second and len(calls) == 2
    assert spec_build.counts(run) == {"document": 2}


def test_the_inputs_skip_generated_files(counted_builds, tmp_path, monkeypatch) -> None:
    """What the spec's producers write (design_output) and caches are no input of the build."""
    _calls, inputs = counted_builds
    before = spec_build.inputs_key()
    for generated in ("design_output/obs-html-specification.html", "__pycache__/note.pyc"):
        (inputs / generated).parent.mkdir(parents=True, exist_ok=True)
        (inputs / generated).write_text("generated", encoding="utf-8")
    monkeypatch.setattr(spec_build, "_keys", {})

    assert spec_build.inputs_key() == before


def suite_run(tmp_path, monkeypatch, builds: list[str]):
    """test/suite.py's main with stand-in parts; the core's records ``builds`` in the run's folder."""
    folders = []
    monkeypatch.delenv(spec_build.RUN_FOLDER, raising=False)

    def run_part(part: Path, arguments: list[str], run_folder: Path) -> tuple[int, str]:
        folder = Path(os.environ[spec_build.RUN_FOLDER])
        folders.append(folder)
        if part == suite.ROOT:
            with (folder / spec_build.COUNTER).open("a", encoding="utf-8") as counter:
                counter.writelines(f"{kind} key-{index}\n" for index, kind in enumerate(builds))
        return 0, f"== {suite.part_name(part)}\n"

    monkeypatch.setattr(suite, "NODE_PACKAGES", [])
    monkeypatch.setattr(suite, "run_part", run_part)
    return suite.main([]), folders


def test_the_suite_reports_one_build_per_run(tmp_path, monkeypatch, capsys) -> None:
    code, folders = suite_run(tmp_path, monkeypatch, ["document"])

    assert code == 0
    assert len(set(folders)) == 1 and not folders[0].exists(), "the run's folder outlives the run"
    assert spec_build.RUN_FOLDER not in os.environ
    out = capsys.readouterr().out
    assert "test/spec_build.py" in out and "document 1" in out and "interim" not in out


def test_the_suite_fails_where_the_spec_was_built_twice(tmp_path, monkeypatch, capsys) -> None:
    code, _folders = suite_run(tmp_path, monkeypatch, ["document", "document"])

    assert code == 1
    error = capsys.readouterr().err
    assert "test/spec_build.py" in error and "document 2" in error


def test_the_adapter_spec_fence_is_served_the_runs_one_build(counted_builds, tmp_path, monkeypatch) -> None:
    """Every build of the spec in the run, the shared one and a test's copy of the vault, is served
    the adapter's specification its producer fence writes from the run's one ``adapter-spec`` build."""
    fence, produced = spec_build.adapter_spec_fence()
    built = []

    def build(folder: Path) -> None:
        built.append(folder)
        (folder / produced).parent.mkdir(parents=True)
        (folder / produced).write_text("<title>obs-html</title>", encoding="utf-8")

    monkeypatch.setitem(spec_build.BUILDS, "adapter-spec", build)
    run = tmp_path / "run"
    run.mkdir()
    monkeypatch.setenv(spec_build.RUN_FOLDER, str(run))

    served = [spec_build.serve_adapter_spec(fence, tmp_path / vault) for vault in ("spec", "copy")]

    assert served == [True, True] and len(built) == 1
    assert all((tmp_path / vault / produced).read_text(encoding="utf-8") == "<title>obs-html</title>"
               for vault in ("spec", "copy"))
    assert spec_build.counts(run) == {"adapter-spec": 1}
    assert not spec_build.serve_adapter_spec("echo other producer", tmp_path / "spec")


def test_the_adapter_spec_build_runs_the_specs_own_fence(monkeypatch, tmp_path) -> None:
    """The run's one build of the adapter's specification is the spec's fence, unchanged."""
    runs = []
    monkeypatch.setattr(spec_build, "_run", lambda command, what, run, **options: runs.append((command, options)))

    spec_build.build_adapter_spec(tmp_path / "adapter-spec-key")

    [(command, options)] = runs
    assert command == spec_build.adapter_spec_fence()[0] and command.startswith("uv run obs-html --build-own-spec ")
    assert options["cwd"] == tmp_path / "adapter-spec-key" and options["shell"]


@pytest.mark.parametrize("kind", list(spec_build.BUILDS))
def test_the_suite_fails_where_any_kind_was_built_twice(tmp_path, monkeypatch, capsys, kind) -> None:
    code, _folders = suite_run(tmp_path, monkeypatch, [kind, kind])

    assert code == 1
    assert f"{kind} 2" in capsys.readouterr().err


class Config:
    """A part's pytest config as ``spec_build.start`` reads it: a worker's has ``workerinput``."""

    def __init__(self, worker: bool = False):
        if worker:
            self.workerinput = {"workerid": "gw0"}


def test_the_controller_starts_the_runs_build_before_its_workers_and_it_is_counted_once(
        counted_builds, tmp_path, monkeypatch) -> None:
    """In a run of the complete suite the core's controller starts the Document build in the
    background; a worker that asks while it builds waits on the same lock and reads that build."""
    calls, _inputs = counted_builds
    run = tmp_path / "run"
    run.mkdir()
    monkeypatch.setenv(spec_build.RUN_FOLDER, str(run))
    building, release = threading.Event(), threading.Event()

    def build(folder: Path) -> None:
        building.set()
        release.wait(10)
        calls.append(folder)
        (folder / "spec.json").write_text("{}", encoding="utf-8")

    monkeypatch.setitem(spec_build.BUILDS, "document", build)
    started = spec_build.start(Config())
    assert started is not None and building.wait(10), "the controller started no build"
    asked = []
    worker = threading.Thread(target=lambda: asked.append(spec_build.built(run, "document")))
    worker.start()
    release.set()
    spec_build.finish()
    worker.join(10)

    assert not started.is_alive() and len(calls) == 1
    assert asked == [run / f"document-{spec_build.inputs_key()}"]
    assert spec_build.counts(run) == {"document": 1}


@pytest.mark.parametrize("worker, run_folder", [(True, True), (False, False)], ids=["worker", "focused-run"])
def test_a_worker_and_a_focused_run_start_no_build(counted_builds, tmp_path, monkeypatch, worker, run_folder) -> None:
    """A worker leaves the start to its controller; a focused run builds only where a test asks."""
    calls, _inputs = counted_builds
    if run_folder:
        monkeypatch.setenv(spec_build.RUN_FOLDER, str(tmp_path))
    else:
        monkeypatch.delenv(spec_build.RUN_FOLDER, raising=False)

    assert spec_build.start(Config(worker)) is None
    spec_build.finish()
    assert calls == [] and spec_build.counts(tmp_path) == {}


def test_a_failed_early_build_is_not_counted_and_the_test_that_needs_it_reports_it(
        counted_builds, tmp_path, monkeypatch) -> None:
    """The background build keeps its error; the test that needs the build builds it again and
    fails with the build's own message, so a failure is reported where it matters, once."""
    _calls, _inputs = counted_builds
    run = tmp_path / "run"
    run.mkdir()
    monkeypatch.setenv(spec_build.RUN_FOLDER, str(run))

    def build(folder: Path) -> None:
        raise spec_build.SpecBuildError("test/spec_build.py: building failed: the step's output")

    monkeypatch.setitem(spec_build.BUILDS, "document", build)
    spec_build.start(Config())
    spec_build.finish()

    assert spec_build.counts(run) == {}
    with pytest.raises(spec_build.SpecBuildError, match="test/spec_build.py"):
        spec_build.built(run, "document")


def test_a_test_of_the_suite_leaves_its_workers_run_folder_so_the_spec_is_built_once(
        counted_builds, tmp_path, tmp_path_factory, monkeypatch) -> None:
    """A worker of the complete suite inherits the run's folder. A test that runs suite.main, as
    test_parallel_suite's and this module's do, leaves it in place, so the worker's next spec test
    reads the run's one build and builds no private one outside the run's count."""
    calls, _inputs = counted_builds
    run = tmp_path / "run"
    run.mkdir()
    monkeypatch.setenv(spec_build.RUN_FOLDER, str(run))
    monkeypatch.setattr(suite, "NODE_PACKAGES", [])
    monkeypatch.setattr(suite, "run_part", lambda part, arguments, run_folder: (0, ""))

    assert suite.main([]) == 0
    assert os.environ.get(spec_build.RUN_FOLDER) == str(run)
    spec_build.built(spec_build.base(tmp_path_factory), "document")
    assert len(calls) == 1 and spec_build.counts(run) == {"document": 1}


def test_a_build_outside_the_run_folder_its_process_was_started_in_is_counted_in_that_run(
        counted_builds, tmp_path, monkeypatch) -> None:
    """A process started in a run of the complete suite (STARTED_IN) that builds the spec in
    another folder, as one whose OBS_SPEC_BUILD a test removed would, is counted in the run's
    folder too, so the suite's check at the run's end fails on the second build."""
    calls, _inputs = counted_builds
    run, elsewhere = tmp_path / "run", tmp_path / "elsewhere"
    run.mkdir()
    elsewhere.mkdir()
    monkeypatch.setattr(spec_build, "STARTED_IN", run, raising=False)

    spec_build.built(run, "document")
    spec_build.built(elsewhere, "document")

    assert len(calls) == 2
    assert spec_build.counts(elsewhere) == {"document": 1}
    assert spec_build.counts(run) == {"document": 2}
    assert str(elsewhere) in (run / spec_build.COUNTER).read_text(encoding="utf-8")
