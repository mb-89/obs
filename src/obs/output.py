"""Write the core's output files; see architecture, Safety boundaries.

An output is replaced atomically: the new text goes to a temporary file in the same folder, which
then replaces the output, so a reader never sees a partial file, even while another build of the
same vault writes it. An output whose content is unchanged stays untouched.
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")


SHARING_REFUSED = os.name == "nt"
"""Whether the system refuses to replace a file another handle holds open, and to open a file being
replaced: Windows does, so there the core tries again (architecture, Safety boundaries)."""
ATTEMPTS = 200
"""How often a refused replacement or read is tried before its refusal fails the call."""
PAUSE_SECONDS = 0.01
"""The pause between two attempts; with ATTEMPTS, a holder gets about two seconds."""


def pause() -> None:
    """The wait between two attempts: this module's clock door, which the tests replace by one that
    only yields the thread (quality.md, Testing boundaries)."""
    time.sleep(PAUSE_SECONDS)


def _retried(action: Callable[[], T]) -> T:
    """``action``'s result, tried again after a pause while the system refuses it for a handle another
    reader or writer holds (SHARING_REFUSED); elsewhere, and after the last attempt, the refusal fails."""
    for attempt in range(ATTEMPTS):
        try:
            return action()
        except PermissionError:
            if not SHARING_REFUSED or attempt == ATTEMPTS - 1:
                raise
            pause()
    raise AssertionError("ATTEMPTS is at least 1")


def replace_file(source: Path, target: Path) -> None:
    """``os.replace``, tried again while a reader holds ``target`` open (SHARING_REFUSED)."""
    _retried(lambda: os.replace(source, target))


def read_file(path: Path) -> bytes:
    """``path``'s bytes, tried again while a writer is replacing it (SHARING_REFUSED)."""
    return _retried(path.read_bytes)


def write_output(path: Path, text: str) -> None:
    data = text.encode("utf-8")
    try:
        if path.read_bytes() == data:
            return
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            handle.write(data)
            temporary = Path(handle.name)
        replace_file(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
