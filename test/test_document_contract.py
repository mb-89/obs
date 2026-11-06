import json
import subprocess
import sys
from pathlib import Path

from jsonschema import ValidationError, validate
import pytest

from obs.adapter import AdapterError, load_adapter
from obs.capabilities import build_capability_reference
from obs.document import DocumentError, call_adapter, main, write_document
from obs.vault import build_document

ROOT = Path(__file__).parents[1]


def capability_reference() -> dict[str, object]:
    return build_capability_reference(ROOT / "spec" / "capabilities", ROOT / "spec" / "capabilities" / "coverage.json")


def write_reference(path: Path) -> Path:
    path.write_text(json.dumps(capability_reference()), encoding="utf-8")
    return path


def document_fixture(capabilities: list[str] | None = None) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "manifest": {"title": "Fixture", "path": "manifest.md", "metadata": {"kind": "artifact"}},
        "chapters": [{
            "id": "chapter",
            "title": "Chapter",
            "content": [{"type": "paragraph", "attrs": {}, "children": [{"type": "text", "attrs": {}, "children": [], "text": "Content."}]}],
            "children": [],
        }],
        "links": [{"id": "reference", "href": "https://example.test/reference", "label": "Reference"}],
        "assets": [{"id": "asset", "href": "assets/figure.svg", "mediaType": "image/svg+xml"}],
        "records": [{"id": "record", "type": "note", "path": "record.md", "fields": {"status": "open"}, "fieldNodes": [
            {"type": "field", "attrs": {"name": "status"}, "children": [
                {"type": "text", "attrs": {}, "children": [], "text": "open"},
            ]},
        ]}],
        "semanticResources": [{"id": "resource", "type": "finding", "attrs": {}}],
        "diagnostics": [],
        "capabilities": capabilities or ["manifest"],
    }


def figure_descriptor() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "id": "comparison",
        "data": {"series": [{"id": "observed", "values": [2, 5, 3]}]},
        "panels": [{
            "id": "overview",
            "bounds": {"x": 0, "y": 0, "width": 720, "height": 320},
            "grid": {"row": 0, "column": 0, "rowSpan": 1, "columnSpan": 1},
            "axes": [{
                "id": "time",
                "scale": "linear",
                "limits": {"minimum": 0, "maximum": 2},
                "label": "Time",
            }],
        }],
        "provenance": {"command": ["generate-figure", "--input", "measurements.json"]},
    }


def capability_node_attrs(identifier: str) -> dict[str, object]:
    attrs = {
        "attachments": {"asset": "asset", "label": "Attachment"},
        "callouts": {"kind": "note", "title": ""},
        "cards-metrics": {"source": "", "spec": {}},
        "command-fences": {"source": "echo derived\n", "output": "derived\n"},
        "chapter-inclusion": {"id": "chapter"},
        "count-query": {"query": {}},
        "markdown-frontmatter": {"metadata": {}},
        "profiles": {"profile": {}},
        "quantities": {"metadata": {}},
        "queries": {"query": {}},
        "references": {"metadata": {}},
        "property-editors": {"source": "", "spec": {}, "writes": ["explanation"]},
        "registers": {
            "target": "register.base", "heading": "Open",
            "base": {"views": [{"type": "table", "name": "Open", "order": ["file.name"]}]},
            "view": 0, "rows": [["chapter"]],
        },
        "wikilinks": {"target": "chapter", "chapter": "chapter", "heading": "", "label": "chapter"},
        "embeds": {"target": "outside", "chapter": None},
        "figures": {"kind": "plot"},
    }
    return attrs.get(identifier, {})


def capability_node_children(identifier: str) -> list[dict[str, object]]:
    """A figure's one child is its kind's body; every other fixture node has none."""
    if identifier == "figures":
        return [{"type": "plot", "attrs": {"descriptor": figure_descriptor()}, "children": []}]
    return []


def test_document_schema_validates_a_core_document() -> None:
    schema = json.loads((ROOT / "src" / "obs" / "document.schema.json").read_text(encoding="utf-8"))

    validate(document_fixture(), schema)


@pytest.mark.parametrize("node", [
    {"type": "wikilinks", "attrs": {"target": "chapter", "heading": "", "label": "chapter"}},
    {"type": "embeds", "attrs": {"target": "chapter", "chapter": "Not An Id"}},
])
def test_document_schema_requires_a_resolved_chapter_on_note_links(node) -> None:
    schema = json.loads((ROOT / "src" / "obs" / "document.schema.json").read_text(encoding="utf-8"))
    document = document_fixture()
    document["chapters"][0]["content"] = [{**node, "children": []}]

    with pytest.raises(ValidationError, match="chapter|Not An Id"):
        validate(document, schema)


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
    assert document["chapters"][0]["content"][2]["children"][0]["text"] == "Content."


