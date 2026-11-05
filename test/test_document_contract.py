import json
import subprocess
import sys
from pathlib import Path

from jsonschema import validate
import pytest

from obs_html.adapter import load_adapter
from obs_html.document import AdapterError, call_adapter, write_document

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


def test_core_writes_document_and_calls_adapter(tmp_path) -> None:
    document = tmp_path / "document.json"
    write_document(document_fixture(), document)
    manifest = tmp_path / "adapter.json"
    manifest.write_text(json.dumps({
        "name": "fixture",
        "command": [sys.executable, "-c", "from pathlib import Path; Path(__import__('sys').argv[2]).write_text('ok')"],
        "contractVersion": 1,
        "capabilities": ["manifest"],
    }), encoding="utf-8")
    configuration = tmp_path / "adapters.json"
    configuration.write_text(json.dumps({"adapters": {"fixture": "adapter.json"}}), encoding="utf-8")
    destination = tmp_path / "output.txt"

    call_adapter("fixture", configuration, document, destination)

    assert destination.read_text(encoding="utf-8") == "ok"


@pytest.mark.parametrize(
    ("contract_version", "capabilities", "message"),
    [(2, ["manifest"], "contract version 2 does not match Document schema version 1"),
     (1, [], "does not support Document capabilities: manifest")],
)
def test_core_rejects_mismatched_adapter_contracts(
        tmp_path, contract_version, capabilities, message) -> None:
    document = tmp_path / "document.json"
    write_document(document_fixture(), document)
    manifest = tmp_path / "adapter.json"
    manifest.write_text(json.dumps({
        "name": "fixture",
        "command": [sys.executable, "-c", "pass"],
        "contractVersion": contract_version,
        "capabilities": capabilities,
    }), encoding="utf-8")
    configuration = tmp_path / "adapters.json"
    configuration.write_text(json.dumps({"adapters": {"fixture": "adapter.json"}}), encoding="utf-8")

    with pytest.raises(AdapterError, match=message):
        call_adapter("fixture", configuration, document, tmp_path / "output.txt")


def test_node_adapter_receives_the_document_and_writes_output(tmp_path) -> None:
    document = tmp_path / "document.json"
    write_document(document_fixture(), document)
    manifest = tmp_path / "adapter.json"
    fixture = ROOT / "test" / "fixtures" / "document-adapter.js"
    manifest.write_text(json.dumps({
        "name": "node-fixture",
        "command": ["node", str(fixture)],
        "contractVersion": 1,
        "capabilities": ["manifest"],
    }), encoding="utf-8")
    configuration = tmp_path / "adapters.json"
    configuration.write_text(json.dumps({"adapters": {"node-fixture": "adapter.json"}}), encoding="utf-8")
    destination = tmp_path / "output.json"

    call_adapter("node-fixture", configuration, document, destination)

    assert json.loads(destination.read_text(encoding="utf-8")) == {
        "schemaVersion": 1,
        "capabilities": ["manifest"],
    }


def test_document_core_import_has_no_renderer_or_browser_dependencies() -> None:
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; import obs_html.document; "
         "print(','.join(name for name in sys.modules if name.startswith('obs_html.')))"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert set(result.stdout.strip().split(",")) == {
        "obs_html.document",
        "obs_html.adapter",
    }
