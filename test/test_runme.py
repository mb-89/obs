"""obs's entry through se's generic RUNME pair: RUNME.conf declares what obs needs and its command
line, and RUNME.sh hands every argument to obs-document in the caller's folder.

The pair itself is se's (CI's gate compares it with se's at se.lock's commit); these tests hold
obs's declaration and what a call through it does. spec/design_input/cli.md, "Setup", owns the
behaviour; RUNME.sh's header owns RUNME.conf's format.
"""
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from installed_components import install_adapter
from obs import document

ROOT = Path(__file__).parents[1]
RUNME = ROOT / "RUNME.sh"
CONF = ROOT / "RUNME.conf"
# What the suite's process sets and a person's shell does not: the suite's environment, which uv
# would otherwise warn about, as test/spec_build.py drops it; and uv's TLS choice.
DROPPED = ("VIRTUAL_ENV", "UV_NATIVE_TLS")
COLUMNS = "100"
"""The terminal width both helps are formatted for."""


def _environment() -> dict[str, str]:
    return {**{key: value for key, value in os.environ.items() if key not in DROPPED}, "COLUMNS": COLUMNS}


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=cwd, env=_environment(), text=True, encoding="utf-8",
                          capture_output=True, timeout=600)


def _entries(kind: str) -> list[list[str]]:
    """RUNME.conf's lines of one kind, each split into its words after the kind."""
    lines = CONF.read_text(encoding="utf-8").splitlines()
    return [line.split()[1:] for line in lines if line.split()[:1] == [kind]]


def test_runme_help_is_obs_documents_help(capsys, monkeypatch) -> None:
    """The one test that starts RUNME as a real process: it hands every argument to obs-document,
    whose help it prints as obs-document's main does in-process."""
    through = _run(["sh", str(RUNME), "--help"], ROOT)
    monkeypatch.setenv("COLUMNS", COLUMNS)
    with pytest.raises(SystemExit) as ended:
        document.main(["--help"])
    assert ended.value.code == 0
    assert (through.returncode, through.stderr) == (0, ""), through.stderr
    assert through.stdout == capsys.readouterr().out


def test_a_relative_path_resolves_from_the_callers_folder(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[note]]\n", encoding="utf-8")
    (vault / "note.md").write_text("# Note\n\nOne note.\n", encoding="utf-8")
    install_adapter({"name": "fixture", "contractVersion": 1, "capabilities": ["chapter-inclusion", "manifest", "markdown",
                                                                          "markdown-frontmatter", "queries", "wikilinks"],
                     "command": [sys.executable, "-c",
                                 "import sys, pathlib; pathlib.Path(sys.argv[2]).write_text('ok')"]})
    monkeypatch.chdir(tmp_path)
    assert document.main(["--source", "vault/manifest.md", "--adapter", "fixture", "--destination", "out.html"]) == 0
    assert (tmp_path / "out.html").is_file()


def test_runme_conf_declares_obs_needs_and_its_command_line() -> None:
    assert [entry[0] for entry in _entries("need")] == ["git", "curl", "uv", "npm"]
    [run] = [shlex.split(" ".join(entry)) for entry in _entries("run")]
    assert run[:4] == ["uv", "run", "--project", "$RUNME_ROOT"]
    assert run[4:] == ["obs-document"]
