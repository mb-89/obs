"""obs's spec is built once per run and shared by the core's and every adapter's tests.

Owner: test/spec_build.py (the build, its inputs and its count) and test/suite.py (the run's
folder, and the check at the run's end); quality.md, Testing boundaries, owns the rule.
"""
import os
from pathlib import Path

import pytest

import spec_build
import suite


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
