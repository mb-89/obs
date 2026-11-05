import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from obs.producers import ProducerError, run_producers


def test_authorized_producers_run_silent_cmd_fences_in_path_and_source_order(
    tmp_path: Path, monkeypatch,
) -> None:
    (tmp_path / "zeta.md").write_text(
        "```cmd silent\nsecond\n```\n\n```cmd\nvisible\n```\n", encoding="utf-8",
    )
    (tmp_path / "alpha.md").write_text(
        "```cmd silent\nfirst\n```\n\n```cmd silent\nthird\n```\n", encoding="utf-8",
    )
    calls: list[str] = []

    def run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "")

    monkeypatch.setattr("obs.producers.subprocess.run", run)

    assert run_producers(tmp_path, authorized=True, timeout_seconds=5) == 3
    assert calls == ["first", "third", "second"]


def test_unauthorized_producers_do_not_start_processes(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "chapter.md").write_text("```cmd silent\nmust-not-run\n```\n", encoding="utf-8")
    process = Mock()
    monkeypatch.setattr("obs.producers.subprocess.run", process)

    assert run_producers(tmp_path, authorized=False, timeout_seconds=5) == 0
    process.assert_not_called()


def test_producer_failure_includes_the_source_location(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "chapter.md").write_text("```cmd silent\nfail\n```\n", encoding="utf-8")
    monkeypatch.setattr(
        "obs.producers.subprocess.run",
        Mock(return_value=subprocess.CompletedProcess("fail", 7, "details\n")),
    )

    with pytest.raises(ProducerError, match=r"chapter\.md:1: Command exited with code 7: fail\ndetails"):
        run_producers(tmp_path, authorized=True, timeout_seconds=5)
