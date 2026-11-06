"""The spec's manifest note, spec/manifest.md, as the core reads it into obs's spec Document.

Reader: whoever changes the spec's manifest or its chapters.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
MANIFEST = ROOT / "spec" / "manifest.md"


def _chapters(items: list[dict]):
    for chapter in items:
        yield chapter
        yield from _chapters(chapter["children"])


def _nodes(nodes: list[dict]):
    for node in nodes:
        yield node
        yield from _nodes(node.get("children", []))


def _chapter_paths(document: dict) -> dict[str, str]:
    """Each chapter's id and the vault path of the note it comes from (its note record)."""
    paths = {record["id"]: record.get("path") for record in document["records"]}
    return {chapter["id"]: paths.get(chapter["id"]) for chapter in _chapters(document["chapters"])}


def test_spec_manifest_is_a_nested_list_of_existing_links(spec_document) -> None:
    manifest = spec_document["manifest"]

    assert spec_document["chapters"]
    assert manifest["title"] == "obs"
    assert [node for node in manifest["abstract"] if node["type"] != "markdown-frontmatter"]
    paths = _chapter_paths(spec_document)
    assert all(path and (ROOT / "spec" / path).is_file() for path in paths.values()), paths


def test_spec_manifest_reaches_every_design_input_note(spec_document) -> None:
    design_inputs = {f"design_input/{path.name}" for path in (ROOT / "spec" / "design_input").glob("*.md")}

    assert design_inputs <= set(_chapter_paths(spec_document).values())


def test_every_spec_wiki_link_resolves(spec_document) -> None:
    unresolved = [
        (chapter["id"], node["attrs"]["target"])
        for chapter in _chapters(spec_document["chapters"])
        for node in _nodes(chapter["content"])
        if node["type"] == "wikilinks" and not node["attrs"].get("chapter")
    ]

    assert unresolved == []
    assert spec_document["diagnostics"] == []


def test_spec_manifest_declares_generic_paged_presentation(spec_document) -> None:
    frontmatter = yaml.safe_load(MANIFEST.read_text(encoding="utf-8").split("---", 2)[1])

    assert spec_document["manifest"]["metadata"]["obsHtml"] == {
        "layout": "paged",
        "pages": [
            {"page": "cover"},
            {"page": "abstract", "title": "Abstract"},
            {"page": "contents", "title": "Contents"},
        ],
    }
    assert frontmatter["product"] == {"name": "", "version": ""}
    for field in (
        "organization", "template", "document number", "authors", "reviewers", "approvers",
        "copyright", "confidentiality", "legal entity",
    ):
        assert frontmatter[field] == ""


def test_dogfood_subtitle_owns_hosted_logos_not_abstract(spec_document) -> None:
    """The subtitle holds the two hosted badges, Obsidian then HTML5 with an arrow between; the
    abstract holds neither."""
    [record] = [record for record in spec_document["records"] if record.get("path") == "manifest.md"]
    subtitle = {node["attrs"]["name"]: node["children"] for node in record["fieldNodes"]}["subtitle"]
    assets = {asset["id"]: asset["href"] for asset in spec_document["assets"]}

    assert [node["type"] for node in subtitle] == ["attachments", "text", "attachments"]
    assert [node["attrs"]["label"] for node in subtitle[::2]] == ["Obsidian", "HTML5"]
    assert subtitle[1]["text"].strip() == "→"
    assert all(assets[node["attrs"]["asset"]].startswith("https://img.shields.io/badge/") for node in subtitle[::2])
    abstract = [node for node in spec_document["manifest"]["abstract"] if node["type"] != "markdown-frontmatter"]
    assert "img.shields.io" not in str(abstract)
