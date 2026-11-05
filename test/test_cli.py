import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import FIXTURE, ROOT
from obs_html import cli


def _run(*arguments: str) -> None:
    cli.main([str(argument) for argument in arguments])


def test_help_is_the_complete_cli_reference(capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _run("--help")
    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    for option in ("DOCUMENT", "DESTINATION", "--config", "--check", "--execute-commands", "--command-root",
                   "--export-pdf", "--output", "--check-rendered", "--timings", "Exit status"):
        assert option in output


def test_installed_command_renders_through_the_adapter_contract(tmp_path) -> None:
    destination = tmp_path / "out" / "document.html"
    completed = subprocess.run(
        [sys.executable, "-m", "obs_html.cli", FIXTURE, destination,
         "--execute-commands", "--command-root", tmp_path],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Warning: Fixture diagnostic." in completed.stderr
    assert completed.stdout == f"Generated {destination.resolve()}.\n"
    html = destination.read_text(encoding="utf-8")
    assert '<pre class="command-output">derived' in html
    assert not (tmp_path / "produced.txt").exists()  # Silent producers run in the core, before conversion.


def test_unauthorized_command_fences_fail_without_output(tmp_path, capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _run(FIXTURE, tmp_path / "document.html")
    assert exit_info.value.code == 2
    assert "--execute-commands" in capsys.readouterr().err
    assert not (tmp_path / "document.html").exists()


def test_check_renders_without_output_or_execution(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "run_command", lambda *args, **kwargs: pytest.fail("executed"))
    _run(FIXTURE, "--check")
    assert "no output written and no commands executed" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("arguments, message", [
    ([FIXTURE, "--check", "--execute-commands", "--command-root", "."], "--check cannot be combined"),
    ([FIXTURE], "DESTINATION is required"),
    ([FIXTURE, "x.html", "--execute-commands"], "only used together"),
    ([FIXTURE, "x.html", "--output", "x.pdf"], "--output is only used with --export-pdf"),
    (["--export-pdf", "a.html"], "requires --output file.pdf"),
    (["--export-pdf", "a.html", "--output", "a.html"], "requires --output file.pdf"),
    (["--check-rendered", "a.html", FIXTURE], "separate operations"),
    ([FIXTURE, FIXTURE], "must not overwrite"),
])
def test_invalid_option_combinations_fail(arguments, message, capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _run(*arguments)
    assert exit_info.value.code == 2
    assert message in capsys.readouterr().err


def test_settings_override_merges_over_the_packaged_settings(tmp_path, capsys) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"report": {"print": {"paperSizes": {
        "Letter": {"widthMillimeters": 200, "heightMillimeters": 250}}}}}), encoding="utf-8")
    destination = tmp_path / "document.html"
    _run(FIXTURE, destination, "--config", settings, "--execute-commands", "--command-root", tmp_path)
    assert "@page{size:200mm 250mm;margin:15mm}" in destination.read_text(encoding="utf-8")


@pytest.mark.parametrize("override, message", [
    ({"execution": {"commandTimeoutSeconds": 0}}, "execution.commandTimeoutSeconds"),
    ({"report": {"theme": "dark"}}, "Additional properties"),
    ({"report": {"print": {"default": {"paper": "A4", "margin": "2mm"}}}}, "out of range"),
    ({"report": {"print": {"default": {"paper": "B5", "margin": "20mm"}}}}, "must be one of"),
])
def test_invalid_settings_fail(tmp_path, override, message, capsys) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(override), encoding="utf-8")
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    del document["manifest"]["abstract"][1]  # The fixture's profile would choose its own paper.
    source = tmp_path / "document.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(SystemExit):
        _run(source, "--check", "--config", settings)
    assert message in capsys.readouterr().err


def test_identical_output_is_not_rewritten(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "document.html"
    arguments = (FIXTURE, destination, "--execute-commands", "--command-root", tmp_path)
    _run(*arguments)
    writes = []
    original = Path.replace
    monkeypatch.setattr(Path, "replace", lambda self, target: writes.append(target) or original(self, target))
    _run(*arguments)
    assert writes == []


def test_failed_write_preserves_the_previous_output(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "document.html"
    destination.write_text("previous", encoding="utf-8")

    def fail(self, target):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(SystemExit):
        _run(FIXTURE, destination, "--execute-commands", "--command-root", tmp_path)
    assert destination.read_text(encoding="utf-8") == "previous"
    assert [path.name for path in tmp_path.iterdir()] == ["document.html"]


def test_timings_print_one_line_per_stage(tmp_path, capsys) -> None:
    _run(FIXTURE, tmp_path / "document.html", "--execute-commands", "--command-root", tmp_path, "--timings")
    stages = [line.split()[1] for line in capsys.readouterr().out.splitlines() if line.startswith("Timing:")]
    assert stages == ["render", "commands", "write", "total"]