def test_the_manifest_carries_its_note_s_vault_relative_path(tmp_path) -> None:
    """An adapter's error about the manifest names its note, as one about a chapter names the chapter's."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "report.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text("Content.\n", encoding="utf-8")

    assert build_document(vault / "report.md")["manifest"]["path"] == "report.md"


def test_the_document_schema_requires_the_manifest_path() -> None:
    schema = json.loads((ROOT / "src" / "obs" / "document.schema.json").read_text(encoding="utf-8"))
    document = document_fixture()
    del document["manifest"]["path"]

    with pytest.raises(ValidationError) as failure:
        validate(document, schema)
    assert (list(failure.value.absolute_path), failure.value.validator) == (["manifest"], "required")


@pytest.mark.parametrize("block", [
    {"type": "registers", "attrs": capability_node_attrs("registers"), "children": []},
    {"type": "embeds", "attrs": {"target": "chapter", "chapter": "chapter"}, "children": []},
])
def test_document_refuses_a_block_node_inside_a_paragraph(tmp_path, block) -> None:
    document = document_fixture(["registers", "embeds"])
    paragraph = document["chapters"][0]["content"][0]
    paragraph["children"].append(block)

    with pytest.raises(DocumentError, match=r"chapters\[0\]\.content\[0\]\.children\[1\]: .*"
                                            r"\(capabilities/markdown#Document nodes\)"):
        write_document(document, tmp_path / "document.json", capability_reference())


def test_document_keeps_an_asset_embed_inside_a_paragraph(tmp_path) -> None:
    document = document_fixture(["embeds"])
    document["chapters"][0]["content"][0]["children"].append(
        {"type": "embeds", "attrs": {"target": "figure.svg", "chapter": None, "asset": "asset"}, "children": []},
    )

    write_document(document, tmp_path / "document.json", capability_reference())


def test_document_validates_figure_descriptor_at_the_plot_figure_s_body(tmp_path) -> None:
    document = document_fixture(["figures"])
    document["chapters"][0]["content"] = [{
        "type": "figures", "attrs": {"kind": "plot"}, "children": capability_node_children("figures"),
    }]

    write_document(document, tmp_path / "document.json", capability_reference())

    document["chapters"][0]["content"][0]["children"][0]["attrs"]["descriptor"]["panels"] = []
    with pytest.raises(DocumentError, match=r"figure body plot\.descriptor\.panels: .*figureBodies"):
        write_document(document, tmp_path / "invalid-document.json", capability_reference())


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
         "print(','.join(name for name in sys.modules if name.startswith('obs_html_interim')))"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == ""


def test_document_accepts_one_node_for_each_input_capability(tmp_path) -> None:
    reference = capability_reference()
    document = document_fixture([item["id"] for item in reference["capabilities"]])
    document["chapters"][0]["content"] = [
        {
            "type": item["id"],
            "attrs": capability_node_attrs(item["id"]),
            "children": capability_node_children(item["id"]),
            "text": item["id"],
        }
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


SPEC_MANIFEST = ROOT / "spec" / "manifest.md"
# A fixture adapter: writes its arguments and the Document's manifest path to DESTINATION.
RECORDING_ADAPTER = (
    "import json, sys; from pathlib import Path; document = json.loads(Path(sys.argv[1]).read_text("
    "encoding='utf-8')); Path(sys.argv[2]).write_text(json.dumps({'arguments': sys.argv[1:], "
    "'manifest': document['manifest']['path']}), encoding='utf-8')"
)


def recording_adapter(folder: Path, **declared: object) -> Path:
    """An adapters.json in ``folder`` registering the recording adapter ``fixture``."""
    (folder / "adapter.json").write_text(json.dumps({
        "name": "fixture", "command": [sys.executable, "-c", RECORDING_ADAPTER], "contractVersion": 1,
        "capabilities": [item["id"] for item in capability_reference()["capabilities"]], **declared,
    }), encoding="utf-8")
    configuration = folder / "adapters.json"
    configuration.write_text(json.dumps({"adapters": {"fixture": "adapter.json"}}), encoding="utf-8")
    return configuration


@pytest.fixture
def offline_spec_commands(monkeypatch):
    """The spec's cmd fences echo their command instead of starting it; its remote images are served."""
    from obs import vault

    monkeypatch.setattr(vault, "run_command", lambda command, cwd, timeout_seconds: f"{command}\n")
    monkeypatch.setattr(vault, "fetch_remote", lambda url: (b"<svg xmlns='http://www.w3.org/2000/svg'/>",
                                                             "image/svg+xml"))


