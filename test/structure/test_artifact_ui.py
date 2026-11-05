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
