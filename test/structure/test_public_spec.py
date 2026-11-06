"""The public spec names no private work context.

This file is the one place that lists the denied terms; nothing else repeats them. It spans every
authored file under `spec/` (generated `spec/design_output` excluded), so it lives in its own file rather than in one note's structure test.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]

# Case-sensitive: the generic words ("catalog", "trace", "node") stay allowed.
DENIED = (
    "quack_v5",
    "Node artifact",
    "Node edition",
    "Node side-by-side",
    "Leaves artifact",
    "node-flatness",
    "25 open points",
    "machine-specific knowledge-base links",
    "Catalog",
    "Trace matrix",
    "Trace Graph",
    "Trace levels",
    "REFERENCE_EXAMPLE_SNAPSHOT",
    "arbitrary corporate site",
    "old tracing artifact",
    "leaves.html",
    "32eae7f",
    "sharepoint_diagnostic",
    "Tenant probe",
    "User screenshots",
)


def test_spec_names_no_denied_term() -> None:
    # Whitespace is flattened so a term wrapped across lines is still found.
    pattern = re.compile("|".join(rf"(?<![\w-]){re.escape(term)}(?![\w-])" for term in DENIED))
    found = [
        f"{path.relative_to(ROOT).as_posix()}: {match.group(0)}"
        for path in sorted((ROOT / "spec").rglob("*"))
        if path.is_file() and "design_output" not in path.parts
        for match in pattern.finditer(" ".join(path.read_text(encoding="utf-8").split()))
    ]
    assert not found, "spec/ names private work context; rewrite it generically:\n" + "\n".join(found)
