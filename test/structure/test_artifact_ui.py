import re
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_artifact_ui_alone_owns_what_counts_as_a_change() -> None:
    design = ROOT / "spec" / "design_input"
    artifact_ui = (design / "artifact-ui.md").read_text(encoding="utf-8")
    input_model = (design / "input-model.md").read_text(encoding="utf-8")
    rule = artifact_ui.split("## What counts as a change", 1)[1].split("\n## ", 1)[0]

    for reader_state in ("filters", "view selections", "table columns", "sorting", "open or closed panels"):
        assert reader_state in rule
    assert "Reader state is never a change" in rule
    assert "persisted reader-state changes all participate" not in artifact_ui
    assert "[[artifact-ui#What counts as a change" in input_model
    for restatement in ("Persisted reader-state changes do", "changed-HTML state", "as changed.", "or an artifact change"):
        assert restatement not in input_model


def test_width_rule_has_one_owner() -> None:
    design = ROOT / "spec" / "design_input"
    input_model = (design / "input-model.md").read_text(encoding="utf-8")

    assert "column or width changes" not in input_model

    generic_tables = (design / "generic-tables.md").read_text(encoding="utf-8")
    assert "never mark the" not in generic_tables
    assert "never show the change notice" not in generic_tables
    assert "[[artifact-ui#What counts as a change" in generic_tables


WIDTH_CLASSIFICATION = re.compile(r"widths?\b[^.]*session-only|session-only[^.]*\bwidths?\b", re.IGNORECASE)


def test_exactly_one_note_classifies_resized_widths() -> None:
    notes = sorted(path for path in (ROOT / "spec").rglob("*.md") if "design_output" not in path.parts)
    classifying = [path.relative_to(ROOT).as_posix() for path in notes
                   if WIDTH_CLASSIFICATION.search(" ".join(path.read_text(encoding="utf-8").split()))]
    assert classifying == ["spec/design_input/artifact-ui.md"], (
        f"{classifying}: state the width classification only in artifact-ui#What counts as a change "
        "and link [[artifact-ui#What counts as a change]] elsewhere"
    )

    design = ROOT / "spec" / "design_input"
    artifact_ui = (design / "artifact-ui.md").read_text(encoding="utf-8")
    rule = artifact_ui.split("## What counts as a change", 1)[1].split("\n## ", 1)[0]
    assert "table columns and their widths" not in rule
    flat = " ".join(artifact_ui.split())
    assert flat.count("session-only view state") == 1
    assert "resized widths are session-only" not in flat
    assert " a artifact" not in flat
    assert "session-only view state" in " ".join(rule.split())
    for note in ("input-model.md", "generic-tables.md"):
        assert "[[artifact-ui#What counts as a change" in (design / note).read_text(encoding="utf-8")
