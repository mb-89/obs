import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from obs_html_interim.commands import CommandError, run_command


def test_command_runner_captures_process_output(tmp_path: Path) -> None:
    output = run_command("echo live-owner", cwd=tmp_path, timeout_seconds=5)

    assert output.strip() == "live-owner"


def test_command_runner_translates_timeout(tmp_path: Path, monkeypatch) -> None:
    timeout = subprocess.TimeoutExpired("show help", 5)
    process = Mock(side_effect=timeout)
    monkeypatch.setattr("obs_html_interim.commands.subprocess.run", process)

    with pytest.raises(CommandError) as raised:
        run_command("show help", cwd=tmp_path, timeout_seconds=5)

    assert str(raised.value) == "Command exceeded the 5-second timeout: show help"
    assert raised.value.__cause__ is timeout
    process.assert_called_once_with(
        "show help",
        cwd=tmp_path,
        shell=True,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=5,
    )


@pytest.mark.parametrize(
    ("output", "detail"),
    [("  failure details\n", "\nfailure details"), ("", ""), (" \n", "")],
)
def test_command_runner_rejects_nonzero_exit(
    tmp_path: Path, monkeypatch, output: str, detail: str,
) -> None:
    process = Mock(return_value=subprocess.CompletedProcess("show help", 7, output))
    monkeypatch.setattr("obs_html_interim.commands.subprocess.run", process)

    with pytest.raises(CommandError) as raised:
        run_command("show help", cwd=tmp_path, timeout_seconds=5)

    assert str(raised.value) == f"Command exited with code 7: show help{detail}"
    process.assert_called_once()


@pytest.mark.parametrize("command", ["", " ", "\n\t"])
def test_command_runner_rejects_empty_command_without_starting_process(
    tmp_path: Path, monkeypatch, command: str,
) -> None:
    process = Mock()
    monkeypatch.setattr("obs_html_interim.commands.subprocess.run", process)

    with pytest.raises(CommandError, match="^A cmd fence cannot be empty\\.$"):
        run_command(command, cwd=tmp_path, timeout_seconds=5)

    process.assert_not_called()
