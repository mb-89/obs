"""Producer commands that run the same under ``cmd`` and ``/bin/sh``.

A ``cmd`` fence runs through the platform shell, whose builtins (``copy``, ``echo``) and line
endings differ. Tests that need a real producer let the test interpreter do the work instead.
``code`` must not contain double quotes or shell metacharacters such as ``$``, ``%`` or ``!``.
"""

from __future__ import annotations

import sys


def python_command(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'
