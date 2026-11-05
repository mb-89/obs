import json
import subprocess
import sys
from pathlib import Path

from jsonschema import validate
import pytest

from obs.adapter import AdapterError, load_adapter
from obs.capabilities import build_capability_reference
from obs.document import call_adapter, main, write_document

ROOT = Path(__file__).parents[1]


def capability_reference() -> dict[str, object]:
    return build_capability_reference(ROOT / "spec" / "capabilities", ROOT / "spec" / "capabilities" / "coverage.json")


def write_reference(path: Path) -> Path:
    path.write_text(json.dumps(capability_reference()), encoding="utf-8")
    return path


def document_fixture(capabilities: list[str] | None = None) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "manifest": {"title": "Fixture", "metadata": {"kind": "report"}},
        "chapters": [{
            "id": "chapter",
            "title": "Chapter",
            "content": [{"type": "paragraph", "attrs": {}, "children": [{"type": "text", "attrs": {}, "children": [], "text": "Content."}]}],
            "children": [],
        }],
        "links": [{"id": "reference", "href": "https://example.test/reference", "label": "Reference"}],
        "assets": [{"id": "asset", "href": "assets/figure.svg", "mediaType": "image/svg+xml"}],
        "records": [{"id": "record", "type": "finding", "fields": {"status": "open"}}],
        "semanticResources": [{"id": "resource", "type": "finding", "attrs": {}}],
        "diagnostics": [],
        "capabilities": capabilities or ["manifest"],
    }


def test_document_schema_validates_a_core_document() -> None:
    schema = json.loads((ROOT / "src" / "obs" / "document.schema.json").read_text(encoding="utf-8"))

    validate(document_fixture(), schema)


def test_document_cli_writes_a_vault_document(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text("Content.\n", encoding="utf-8")
    reference = write_reference(tmp_path / "capabilities.json")
    output = tmp_path / "document.json"

    assert main([
        "--source", str(vault / "manifest.md"),
        "--document", str(output),
        "--capability-reference", str(reference),
    ]) == 0

    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["chapters"][0]["content"][0]["children"][0]["text"] == "Content."


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
    reference = write_reference(tmp_path / "capabilities.json")
    write_document(document_fixture(), document, capability_reference())
    manifest = tmp_path / "adapter.json"
    manifest.write_text(json.dumps({
        "name": "fixture",
        "command": [sys.executable, "-c", "from pathlib import Path; Path(__import__('sys').argv[2]).write_text('ok')"],
        "contractVersion": 1,
        "capabilities": [item["id"] for item in capability_reference()["capabilities"]],
    }), encoding="utf-8")
    configuration = tmp_path / "adapters.json"
    configuration.write_text(json.dumps({"adapters": {"fixture": "adapter.json"}}), encoding="utf-8")
    destination = tmp_path / "output.txt"

    assert main([
        "--document", str(document),
        "--adapter", "fixture",
        "--adapter-config", str(configuration),
        "--capability-reference", str(reference),
        "--destination", str(destination),
    ]) == 0

    assert destination.read_text(encoding="utf-8") == "ok"


@pytest.mark.parametrize(
    ("contract_version", "capabilities", "message"),
    [(2, ["manifest"], "contract version 2 does not match Document schema version 1"),
     (1, [], "does not support Document capabilities: manifest")],
)
def test_core_rejects_mismatched_adapter_contracts(
        tmp_path, contract_version, capabilities, message) -> None:
    document = tmp_path / "document.json"
    reference = write_reference(tmp_path / "capabilities.json")
    write_document(document_fixture(), document, capability_reference())
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
        call_adapter("fixture", configuration, document, tmp_path / "output.txt", reference)


def test_node_adapter_receives_the_document_and_writes_output(tmp_path) -> None:
    document = tmp_path / "document.json"
    reference = write_reference(tmp_path / "capabilities.json")
    write_document(document_fixture(), document, capability_reference())
    manifest = tmp_path / "adapter.json"
    fixture = ROOT / "test" / "fixtures" / "document-adapter.js"
    manifest.write_text(json.dumps({
        "name": "node-fixture",
        "command": ["node", str(fixture)],
        "contractVersion": 1,
        "capabilities": [item["id"] for item in capability_reference()["capabilities"]],
    }), encoding="utf-8")
    configuration = tmp_path / "adapters.json"
    configuration.write_text(json.dumps({"adapters": {"node-fixture": "adapter.json"}}), encoding="utf-8")
    destination = tmp_path / "output.json"

    call_adapter("node-fixture", configuration, document, destination, reference)

    assert json.loads(destination.read_text(encoding="utf-8")) == {
        "schemaVersion": 1,
        "capabilities": ["manifest"],
    }


def test_document_core_import_has_no_renderer_or_browser_dependencies() -> None:
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; import obs; "
         "print(','.join(name for name in sys.modules if name.startswith('obs_html')))"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == ""


def test_document_accepts_one_node_for_each_input_capability(tmp_path) -> None:
    reference = capability_reference()
    document = document_fixture([item["id"] for item in reference["capabilities"]])
    document["chapters"][0]["content"] = [
        {"type": item["id"], "attrs": {}, "children": [], "text": item["id"]}
        for item in reference["capabilities"]
    ]

    write_document(document, tmp_path / "document.json", reference)


def test_document_rejects_unknown_capability_and_requires_dependency_closure(tmp_path) -> None:
    reference = capability_reference()
    document = tmp_path / "document.json"
    unknown = document_fixture(["unknown"])
    with pytest.raises(Exception, match="unknown capabilities"):
        write_document(unknown, document, reference)
    dependent = next(item for item in reference["capabilities"] if item["dependsOn"])
    document_data = document_fixture([dependent["id"]])
    write_document(document_data, document, reference)
    reference_path = write_reference(tmp_path / "capabilities.json")
    manifest = tmp_path / "adapter.json"
    manifest.write_text(json.dumps({
        "name": "fixture", "command": [sys.executable, "-c", "pass"],
        "contractVersion": 1, "capabilities": [dependent["id"]],
    }), encoding="utf-8")
    configuration = tmp_path / "adapters.json"
    configuration.write_text(json.dumps({"adapters": {"fixture": "adapter.json"}}), encoding="utf-8")

    with pytest.raises(AdapterError, match="does not support Document capabilities"):
        call_adapter("fixture", configuration, document, tmp_path / "output.txt", reference_path)
