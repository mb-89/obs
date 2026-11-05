import json
import sys
from pathlib import Path

from conftest import FIXTURE, ROOT
from obs_html import cli
from obs_html.commands import MINIMAL_ENVIRONMENT
from obs_html.report_data import decode_report_data


def _with_command(tmp_path: Path, command: str) -> Path:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    text = json.dumps(document).replace('"echo derived\\n"', json.dumps(command))
    source = tmp_path / "document.json"
    source.write_text(text, encoding="utf-8")
    return source


def _command_output(destination: Path) -> str:
    notes = decode_report_data(destination.read_text(encoding="utf-8"))["notes"]
    return "".join(note["html"] for note in notes if "command-output" in note["html"])


def test_command_output_carries_no_absolute_path_of_the_build_machine(tmp_path, monkeypatch) -> None:
    home, root, temporary = tmp_path / "home" / "builder", tmp_path / "vault", tmp_path / "scratch" / ".venv"
    for folder in (home, root / "notes", temporary):
        folder.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("VIRTUAL_ENV", str(temporary))
    script = ("import os, sys; "
              "print('home', os.environ.get('HOME') or os.environ.get('USERPROFILE')); "
              "print('venv', os.environ.get('VIRTUAL_ENV', 'unset')); "
              "print('pwd', os.getcwd()); "
              f"print('note', os.path.join(os.getcwd(), 'notes', 'a.md')); "
              f"print('cache', os.path.join(os.path.expanduser('~'), '.cache')); "
              f"print('temp', {str(temporary)!r}); "
              "print('prefix', sys.prefix)")
    destination = tmp_path / "document.html"
    cli.main([str(_with_command(tmp_path, f'"{sys.executable}" -c "{script}"')), str(destination),
              "--execute-commands", "--command-root", str(root)])
    output = _command_output(destination)
    assert "home ~\n" in output
    assert "venv unset\n" in output
    assert "pwd .\n" in output
    assert f"note {Path('notes', 'a.md')}\n" in output
    assert f"cache {Path('~', '.cache')}\n" in output
    assert "temp &lt;local-path&gt;\n" in output
    assert "prefix &lt;local-path&gt;\n" in output
    report = destination.read_text(encoding="utf-8") + json.dumps(decode_report_data(
        destination.read_text(encoding="utf-8")))
    for path in (home, root, temporary, Path(sys.prefix)):
        for spelling in {str(path), path.as_posix(), json.dumps(str(path))[1:-1]}:
            assert spelling not in report


def test_commands_run_with_the_documented_minimal_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OBS_HTML_BUILDER_SECRET", "machine-specific")
    script = "import os; print('names', *sorted(os.environ))"
    destination = tmp_path / "document.html"
    cli.main([str(_with_command(tmp_path, f'"{sys.executable}" -c "{script}"')), str(destination),
              "--execute-commands", "--command-root", str(tmp_path)])
    line = next(line for line in _command_output(destination).splitlines() if "names " in line)
    names = set(line.split("names ", 1)[1].split())
    assert names <= set(MINIMAL_ENVIRONMENT) | {"PWD", "SHLVL", "_", "LC_CTYPE", "OLDPWD"}
    assert "OBS_HTML_BUILDER_SECRET" not in names
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert all(f"`{name}`" in readme for name in MINIMAL_ENVIRONMENT)
