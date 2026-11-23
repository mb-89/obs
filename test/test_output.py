"""The core's output writer and reader where the system refuses a file another handle holds.

Owner: spec/design_input/architecture.md ("Safety boundaries"). Windows refuses to replace a file a
reader holds open and to read one while it is replaced; these tests make the system refuse, so they
run alike on every platform, and the pause between attempts is the conftest's yield, never a wait.
"""
import os
from pathlib import Path

import pytest

from obs import output


def _refusing(times: int, then):
    """A call that raises the sharing violation ``times`` times, then does what ``then`` does."""
    calls = []

    def call(*arguments):
        calls.append(arguments)
        if len(calls) <= times:
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")
        return then(*arguments)

    return call, calls


def test_a_replacement_refused_while_a_reader_holds_the_file_succeeds_once_it_lets_go(
        tmp_path: Path, monkeypatch, pauses) -> None:
    source, target = tmp_path / "new", tmp_path / "out.json"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    replace, calls = _refusing(3, os.replace)
    monkeypatch.setattr(output, "SHARING_REFUSED", True)
    monkeypatch.setattr(output.os, "replace", replace)

    output.replace_file(source, target)

    assert target.read_bytes() == b"new"
    assert len(calls) == 4
    assert len(pauses) == 3, "one pause between two attempts, no other"


def test_a_read_refused_while_a_writer_replaces_the_file_returns_its_bytes_once_it_is_replaced(
        tmp_path: Path, monkeypatch, pauses) -> None:
    path = tmp_path / "capability-reference.json"
    path.write_bytes(b"{}")
    read, calls = _refusing(2, Path.read_bytes)
    monkeypatch.setattr(output, "SHARING_REFUSED", True)
    monkeypatch.setattr(Path, "read_bytes", read)

    assert output.read_file(path) == b"{}"
    assert (len(calls), len(pauses)) == (3, 2)


def test_a_refusal_that_outlasts_every_attempt_fails_with_the_system_s_refusal(
        tmp_path: Path, monkeypatch, pauses) -> None:
    replace, calls = _refusing(output.ATTEMPTS, os.replace)
    monkeypatch.setattr(output, "SHARING_REFUSED", True)
    monkeypatch.setattr(output.os, "replace", replace)

    with pytest.raises(PermissionError):
        output.replace_file(tmp_path / "new", tmp_path / "out.json")

    assert len(calls) == output.ATTEMPTS
    assert len(pauses) == output.ATTEMPTS - 1


def test_where_the_system_shares_files_the_first_refusal_fails_without_a_pause(
        tmp_path: Path, monkeypatch, pauses) -> None:
    replace, calls = _refusing(1, os.replace)
    monkeypatch.setattr(output, "SHARING_REFUSED", False)
    monkeypatch.setattr(output.os, "replace", replace)

    with pytest.raises(PermissionError):
        output.replace_file(tmp_path / "new", tmp_path / "out.json")

    assert (len(calls), pauses) == (1, [])


def test_the_output_writer_replaces_through_the_retried_replacement(tmp_path: Path, monkeypatch, pauses) -> None:
    replace, calls = _refusing(1, os.replace)
    monkeypatch.setattr(output, "SHARING_REFUSED", True)
    monkeypatch.setattr(output.os, "replace", replace)
    path = tmp_path / "document.json"

    output.write_output(path, "{}\n")

    assert path.read_text(encoding="utf-8") == "{}\n"
    assert (len(calls), len(pauses)) == (2, 1)
    assert sorted(child.name for child in tmp_path.iterdir()) == ["document.json"], "no temporary file is left"
