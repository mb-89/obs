"""Write the core's output files; see architecture, Safety boundaries.

An output is replaced atomically: the new text goes to a temporary file in the same folder, which
then replaces the output, so a reader never sees a partial file, even while another build of the
same vault writes it. An output whose content is unchanged stays untouched.
"""
from __future__ import annotations

import tempfile
from pathlib import Path


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
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
