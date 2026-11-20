"""Cover metadata is split by owner: obs's spec states what the core reads, validates and emits;
how an adapter presents the cover and History is that adapter's specification's."""
from pathlib import Path

ROOT = Path(__file__).parents[2]


def _section() -> str:
    model = (ROOT / "spec" / "design_input" / "input-model.md").read_text(encoding="utf-8")
    return " ".join(model.split("\n## Cover metadata and history\n", 1)[1].split("\n## ", 1)[0].split())


def test_the_input_model_keeps_the_fields_their_validation_and_records() -> None:
    section = _section()

    for core in ("`document type`", "`src/obs/cover-metadata.schema.json`", "`documentHistory`",
                 "Unknown history fields, duplicate version labels"):
        assert core in section
    for presentation in ("These values populate the cover", "displayed on the cover and page frame",
                         "In document view it occupies its own section", "appear in History, not on the cover",
                         "views render the same canonical history"):
        assert presentation not in section, (
            f"input-model.md, Cover metadata and history: move '{presentation}' to the adapter's specification")


def test_the_cover_metadata_note_states_the_core_part_and_points_to_the_references() -> None:
    body = (ROOT / "spec" / "capabilities" / "cover-metadata.md").read_text(encoding="utf-8").split("---", 2)[2]

    assert "[[input-model#Cover metadata and history]]" in body
    assert "`documentMetadata`" in body and "`documentHistory`" in body
    assert "[[appendix/references|References]]" in body