def test_one_call_builds_the_spec_without_a_capability_reference_or_a_document(
        tmp_path, monkeypatch, offline_spec_commands) -> None:
    """The packaged capability reference and a temporary Document; adapters.json in the current folder."""
    recording_adapter(tmp_path)
    monkeypatch.chdir(tmp_path)
    destination = tmp_path / "spec.out"

    assert main(["--source", str(SPEC_MANIFEST), "--adapter", "fixture", "--destination", str(destination),
                 "--execute-commands"]) == 0

    called = json.loads(destination.read_text(encoding="utf-8"))
    assert called["manifest"] == "manifest.md"
    assert called["arguments"][1:] == [str(destination.resolve()), "--vault-root", str(SPEC_MANIFEST.parent)]
    assert not Path(called["arguments"][0]).exists(), "the temporary Document outlives the build"


def test_a_given_document_is_kept_and_the_vault_root_is_passed_as_given(tmp_path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text("Content.\n", encoding="utf-8")
    recording_adapter(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert main(["--source", "vault/manifest.md", "--document", "kept.json", "--adapter", "fixture",
                 "--destination", "out.json"]) == 0

    assert json.loads((tmp_path / "kept.json").read_text(encoding="utf-8"))["manifest"]["path"] == "manifest.md"
    assert json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))["arguments"] == [
        str((tmp_path / "kept.json").resolve()), str((tmp_path / "out.json").resolve()), "--vault-root", "vault"]


def test_an_adapter_called_on_a_document_gets_no_vault_root(tmp_path) -> None:
    document = tmp_path / "document.json"
    write_document(document_fixture(), document, capability_reference())
    configuration = recording_adapter(tmp_path)

    assert main(["--document", str(document), "--adapter", "fixture", "--adapter-config", str(configuration),
                 "--destination", str(tmp_path / "out.json")]) == 0

    assert json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))["arguments"] == [
        str(document.resolve()), str((tmp_path / "out.json").resolve())]


@pytest.mark.parametrize(("value", "passed"), [("true", ["--flag"]), ("false", [])])
def test_a_declared_adapter_option_is_passed_as_the_adapter_declares_it(tmp_path, value, passed) -> None:
    document = tmp_path / "document.json"
    write_document(document_fixture(), document, capability_reference())
    configuration = recording_adapter(tmp_path, options={"flag": {"type": "boolean", "summary": "A flag."}})

    assert main(["--document", str(document), "--adapter", "fixture", "--adapter-config", str(configuration),
                 "--destination", str(tmp_path / "out.json"), "--adapter-option", f"flag={value}"]) == 0

    assert json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))["arguments"][2:] == passed


@pytest.mark.parametrize("option", ["other=true", "flag", "flag=yes"])
def test_an_adapter_option_the_adapter_does_not_declare_names_the_adapter_and_its_options(
        tmp_path, option) -> None:
    document = tmp_path / "document.json"
    write_document(document_fixture(), document, capability_reference())
    configuration = recording_adapter(tmp_path, options={"flag": {"type": "boolean", "summary": "A flag."}})

    with pytest.raises(SystemExit) as failure:
        main(["--document", str(document), "--adapter", "fixture", "--adapter-config", str(configuration),
              "--destination", str(tmp_path / "out.json"), "--adapter-option", option])

    message = str(failure.value.code)
    assert "--adapter-option" in message and str(tmp_path / "adapter.json") in message and "flag" in message
    assert not (tmp_path / "out.json").exists()


def test_a_document_is_required_without_an_adapter(tmp_path) -> None:
    (tmp_path / "manifest.md").write_text("Text.\n", encoding="utf-8")

    with pytest.raises(SystemExit) as failure:
        main(["--source", str(tmp_path / "manifest.md")])

    assert "--document" in str(failure.value.code)


def test_document_and_capability_reference_writers_replace_their_output_atomically(tmp_path) -> None:
    """architecture, Safety boundaries: output is replaced atomically, and an unchanged output
    stays untouched; two builds of one vault (a producer and its reader) never see a partial file."""
    from obs.capabilities import main as capabilities_main

    reference = capability_reference()
    document = tmp_path / "document.json"
    capabilities = tmp_path / "capabilities.json"
    write_document(document_fixture(), document, reference)
    capabilities_main(["--notes", str(ROOT / "spec" / "capabilities"), "--output", str(capabilities)])
    written = {path: path.stat() for path in (document, capabilities)}

    write_document(document_fixture(), document, reference)
    capabilities_main(["--notes", str(ROOT / "spec" / "capabilities"), "--output", str(capabilities)])
    for path, before in written.items():
        assert path.stat().st_mtime_ns == before.st_mtime_ns, f"{path.name}: unchanged output was rewritten"

    changed = document_fixture()
    changed["manifest"]["title"] = "Changed"
    write_document(changed, document, reference)
    assert json.loads(document.read_text(encoding="utf-8"))["manifest"]["title"] == "Changed"
    assert document.stat().st_ino != written[document].st_ino, "document.json: rewritten in place, not replaced"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["capabilities.json", "document.json"]
