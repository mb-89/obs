from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_conditions_state_once_that_empty_conditions_select_every_selectable_note() -> None:
    note = (ROOT / "spec" / "capabilities" / "queries.md").read_text(encoding="utf-8")
    section = note.split("## Conditions", 1)[1].split("\n## ", 1)[0]

    assert note.count("selects every selectable note") == 1
    assert "selects every selectable note" in section
    assert "[[input-model#Chapter content]]" in section
    assert "validates" in section.split("selects every selectable note", 1)[1].split("\n\n", 1)[0]
