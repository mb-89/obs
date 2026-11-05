import json
import re
from pathlib import Path

from jsonschema import validate
import pytest

from obs.capabilities import build_capability_reference
from obs.document import build_document


ROOT = Path(__file__).parents[1]
INPUT_CAPABILITY_GAPS: frozenset[str] = frozenset({"extensions"})
"""Capabilities no input syntax yields yet; capabilities/extensions owns why."""


def capability_reference() -> dict[str, object]:
    return build_capability_reference(
        ROOT / "spec" / "capabilities", ROOT / "spec" / "capabilities" / "coverage.json",
    )


def node_types(document: dict[str, object]) -> set[str]:
    def descend(node: dict[str, object]):
        yield node["type"]
        for child in node["children"]:
            yield from descend(child)

    def chapters(items: list[dict[str, object]]):
        for chapter in items:
            for node in chapter["content"]:
                yield from descend(node)
            yield from chapters(chapter["children"])

    return {
        *[node["type"] for node in document["manifest"]["abstract"]],
        *chapters(document["chapters"]),
    }


def recognized_capability_document(tmp_path) -> dict[str, object]:
    vault = tmp_path / "recognized"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "target.md").write_text("# Target\n", encoding="utf-8")
    (vault / "chapter.md").write_text(
        "# Chapter\n\nBefore [[target#Heading|Label]] ![[target]] #mark/risk/watch.\n\n"
        "> [!warning] Be careful\n> Callout body.\n\n"
        "```base\nviews: []\n```\n\n```figure\ncaption: Diagram\n```\n\n```cmd\necho example\n```\n",
        encoding="utf-8",
    )
    return build_document(vault / "manifest.md", capability_reference())


