"""One generic figure node: every kind shares one node shape, from inline or external content.

Reader: whoever changes a figure kind or the figures node (input-model, Figure input direction).
"""
import base64
import json
from pathlib import Path

import pytest

from obs.document import DocumentError, build_document, validate_document
from obs.figure import FIGURE_KINDS

from test_vault import capability_reference


ROOT = Path(__file__).parents[1]
SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'
GRAPH = {
    "version": 1,
    "nodes": [{"id": "a", "label": "A", "stage": 0}, {"id": "b", "label": "B", "stage": 1}],
    "links": [{"source": "a", "target": "b", "value": 2}],
}
DESCRIPTOR = {
    "schemaVersion": 1, "id": "response",
    "data": {"traces": [{"x": [0, 1], "y": [1, 2]}]},
    "panels": [{
        "id": "main", "bounds": {"x": 0, "y": 0, "width": 1, "height": 1},
        "grid": {"row": 0, "column": 0, "rowSpan": 1, "columnSpan": 1},
        "axes": [
            {"id": "x", "scale": "linear", "limits": {"minimum": 0, "maximum": 1}, "label": "x"},
            {"id": "y", "scale": "linear", "limits": {"minimum": 0, "maximum": 2}, "label": "y"},
        ],
    }],
    "provenance": {"command": ["measure"]},
}
CURVE = {
    "equations": "y = a*x",
    "variables": {"x": {"default": 0, "range": [0, 1]}, "a": {"default": 2}, "y": {}},
    "plot": {"x": "x", "y": "y"},
}
FLOW = "graph LR\n  A --> B\n"
SEQUENCE = "@startuml\nA -> B\n@enduml\n"
KINDS = {
    # kind: (file name, file text, inline content as YAML, kind options)
    "image": ("drawing.svg", SVG, json.dumps(SVG), ""),
    "svg": ("panels.svg", SVG, json.dumps(SVG), "panels: [{id: all, title: All, box: [0, 0, 10, 10]}]\n"),
    "sankey": ("flow.json", json.dumps(GRAPH), json.dumps(GRAPH), "countLabels: {unit: items}\n"),
    "plot": ("response.json", json.dumps(DESCRIPTOR), json.dumps(DESCRIPTOR), ""),
    "equations": ("curve.json", json.dumps(CURVE), json.dumps(CURVE), ""),
    "mermaid": ("flow.mmd", FLOW, json.dumps(FLOW), ""),
    "plantuml": ("sequence.puml", SEQUENCE, json.dumps(SEQUENCE), ""),
}


def _document(tmp_path: Path, chapter: str, files: dict[str, str] | None = None) -> dict:
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "chapter.md").write_text(chapter, encoding="utf-8")
    for name, text in (files or {}).items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return build_document(tmp_path / "manifest.md", capability_reference())


def _fence(kind: str, content: str, options: str = "", caption: str = "A [[target]] caption") -> str:
    return (f"```figure\nversion: 1\nkind: {kind}\ncaption: {json.dumps(caption)}\nalt: Alt text\n"
            f"{options}{content}\n```\n^{kind}-figure\n")


def _figures(document: dict) -> list[dict]:
    return [node for node in document["chapters"][0]["content"] if node["type"] == "figures"]


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_inline_and_external_content_give_the_same_node(tmp_path, kind) -> None:
    name, text, inline, options = KINDS[kind]
    (tmp_path / "target.md").write_text("# Target\n", encoding="utf-8")
    document = _document(
        tmp_path, "# Chapter\n\n" + _fence(kind, f"source: {name}", options) + "\n"
        + _fence(kind, f"content: {inline}", options), {name: text},
    )

    external, inline_node = _figures(document)

    assert external == inline_node
    assert external["attrs"]["kind"] == kind
    assert external["attrs"]["alt"] == "Alt text"
    assert external["attrs"]["block"] == f"{kind}-figure"
    assert [paragraph["type"] for paragraph in external["attrs"]["caption"]] == ["paragraph"]
    assert "wikilinks" in [node["type"] for node in external["attrs"]["caption"][0]["children"]]
    [body] = external["children"]
    assert body["type"] == kind
    assert not {"kind", "caption", "alt", "block", "number"} & set(body["attrs"])
    assert "figures" in document["capabilities"]
    # The block id line is the figure's, never visible text.
    assert f"^{kind}-figure" not in json.dumps(document["chapters"][0]["content"][-1])


