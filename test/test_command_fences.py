"""obs-document runs authorized cmd fences and carries their captured output in the Document.

Reader: whoever changes how the core runs command fences; capabilities/command-fences owns the
contract.
"""
import json
import re
import sys
from pathlib import Path

import pytest

from obs import commands
from obs.commands import MINIMAL_ENVIRONMENT
from obs.document import main


ROOT = Path(__file__).parents[1]


def _vault(tmp_path: Path, chapter: str) -> Path:
    vault = tmp_path / "vault"
    (vault / "notes").mkdir(parents=True)
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text(chapter, encoding="utf-8")
    return vault


def _reference(tmp_path: Path) -> Path:
    from obs.capabilities import build_capability_reference

    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(build_capability_reference(ROOT / "spec" / "capabilities")), encoding="utf-8")
    return path


def _document(tmp_path: Path, vault: Path, *options: str) -> dict[str, object]:
    document = tmp_path / "document.json"
    assert main(["--source", str(vault / "manifest.md"), "--document", str(document),
                 "--capability-reference", str(_reference(tmp_path)), *options]) == 0
    return json.loads(document.read_text(encoding="utf-8"))


def _command_nodes(document: dict[str, object]) -> list[dict[str, object]]:
    return [node for node in document["chapters"][0]["content"] if node["type"] == "command-fences"]


def _python(script: str) -> str:
    return f'"{sys.executable}" -c "{script}"'


def test_an_authorized_build_carries_each_fence_output_in_its_node(tmp_path) -> None:
    vault = _vault(tmp_path, f"```cmd\n{_python('print(1 + 1)')}\n```\n")

    node, = _command_nodes(_document(tmp_path, vault, "--execute-commands"))

    assert node["attrs"]["output"] == "2\n"


def test_without_authorization_a_cmd_fence_fails_naming_its_note_and_the_flag(tmp_path, capsys) -> None:
    vault = _vault(tmp_path, "Text.\n\n```cmd silent\nproduce\n```\n\n```cmd\necho never\n```\n")

    with pytest.raises(SystemExit) as raised:
        main(["--source", str(vault / "manifest.md"), "--document", str(tmp_path / "document.json"),
              "--capability-reference", str(_reference(tmp_path))])

    message = str(raised.value.code)
    assert message.startswith(f"obs-document: {vault.resolve() / 'chapter.md'}: cmd fence 2: ")
    assert "--execute-commands" in message
    assert message.endswith("see capabilities/command-fences.")
    assert not (tmp_path / "document.json").exists()


def test_an_authorized_build_runs_producers_before_conversion(tmp_path) -> None:
    produce = _python("open('notes/made.md', 'w').write('Made.')")
    vault = _vault(tmp_path, f"```cmd silent\n{produce}\n```\n\n![[made]]\n")

    _document(tmp_path, vault, "--execute-commands")

    assert (vault / "notes" / "made.md").read_text(encoding="utf-8") == "Made."


def test_a_failing_command_fails_the_build_naming_its_note(tmp_path, capsys) -> None:
    vault = _vault(tmp_path, f"```cmd\n{_python('raise SystemExit(3)')}\n```\n")

    with pytest.raises(SystemExit) as raised:
        main(["--source", str(vault / "manifest.md"), "--document", str(tmp_path / "document.json"),
              "--capability-reference", str(_reference(tmp_path)), "--execute-commands"])

    assert str(raised.value.code).startswith(f"obs-document: {vault.resolve() / 'chapter.md'}: cmd fence 1: ")
    assert "see capabilities/command-fences." in str(raised.value.code)


def test_captured_output_carries_no_absolute_path_of_the_build_machine(tmp_path, monkeypatch) -> None:
    home, temporary = tmp_path / "home" / "builder", tmp_path / "scratch" / ".venv"
    for folder in (home, temporary):
        folder.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("VIRTUAL_ENV", str(temporary))
    monkeypatch.setenv("TMPDIR", str(temporary))
    script = ("import os, sys; "
              "print('home', os.environ.get('HOME') or os.environ.get('USERPROFILE')); "
              "print('venv', os.environ.get('VIRTUAL_ENV', 'unset')); "
              "print('pwd', os.getcwd()); "
              "print('note', os.path.join(os.getcwd(), 'notes', 'a.md')); "
              "print('cache', os.path.join(os.path.expanduser('~'), '.cache')); "
              "print('temp', os.environ['TMPDIR']); "
              "print('prefix', sys.prefix)")
    vault = _vault(tmp_path, f"```cmd\n{_python(script)}\n```\n")

    document = _document(tmp_path, vault, "--execute-commands")

    output = _command_nodes(document)[0]["attrs"]["output"]
    assert "home ~\n" in output
    assert "venv unset\n" in output
    assert "pwd .\n" in output
    assert f"note {Path('notes', 'a.md')}\n" in output
    assert f"cache {Path('~', '.cache')}\n" in output
    assert "temp <local-path>\n" in output
    assert "prefix <local-path>\n" in output
    text = json.dumps(output)
    for path in (home, vault, temporary, Path(sys.prefix)):
        for spelling in {str(path), path.as_posix(), json.dumps(str(path))[1:-1]}:
            assert spelling not in text


def test_commands_run_with_the_documented_minimal_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OBS_BUILDER_SECRET", "machine-specific")
    vault = _vault(tmp_path, f"```cmd\n{_python('import os; print(*sorted(os.environ))')}\n```\n")

    output = _command_nodes(_document(tmp_path, vault, "--execute-commands"))[0]["attrs"]["output"]

    names = set(output.split())
    assert names <= set(MINIMAL_ENVIRONMENT) | {"PWD", "SHLVL", "_", "LC_CTYPE", "OLDPWD"}
    assert "OBS_BUILDER_SECRET" not in names
    note = (ROOT / "spec" / "capabilities" / "command-fences.md").read_text(encoding="utf-8")
    assert all(f"`{name}`" in note for name in MINIMAL_ENVIRONMENT)


def test_the_check_on_captured_output_names_what_it_found(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(commands, "redact_local_paths", lambda text, root: text)
    vault = _vault(tmp_path, f"```cmd\n{_python('import os; print(os.getcwd())')}\n```\n")

    with pytest.raises(SystemExit) as raised:
        main(["--source", str(vault / "manifest.md"), "--document", str(tmp_path / "document.json"),
              "--capability-reference", str(_reference(tmp_path)), "--execute-commands"])

    message = str(raised.value.code)
    assert re.match(rf"obs-document: {re.escape(str(vault.resolve() / 'chapter.md'))}: cmd fence 1: ", message)
    assert "command root" in message and "see capabilities/command-fences." in message
