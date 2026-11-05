import json
from pathlib import Path

from jsonschema import validate

from obs_html.adapter import load_adapter

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


def test_adapter_is_discovered_by_name_from_configuration(tmp_path) -> None:
    manifest = tmp_path / "adapter.json"
    manifest.write_text(json.dumps({
        "name": "fixture",
        "command": ["node", "adapter.js"],
        "contractVersion": 1,
        "capabilities": ["manifest"],
    }), encoding="utf-8")
    configuration = tmp_path / "adapters.json"
    configuration.write_text(json.dumps({"adapters": {"fixture": "adapter.json"}}), encoding="utf-8")

    assert load_adapter("fixture", configuration) == {
        "name": "fixture",
        "command": ["node", "adapter.js"],
        "contractVersion": 1,
        "capabilities": ["manifest"],
    }