def additional_capability_document(tmp_path) -> dict[str, object]:
    vault = tmp_path / "additional"
    vault.mkdir()
    (vault / "manifest.md").write_text(
        "---\ntitle: Fixture\n---\n- [[chapter]]\n",
        encoding="utf-8",
    )
    (vault / "register.base").write_text("views: []\n", encoding="utf-8")
    (vault / "source.csv").write_text("value\n1\n", encoding="utf-8")
    (vault / "chapter.md").write_text(
        "---\nkind: quantity\nquery: {where: []}\nobsHtml: {document: false}\n"
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
    return build_document(vault / "manifest.md", capability_reference())


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
    document = recognized_capability_document(tmp_path)
    content = document["chapters"][0]["content"]

    assert [node["type"] for node in content] == [
        "chapter-inclusion", "markdown", "section", "paragraph", "callouts", "bases",
        "figures", "command-fences",
    ]
    assert content[3]["children"][1] == {
        "type": "wikilinks",
        "attrs": {"target": "target", "chapter": "target", "heading": "Heading", "label": "Label"},
        "children": [],
    }
    assert content[3]["children"][3] == {
        "type": "embeds", "attrs": {"target": "target", "chapter": "target"}, "children": [],
    }
    assert content[3]["children"][5] == {
        "type": "marks", "attrs": {"category": "risk", "id": "watch"}, "children": [],
    }
    assert content[4]["attrs"] == {"kind": "warning", "title": "Be careful"}
    assert content[4]["children"] == [{
        "type": "paragraph", "attrs": {},
        "children": [{"type": "text", "attrs": {}, "children": [], "text": "Callout body."}],
    }]
    assert content[5]["attrs"] == {"source": "views: []\n", "spec": {"views": []}}
    assert content[6]["attrs"] == {"source": "caption: Diagram\n", "spec": {"caption": "Diagram"}}
    assert content[7]["attrs"] == {"source": "echo example\n"}
    assert set(document["capabilities"]) == {
        "bases", "callouts", "chapter-inclusion", "command-fences", "embeds", "figures",
        "manifest", "markdown", "marks", "wikilinks",
    }


def test_a_vault_whose_only_special_syntax_is_a_callout_uses_callouts_not_extensions(
    tmp_path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text("> [!warning] Check the limits\n> Body.\n", encoding="utf-8")

    document = build_document(vault / "manifest.md", capability_reference())

    assert "callouts" in document["capabilities"]
    assert "extensions" not in document["capabilities"]
    assert "extensions" not in node_types(document)


def test_core_marks_silent_command_fences_as_non_rendering_producers(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text(
        "```cmd silent\nproduce-file\n```\n", encoding="utf-8",
    )

    document = build_document(vault / "manifest.md", capability_reference())

    assert document["chapters"][0]["content"][-1] == {
        "type": "command-fences",
        "attrs": {"source": "produce-file\n", "silent": True},
        "children": [],
    }


def test_core_emits_data_only_nodes_for_additional_input_capabilities(tmp_path) -> None:
    document = additional_capability_document(tmp_path)
    nodes = document["chapters"][0]["content"]
    emitted = [
        node for parent in nodes
        for node in (parent["children"] if parent["type"] == "paragraph" else [parent])
    ]

    assert [node["type"] for node in emitted] == [
        "markdown-frontmatter", "profiles", "quantities", "queries", "count-query",
        "references", "chapter-inclusion", "markdown", "attachments", "registers",
        "cards-metrics", "figure-descriptor",
    ]
    assert emitted[-1]["attrs"]["descriptor"]["id"] == "comparison"
    assert {
        "attachments", "cards-metrics", "count-query", "figure-descriptor",
        "markdown-frontmatter", "profiles", "quantities", "queries", "references",
        "registers",
    } <= set(document["capabilities"])


def test_core_resolves_link_and_embed_targets_to_chapter_ids(tmp_path) -> None:
    vault = tmp_path / "vault"
    (vault / "part").mkdir(parents=True)
    (vault / "manifest.md").write_text("- [[intro]]\n- [[part/details]]\n", encoding="utf-8")
    (vault / "outside.md").write_text("Outside.\n", encoding="utf-8")
    (vault / "part" / "details.md").write_text("Details.\n", encoding="utf-8")
    (vault / "intro.md").write_text(
        "[[details#Part|Read]] ![[part/details]] [[outside]] ![[outside]] [[missing]]\n",
        encoding="utf-8",
    )

    document = build_document(vault / "manifest.md", capability_reference())
    nodes = [
        node for node in document["chapters"][0]["content"][-1]["children"]
        if node["type"] in {"wikilinks", "embeds"}
    ]

    assert [(node["type"], node["attrs"]["chapter"]) for node in nodes] == [
        ("wikilinks", "part-details"), ("embeds", "part-details"),
        ("wikilinks", "outside"), ("embeds", "outside"), ("wikilinks", None),
    ]


def test_spec_document_wikilinks_name_their_included_chapter() -> None:
    document = build_document(ROOT / "spec" / "manifest.md", capability_reference())
    manifest = (ROOT / "spec" / "manifest.md").read_text(encoding="utf-8")
    chapter_ids = {
        Path(target).name: re.sub(r"[^a-z0-9]+", "-", target.lower()).strip("-")
        for target in re.findall(r"^ *- \[\[([^\]|]+)", manifest, re.MULTILINE)
    }

    def links(nodes: list[dict[str, object]]):
        for node in nodes:
            if node["type"] in {"wikilinks", "embeds"}:
                yield node["attrs"]
            yield from links(node["children"])

    def chapters(items: list[dict[str, object]]):
        for chapter in items:
            yield from links(chapter["content"])
            yield from chapters(chapter["children"])

    resolved = list(chapters(document["chapters"]))
    included = [attrs for attrs in resolved if Path(attrs["target"]).name in chapter_ids]
    assert included
    assert all(attrs["chapter"] == chapter_ids[Path(attrs["target"]).name] for attrs in included)
    unlisted = {chapter["id"] for chapter in document["chapters"] if chapter.get("toc") is False}
    assert all(
        attrs["chapter"] in unlisted | {"home"}
        for attrs in resolved if Path(attrs["target"]).name not in chapter_ids
    )


def test_core_parses_the_spec_vault_as_neutral_document(tmp_path) -> None:
    reference = capability_reference()
    document = build_document(ROOT / "spec" / "manifest.md", reference)
    structural = {"document", "section", "paragraph", "text", "list", "list-item", "code"}
    references = {item["id"] for item in reference["capabilities"]}
    types = node_types(document)
    assert types <= structural | references
    assert {"wikilinks", "bases", "command-fences", "marks"} <= types
    assert set(document["capabilities"]) <= references
    assert set(document["capabilities"]) == types & references
    coverage = json.loads((ROOT / "spec" / "capabilities" / "coverage.json").read_text(
        encoding="utf-8",
    ))["sections"]
    input_ids = {
        item["id"] for item in reference["capabilities"]
        if coverage[item["source"].removesuffix("]]").split("#", 1)[1]] == "input"
    }
    emitted = types | node_types(recognized_capability_document(tmp_path)) | node_types(
        additional_capability_document(tmp_path),
    )
    assert input_ids <= emitted | INPUT_CAPABILITY_GAPS
    assert INPUT_CAPABILITY_GAPS == {"extensions"}
    assert not INPUT_CAPABILITY_GAPS & emitted
    with pytest.raises(AssertionError):
        assert input_ids <= (emitted - {"attachments"}) | INPUT_CAPABILITY_GAPS
    assert "html" not in types
