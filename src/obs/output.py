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


def replace_file(source: Path, target: Path, attempts: int = 200) -> None:
    """``os.replace``, retried while Windows refuses it because a reader has ``target`` open."""
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if os.name != "nt" or attempt == attempts - 1:
                raise
            time.sleep(0.01)


def read_file(path: Path, attempts: int = 200) -> bytes:
    """``path``'s bytes, retried while Windows refuses the read because a writer is replacing it."""
    for attempt in range(attempts):
        try:
            return path.read_bytes()
        except PermissionError:
            if os.name != "nt" or attempt == attempts - 1:
                raise
            time.sleep(0.01)
    raise AssertionError("unreachable")


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
