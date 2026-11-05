import json
from pathlib import Path

from structure.naming import says_document_presentation

ROOT = Path(__file__).parents[2]


def test_config_references_existing_json_schema() -> None:
    config_path = ROOT / "src" / "obs_html" / "cfg.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    schema_path = config_path.parent / config["$schema"]

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_no_heading_or_link_says_document_presentation() -> None:
    assert says_document_presentation("spec/design_input/configuration.md") == []
