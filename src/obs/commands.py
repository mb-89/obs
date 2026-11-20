"""Run an authorized cmd fence and capture its output without the build machine's paths.

spec/capabilities/command-fences.md, section "Captured output", owns the rule.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


LOCAL_PATH = "<local-path>"
"""Stands in for an absolute path of the build machine outside the command root and home folder."""

SEGMENT = r"""[^\s/\\:*?"'<>|`,;()\[\]{}=]"""
ABSOLUTE_PATH = re.compile(
    r"(?<![\w.~/\\:<])(?:[A-Za-z]:[/\\]|\\\\|/)"  # POSIX root, drive letter or UNC prefix
    rf"(?:{SEGMENT}+[/\\])*{SEGMENT}+"
)

MINIMAL_ENVIRONMENT = (
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC",  # find and start programs
    "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",  # per-user tool settings and caches
    "TMPDIR", "TEMP", "TMP",  # temporary folders
    "LANG", "LC_ALL",  # text encoding
)
"""The only environment variables a command inherits; capabilities/command-fences owns the list."""


class CommandError(ValueError):
    """Raised when derived command content cannot be produced."""


def run_command(command: str, cwd: Path, timeout_seconds: int) -> str:
    if not command.strip():
        raise CommandError("A command fence cannot be empty.")
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env={name: value for name, value in os.environ.items()
                 if name.upper() in MINIMAL_ENVIRONMENT},
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
    output = redact_local_paths(completed.stdout, cwd)
    if completed.returncode != 0:
        detail = f"\n{output.strip()}" if output.strip() else ""
        raise CommandError(f"Command exited with code {completed.returncode}: {command}{detail}")
    check_captured(output, cwd)
    return output


def check_captured(text: str, root: Path) -> None:
    """Fail when captured output still names the command root or the home folder.

    The replacement above makes this hold; a hit is an obs defect, not an authoring error.
    """
    flags = re.IGNORECASE if os.name == "nt" else 0
    home = Path.home()
    folders = [("command root", root), *([("home folder", home)] if home.parent != home else [])]
    for label, folder in folders:
        if any(re.search(re.escape(spelling) + rf"(?!{SEGMENT})", text, flags)
               for spelling in path_spellings(folder)):
            raise CommandError(f"its captured output still names the build machine's {label}; "
                               "this is an obs defect to report")


def redact_local_paths(text: str, root: Path) -> str:
    """Replace the build machine's absolute paths in command output.

    Paths inside the command root become relative to it, the home folder becomes ``~`` and every
    other absolute path becomes LOCAL_PATH; capabilities/command-fences owns the rule.
    """
    flags = re.IGNORECASE if os.name == "nt" else 0
    end = rf"(?!{SEGMENT})"
    for folder in path_spellings(root):
        text = re.sub(rf"{re.escape(folder)}(?:[/\\](?={SEGMENT})|{end})",
                      lambda match: "" if match[0][-1:] in "/\\" else ".", text, flags=flags)
    home = Path.home()
    if home.parent != home:
        for folder in path_spellings(home):
            text = re.sub(rf"{re.escape(folder)}(?=[/\\]|{end})", "~", text, flags=flags)
    return ABSOLUTE_PATH.sub(LOCAL_PATH, text)


def path_spellings(folder: Path) -> list[str]:
    """The folder as written and resolved, with native and forward slashes, longest first."""
    paths = {folder.absolute(), folder.resolve()}
    spellings = {spelling for path in paths for spelling in (str(path), path.as_posix())}
    return sorted(spellings, key=len, reverse=True)
