import json
from pathlib import Path

from jsonschema import validate


ROOT = Path(__file__).parents[1]


def document_fixture(capabilities: list[str] | None = None) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "manifest": {"title": "Fixture", "metadata": {"kind": "report"}},
        "chapters": [{
            "id": "chapter",
            "title": "Chapter",
            "content": [{"type": "paragraph", "text": "Content."}],
            "children": [],
        }],
        "links": [{"id": "reference", "href": "https://example.test/reference", "label": "Reference"}],
        "assets": [{"id": "asset", "href": "assets/figure.svg", "mediaType": "image/svg+xml"}],
        "records": [{"id": "record", "type": "finding", "fields": {"status": "open"}}],
        "diagnostics": [],
        "capabilities": capabilities or ["manifest"],
    }


def test_document_schema_validates_a_core_document() -> None:
    schema = json.loads((ROOT / "src" / "obs_html" / "document.schema.json").read_text(encoding="utf-8"))

    validate(document_fixture(), schema)
