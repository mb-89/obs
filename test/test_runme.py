"""obs's entry through se's generic RUNME pair: RUNME.conf declares what obs needs and its command
line, and RUNME.sh hands every argument to obs-document in the caller's folder.

The pair itself is se's (CI's gate compares it with se's at se.lock's commit); these tests hold
obs's declaration and what a call through it does. adapters/html/spec/cli.md, "Setup", owns the
behaviour; RUNME.sh's header owns RUNME.conf's format.
"""
import os
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
RUNME = ROOT / "RUNME.sh"
CONF = ROOT / "RUNME.conf"
# What the suite's process sets and a person's shell does not: the suite's environment, which uv
# would otherwise warn about, as test/spec_build.py drops it; and uv's TLS choice.
DROPPED = ("VIRTUAL_ENV", "UV_NATIVE_TLS")


def _environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key not in DROPPED}


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=cwd, env=_environment(), text=True, encoding="utf-8",
                          capture_output=True, timeout=600)


def _entries(kind: str) -> list[list[str]]:
    """RUNME.conf's lines of one kind, each split into its words after the kind."""
    lines = CONF.read_text(encoding="utf-8").splitlines()
    return [line.split()[1:] for line in lines if line.split()[:1] == [kind]]


def test_runme_help_is_obs_documents_help() -> None:
    through = _run(["sh", str(RUNME), "--help"], ROOT)
    direct = _run(["uv", "run", "obs-document", "--help"], ROOT)
    assert (through.returncode, through.stderr) == (0, ""), through.stderr
    assert through.stdout == direct.stdout


def test_a_relative_path_resolves_from_the_callers_folder(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[note]]\n", encoding="utf-8")
    (vault / "note.md").write_text("# Note\n\nOne note.\n", encoding="utf-8")
    result = _run(["sh", str(RUNME), "--source", "vault/manifest.md", "--adapter", "html",
                   "--destination", "out.html"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "out.html").is_file()


def test_runme_runs_the_plugin_command(tmp_path: Path) -> None:
    through = _run(["sh", str(RUNME), "plugins", "--help"], tmp_path)
    direct = _run(["uv", "run", "--project", str(ROOT), "obs-plugins", "--help"], tmp_path)
    assert (through.returncode, through.stderr) == (0, ""), through.stderr
    assert through.stdout == direct.stdout


def test_runme_conf_declares_obs_needs_and_its_command_line() -> None:
    assert [entry[0] for entry in _entries("need")] == ["git", "curl", "uv", "npm"]
    [run] = [shlex.split(" ".join(entry)) for entry in _entries("run")]
    assert run[:4] == ["uv", "run", "--project", "$RUNME_ROOT"]
    assert run[4:] == ["obs-document"]
