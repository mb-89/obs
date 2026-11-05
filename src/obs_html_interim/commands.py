from __future__ import annotations

import subprocess
from pathlib import Path

from obs_html_interim.timings import stage


class CommandError(ValueError):
    """Raised when derived command content cannot be produced."""


@stage("commands")
def run_command(command: str, cwd: Path, timeout_seconds: int) -> str:
    if not command.strip():
        raise CommandError("A cmd fence cannot be empty.")
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
    return completed.stdout
