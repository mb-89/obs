import json
from pathlib import Path

ROOT = Path(__file__).parents[2]


def _document_node() -> str:
    note = (ROOT / "spec" / "capabilities" / "registers.md").read_text(encoding="utf-8")
    return note.split("## Document node", 1)[1].split("\n## ", 1)[0]


def test_document_node_names_every_record_type_and_points_to_the_schema_that_defines_them() -> None:
    schema = json.loads((ROOT / "src" / "obs" / "document.schema.json").read_text(encoding="utf-8"))
    types = schema["$defs"]["record"]["properties"]["type"]["enum"]
    section = _document_node()

    assert types[0] == "note"
    assert all(f"`{kind}`" in section for kind in types)
    assert "`src/obs/document.schema.json` (`$defs/record`) defines each record type" in section


def test_document_node_rows_are_never_null() -> None:
    assert "null` for a view" not in _document_node()
    assert "the ids of the records the view" in _document_node()
