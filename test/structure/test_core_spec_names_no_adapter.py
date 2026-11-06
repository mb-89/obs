"""obs's specification makes no statement about an adapter.

Reader: whoever changes obs's specification or this list.

obs treats an adapter's specification as an outside source: one reference note under
`spec/appendix/references` stands for it, and everything about an adapter's output lives in that
adapter's own specification (the HTML adapter's: `adapters/html/spec/manifest.md`). This test
owns the terms that name the HTML adapter or its user interface, and the one list of allowed
exceptions.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
SPEC = ROOT / "spec"
# The reference notes stand for outside sources and may name them.
REFERENCES = SPEC / "appendix" / "references"

# Names of the HTML adapter, its namespace and its packages, and terms of its user interface.
TERMS = re.compile(
    r"obs-html|obsHtml|obs_html|artifact-ui|artifact UI|SharePoint|Plotly|hover card|floating window"
    r"|dock menu|notice center|reading shell",
    re.IGNORECASE,
)
# An output format, matched in its exact case so paths such as `adapters/html` stay allowed.
FORMATS = re.compile(r"\bHTML\b")

# (note, line text) pairs allowed to name a term, each with its reason.
ALLOWED = {
    # The spec's own presentation choice for whichever adapter renders it: authored input in the
    # adapter's namespace, which the core neither reads nor describes.
    ("spec/manifest.md", "obsHtml:"),
    # The core suite's browser variable, a name in the core's tests (test/browser_pool.py).
    ("spec/design_input/quality.md", "- The browser tier needs `OBS_HTML_TEST_NATIVE_BROWSER`"),
    # HTML as input: what authors and imported sources may write, which the core reads or refuses.
    # No output format is named.
    ("spec/design_input/input-model.md",
     "HTML-style Markdown authoring comments (`<!-- ... -->`), including multiline comments,"),
    ("spec/design_input/input-model.md",
     "links and table structure, including supported entity-escaped HTML. Use the existing"),
    ("spec/design_input/input-model.md",
     "safe content-rendering boundary; never enable arbitrary source HTML or execute"),
    ("spec/design_input/input-model.md",
     "as HTML. Unsupported or malformed content remains safely readable without silently"),
    ("spec/design_input/input-model.md",
     "not silently discarded prose. This is artifact layout syntax, not source-authored HTML"),
    ("spec/design_input/input-model.md",
     "files use octet-stream, never an executable HTML/script media type. This keeps supplied"),
    ("spec/design_input/input-model.md",
     "attachment links are allowed; this does not enable raw HTML or HTML/script data URLs."),
}


def core_notes() -> list[Path]:
    return sorted(path for path in SPEC.rglob("*.md")
                  if "design_output" not in path.parts and not path.is_relative_to(REFERENCES))


def adapter_statements() -> list[str]:
    found = []
    for path in core_notes():
        relative = path.relative_to(ROOT).as_posix()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in [*TERMS.finditer(line), *FORMATS.finditer(line)]:
                if (relative, line.strip()) in ALLOWED:
                    continue
                found.append(
                    f"{relative}:{number}: names '{match.group(0)}'. Remedy: move the passage to the "
                    "adapter's specification (adapters/html/spec) or state it for any adapter; "
                    "test/structure/test_core_spec_names_no_adapter.py ALLOWED lists the exceptions."
                )
    return found


def test_core_spec_names_no_adapter_outside_its_references() -> None:
    assert adapter_statements() == []


def test_every_allowed_exception_is_still_needed() -> None:
    lines = {(path.relative_to(ROOT).as_posix(), line.strip())
             for path in core_notes() for line in path.read_text(encoding="utf-8").splitlines()}
    assert sorted(ALLOWED - lines) == []


WIDTH_CLASSIFICATION = re.compile(r"widths?\b[^.]*session-only|session-only[^.]*\bwidths?\b", re.IGNORECASE)


def test_no_core_note_classifies_resized_widths() -> None:
    classifying = [path.relative_to(ROOT).as_posix() for path in core_notes()
                   if WIDTH_CLASSIFICATION.search(" ".join(path.read_text(encoding="utf-8").split()))]
    assert classifying == [], (
        f"{classifying}: the HTML adapter's artifact-ui note (What counts as a change) classifies widths")
