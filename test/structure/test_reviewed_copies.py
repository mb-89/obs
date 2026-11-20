"""Reviewed copies are split by owner: obs's spec keeps the property-editor input contract, which
sources the property-editors capability; the saved copy, its review state and its runtime are the
adapter's specification's."""
from pathlib import Path

ROOT = Path(__file__).parents[2]


def _section() -> str:
    model = (ROOT / "spec" / "design_input" / "input-model.md").read_text(encoding="utf-8")
    return " ".join(model.split("\n## Reviewed copy\n", 1)[1].split("\n## ", 1)[0].split())


def test_the_input_model_keeps_the_property_editor_contract_only() -> None:
    section = _section()

    for core in ("A `property-editor` fence contains `version: 1`, `field`, and `label`",
                 "[[capabilities/property-editors#Projection rules]]",
                 "Generated Home and presentation-semantic properties are not editable"):
        assert core in section
    for adapter in ("`obs-comments`", "File System Access", "Comments bar", "Filter bar",
                    "Comment extraction"):
        assert adapter not in section, f"input-model.md, Reviewed copy: move '{adapter}' to the adapter's specification"


def test_the_reviewed_copies_note_points_to_the_references() -> None:
    body = (ROOT / "spec" / "capabilities" / "reviewed-copies.md").read_text(encoding="utf-8").split("---", 2)[2]

    assert "[[capabilities/property-editors]]" in body
    assert "[[appendix/references|References]]" in body
