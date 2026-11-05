from pathlib import Path

ROOT = Path(__file__).parents[2]


def _grammar() -> str:
    note = (ROOT / "spec" / "design_input" / "generic-tables.md").read_text(encoding="utf-8")
    return note.split("### Bases filter grammar", 1)[1].split("\n### ", 1)[0]


def test_the_grammar_says_the_core_emits_every_projection_and_points_to_their_definition() -> None:
    grammar = _grammar()

    assert "exist only in the browser" not in grammar
    assert "The core emits every projection as records of its type" in grammar
    assert "`src/obs/document.schema.json` (`$defs/record`)" in grammar
