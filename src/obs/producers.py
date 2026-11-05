"""Run authorized silent command producers before a vault is converted."""
from __future__ import annotations

import subprocess
from pathlib import Path

from markdown_it import MarkdownIt

from obs.input import InputError, validate_command


class ProducerError(ValueError):
    """Raised when an authorized producer cannot create its vault files."""


def run_producers(vault_root: Path, authorized: bool, timeout_seconds: int) -> int:
    """Run every ``cmd silent`` fence in deterministic vault and source order."""
    if not authorized:
        return 0
    vault_root = vault_root.resolve()
    producers = []
    for path in sorted(vault_root.rglob("*.md"), key=lambda item: item.relative_to(vault_root).as_posix()):
        if any(part.startswith(".") for part in path.relative_to(vault_root).parts) or not path.is_file():
            continue
        try:
            tokens = MarkdownIt().parse(path.read_text(encoding="utf-8-sig"))
        except OSError as error:
            raise ProducerError(f"Cannot read producer source {path}: {error}") from error
        for token in tokens:
            if token.type != "fence" or token.info.strip().split() != ["cmd", "silent"]:
                continue
            line = token.map[0] + 1 if token.map else 1
            producers.append((path, line, token.content.strip()))
    for path, line, command in producers:
        _run(command, vault_root, timeout_seconds, path.relative_to(vault_root), line)
    return len(producers)


def _run(command: str, cwd: Path, timeout_seconds: int, source: Path, line: int) -> None:
    try:
        validate_command(command)
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
    except InputError as error:
        raise ProducerError(f"{source}:{line}: {error}") from error
    except subprocess.TimeoutExpired as error:
        raise ProducerError(
            f"{source}:{line}: Command exceeded the {timeout_seconds}-second timeout: {command}"
        ) from error
    if completed.returncode != 0:
        output = completed.stdout.strip()
        detail = f"\n{output}" if output else ""
        raise ProducerError(
            f"{source}:{line}: Command exited with code {completed.returncode}: {command}{detail}"
        )
