from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from obs_html.timings import stage


LOCAL_PATH = "<local-path>"
"""Stands in for an absolute path of the build machine outside the command root and home folder."""

_SEGMENT = r"""[^\s/\\:*?"'<>|`,;()\[\]{}=]"""
_ABSOLUTE = re.compile(
    r"(?<![\w.~/\\:<>])(?:[A-Za-z]:[/\\]|\\\\|/)"  # POSIX root, drive letter or UNC prefix
    rf"(?:{_SEGMENT}+[/\\])*{_SEGMENT}+"
)


class CommandError(ValueError):
    """Raised when derived command content cannot be produced."""


@stage("commands")
def run_command(command: str, cwd: Path, timeout_seconds: int) -> str:
    if not command.strip():
        raise CommandError("A command fence cannot be empty.")
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise CommandError(
            f"Command exceeded the {timeout_seconds}-second timeout: {command}"
        ) from error
    if completed.returncode != 0:
        output = completed.stdout.strip()
        detail = f"\n{output}" if output else ""
        raise CommandError(f"Command exited with code {completed.returncode}: {command}{detail}")
    return redact_local_paths(completed.stdout, cwd)


def redact_local_paths(text: str, root: Path) -> str:
    """Replace the build machine's absolute paths in command output.

    Paths inside the command root become relative to it, the home folder becomes ``~`` and every
    other absolute path becomes LOCAL_PATH. README.md, section "Command fences", owns the rule.
    """
    flags = re.IGNORECASE if os.name == "nt" else 0
    end = rf"(?!{_SEGMENT})"
    for folder in _spellings(root):
        text = re.sub(rf"{re.escape(folder)}(?:[/\\](?={_SEGMENT})|{end})",
                      lambda match: "" if match[0][-1:] in "/\\" else ".", text, flags=flags)
    home = Path.home()
    if home.parent != home:
        for folder in _spellings(home):
            text = re.sub(rf"{re.escape(folder)}(?=[/\\]|{end})", "~", text, flags=flags)
    return _ABSOLUTE.sub(LOCAL_PATH, text)


def _spellings(folder: Path) -> list[str]:
    """The folder as written and resolved, with native and forward slashes, longest first."""
    paths = {folder.absolute(), folder.resolve()}
    spellings = {spelling for path in paths for spelling in (str(path), path.as_posix())}
    return sorted(spellings, key=len, reverse=True)
