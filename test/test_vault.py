import json
from pathlib import Path

from jsonschema import validate

from obs.capabilities import build_capability_reference
from obs.document import build_document


ROOT = Path(__file__).parents[1]
INPUT_CAPABILITY_GAPS: frozenset[str] = frozenset()


def capability_reference() -> dict[str, object]:
    return build_capability_reference(
        ROOT / "spec" / "capabilities", ROOT / "spec" / "capabilities" / "coverage.json",
    )


def test_core_parses_a_vault_into_semantic_document_json(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text(
        "---\ntitle: Fixture vault\n---\n- [[chapter|Chapter]]\n",
        encoding="utf-8",
    )
    (vault / "chapter.md").write_text(
        "---\nkind: finding\n---\n# Heading\n\nA [reference](https://example.test/reference).\n\n"
        "![Diagram](diagram.svg)\n\n```text\nliteral\n```\n",
        encoding="utf-8",
    )
    (vault / "diagram.svg").write_text("<svg/>", encoding="utf-8")

    document = build_document(vault / "manifest.md", capability_reference())

    validate(document, json.loads((ROOT / "src" / "obs" / "document.schema.json").read_text(
        encoding="utf-8",
    )))
    assert document["manifest"] == {
        "title": "Fixture vault", "metadata": {"title": "Fixture vault"},
        "abstract": [
            {"type": "markdown-frontmatter", "attrs": {"metadata": {"title": "Fixture vault"}}, "children": []},
            {"type": "manifest", "attrs": {}, "children": []},
        ],
    }
    chapter = document["chapters"][0]
    assert chapter["metadata"] == {"kind": "finding"}
    assert [node["type"] for node in chapter["content"]] == [
        "markdown-frontmatter", "chapter-inclusion", "markdown", "section", "paragraph",
        "paragraph", "code",
    ]
    assert document["links"] == [{
        "id": "reference", "href": "https://example.test/reference", "label": "reference",
    }]
    assert document["assets"] == [{
        "id": "diagram", "href": "diagram.svg", "mediaType": "image/svg+xml",
    }]
    assert all(node["type"] != "html" for node in chapter["content"])


def test_core_places_recognized_capabilities_in_content_nodes(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "target.md").write_text("# Target\n", encoding="utf-8")
    (vault / "chapter.md").write_text(
        "# Chapter\n\nBefore [[target#Heading|Label]] ![[target]] #mark/risk/watch.\n\n"
        "> [!warning] Be careful\n> Callout body.\n\n"
        "```base\nviews: []\n```\n\n```figure\ncaption: Diagram\n```\n\n```cmd\necho example\n```\n",
        encoding="utf-8",
    )

    content = build_document(vault / "manifest.md", capability_reference())["chapters"][0]["content"]

    assert [node["type"] for node in content] == [
        "chapter-inclusion", "markdown", "section", "paragraph", "extensions", "callouts", "bases",
        "figures", "command-fences",
    ]
    assert content[3]["children"][1] == {
        "type": "wikilinks",
        "attrs": {"target": "target", "heading": "Heading", "label": "Label"},
        "children": [],
    }
    assert content[3]["children"][3] == {
        "type": "embeds", "attrs": {"target": "target"}, "children": [],
    }
    assert content[3]["children"][5] == {
        "type": "marks", "attrs": {"category": "risk", "id": "watch"}, "children": [],
    }
    assert content[5]["attrs"] == {"kind": "warning", "title": "Be careful"}
    assert content[5]["children"] == [{
        "type": "paragraph", "attrs": {},
        "children": [{"type": "text", "attrs": {}, "children": [], "text": "Callout body."}],
    }]
    assert content[6]["attrs"] == {"source": "views: []\n", "spec": {"views": []}}
    assert content[7]["attrs"] == {"source": "caption: Diagram\n", "spec": {"caption": "Diagram"}}
    assert content[8]["attrs"] == {"source": "echo example\n"}
    assert set(build_document(vault / "manifest.md", capability_reference())["capabilities"]) == {
        "bases", "callouts", "chapter-inclusion", "command-fences", "embeds", "extensions", "figures",
        "manifest", "markdown", "marks", "wikilinks",
    }


def test_core_emits_data_only_nodes_for_additional_input_capabilities(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text(
        "---\ntitle: Fixture\n---\n- [[chapter]]\n",
        encoding="utf-8",
    )
    (vault / "register.base").write_text("views: []\n", encoding="utf-8")
    (vault / "source.csv").write_text("value\n1\n", encoding="utf-8")
    (vault / "chapter.md").write_text(
        "---\nkind: quantity\nquery: {where: []}\nobsHtml: {document: false}\n"
        "bottom line: Keep the conclusion concise.\n"
        "reference: https://example.test/source\n---\n"
        "![Source](source.csv)\n\n![[register.base#Open]]\n\n"
        "```cards\nversion: 1\ncards: [{title: Coverage, body: Current state.}]\n```\n\n"
        "```figure\n"
        '{"schemaVersion": 1, "id": "comparison", "data": {}, "panels": [{"id": "overview", '
        '"bounds": {"x": 0, "y": 0, "width": 1, "height": 1}, '
        '"grid": {"row": 0, "column": 0, "rowSpan": 1, "columnSpan": 1}, '
        '"axes": [{"id": "time", "scale": "linear", "limits": {"minimum": 0, "maximum": 1}, '
        '"label": "Time"}]}], '
        '"provenance": {"command": ["generate-figure"]}}\n'
        "```\n",
        encoding="utf-8",
    )

    document = build_document(vault / "manifest.md", capability_reference())
    nodes = document["chapters"][0]["content"]
    emitted = [
        node for parent in nodes
        for node in (parent["children"] if parent["type"] == "paragraph" else [parent])
    ]

    assert [node["type"] for node in emitted] == [
        "markdown-frontmatter", "profiles", "quantities", "bottom-lines", "queries", "count-query",
        "references", "chapter-inclusion", "markdown", "attachments", "registers",
        "cards-metrics", "figure-descriptor",
    ]
    assert emitted[-1]["attrs"]["descriptor"]["id"] == "comparison"
    assert {
        "attachments", "cards-metrics", "count-query", "figure-descriptor",
        "markdown-frontmatter", "profiles", "quantities", "queries", "references",
        "registers",
    } <= set(document["capabilities"])


def test_core_parses_the_spec_vault_as_neutral_document() -> None:
    document = build_document(ROOT / "spec" / "manifest.md", capability_reference())
    structural = {"document", "section", "paragraph", "text", "list", "list-item", "code"}
    references = {item["id"] for item in capability_reference()["capabilities"]}

    def nodes(chapters):
        for chapter in chapters:
            for node in chapter["content"]:
                yield from descend(node)
            yield from nodes(chapter["children"])

    def descend(node):
        yield node
        for child in node["children"]:
            yield from descend(child)

    manifest_types = {node["type"] for node in document["manifest"]["abstract"]}
    types = manifest_types | {node["type"] for node in nodes(document["chapters"])}
    assert types <= structural | references
    assert {"wikilinks", "bases", "command-fences", "marks"} <= types
    assert set(document["capabilities"]) <= references
    assert set(document["capabilities"]) == types & references
    assert INPUT_CAPABILITY_GAPS == frozenset()
    assert all(node["type"] != "html" for node in nodes(document["chapters"]))