def test_each_kind_carries_its_content_in_its_one_child(tmp_path) -> None:
    document = _document(tmp_path, "".join(
        _fence(kind, f"source: {name}", options) + "\n" for kind, (name, _, _, options) in sorted(KINDS.items())
    ), {name: text for name, text, _, _ in KINDS.values()})

    bodies = {node["attrs"]["kind"]: node["children"][0]["attrs"] for node in _figures(document)}

    assert bodies["image"] == {"mediaType": "image/svg+xml", "data": base64.b64encode(SVG.encode()).decode()}
    assert bodies["svg"] == {"svg": SVG, "panels": [{"id": "all", "title": "All", "box": [0, 0, 10, 10]}]}
    assert bodies["sankey"] == {"graph": GRAPH, "countLabels": {"unit": "items"}}
    assert bodies["plot"] == {"descriptor": DESCRIPTOR}
    assert [bodies["mermaid"]["source"], bodies["plantuml"]["source"]] == [FLOW, SEQUENCE]
    assert bodies["equations"]["solution"]["branches"] == [
        {"y": {"op": "mul", "args": [{"symbol": "a"}, {"symbol": "x"}]}}]


def test_the_kind_registry_and_the_body_schemas_name_the_same_kinds() -> None:
    schema = json.loads((ROOT / "src" / "obs" / "document.schema.json").read_text(encoding="utf-8"))

    assert set(FIGURE_KINDS) == set(schema["$defs"]["figureBodies"]) == set(KINDS)


@pytest.mark.parametrize(
    ("fence", "field", "owner"),
    [
        ("kind: image\n", "figure fence 1, source", "capabilities/figures"),
        ("kind: image\nsource: drawing.svg\ncontent: '<svg/>'\n", "figure fence 1, source", "capabilities/figures"),
        ("kind: chart\ncontent: {}\n", "figure fence 1, kind", "capabilities/figures"),
        ("kind: sankey\ncontent: {}\ncountLabels: {colour: red}\n", "figure fence 1, countLabels", "capabilities/figures"),
        ("kind: plot\ncontent: {schemaVersion: 1}\n", "figure fence 1, content.id", "capabilities/figure-descriptor"),
        ("kind: image\nsource: missing.png\n", "figure fence 1, source", "capabilities/figures"),
        ("kind: image\nsource: ../outside.png\n", "figure fence 1, source", "capabilities/figures"),
        ("kind: svg\ncontent: 'not markup'\n", "figure fence 1, content", "capabilities/figures"),
        ("kind: image\nsource: notes.txt\n", "figure fence 1, source", "capabilities/figures"),
    ],
)
def test_a_figure_input_error_names_the_note_the_field_and_the_owner(tmp_path, fence, field, owner) -> None:
    with pytest.raises(DocumentError) as failure:
        _document(tmp_path, f"```figure\nversion: 1\n{fence}```\n", {"drawing.svg": SVG, "notes.txt": "x"})

    message = str(failure.value)
    assert message.startswith(f"{tmp_path / 'chapter.md'}: {field}"), message
    assert f"see {owner}." in message


def test_the_document_refuses_a_figure_body_of_an_unknown_kind_or_shape(tmp_path) -> None:
    document = _document(tmp_path, _fence("sankey", f"content: {json.dumps(GRAPH)}"))
    figure = _figures(document)[0]

    figure["children"][0]["attrs"]["extra"] = 1
    with pytest.raises(DocumentError, match=r"figureBodies"):
        validate_document(document, capability_reference())
    figure["children"][0] = {"type": "chart", "attrs": {}, "children": []}
    with pytest.raises(DocumentError, match=r"figureBodies"):
        validate_document(document, capability_reference())
