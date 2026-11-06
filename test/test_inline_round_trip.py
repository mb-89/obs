"""Every inline construct of a note survives into the Document; see capabilities/markdown."""
from collections import Counter

import pytest

from obs.document import build_document
from obs.note import parser as _parser
from test_vault import capability_reference


NOTE = (
    "# A *heading* with `code`\n\n"
    "Plain *em* _em_ **strong** __strong__ ***both*** ~~gone~~ `code` $x^2$ $$y$$ "
    "[a *marked* link](https://example.test) ![Alt](figure.svg) [[target|Target]] "
    "[[target#Part]] ![[target]] #mark/risk/watch soft\nbreak hard  \nbreak escaped\\\nbreak.\n\n"
    "- An *item* with **marks**\n  1. A ~~nested~~ `item`\n\n---\n\n"
    "> A *quoted* $q$\n\n"
    "| *Head* | **Bold** |\n|:---|---:|\n| ~~cell~~ | `x` [[target]] |\n"
)
"""One note with every inline construct the input model supports, in every inline place, and a
thematic break, the one block construct without inline content."""

TOKEN_KINDS = {
    "text": "text", "softbreak": "text", "hardbreak": "break", "link_open": "text",
    "em_open": "emphasis", "strong_open": "strong", "s_open": "strikethrough",
    "code_inline": "code", "math_inline": "math", "math_inline_double": "math",
    "image": "attachments",
}
"""The Document node kind each inline token the core's parser yields becomes."""
CLOSING = {"link_close", "em_close", "strong_close", "s_close"}
SEMANTIC = {"wikilinks", "embeds", "marks"}
"""Kinds the core finds inside text tokens; each keeps its authored text."""


def _tokens() -> list:
    return [
        child for token in _parser().parse(NOTE) if token.type == "inline"
        for child in token.children
    ]


def _token_text(child) -> str:
    """A soft break reads as a space, a hard break as a line break; see capabilities/markdown."""
    return {"softbreak": " ", "hardbreak": "\n"}.get(child.type, child.content)


def _node_text(node: dict[str, object], titles: dict[str, str]) -> str:
    attrs = node["attrs"]
    if node["type"] == "wikilinks":  # An unaliased link's label follows capabilities/wikilinks#Link text.
        heading = f"#{attrs['heading']}" if attrs["heading"] else ""
        unaliased = f"{titles[attrs['chapter']]} > {attrs['heading']}" if heading else attrs["target"]
        label = f"|{attrs['label']}" if attrs["label"] != unaliased else ""
        return f"[[{attrs['target']}{heading}{label}]]"
    if node["type"] == "embeds":
        return f"![[{attrs['target']}]]"
    if node["type"] == "marks":
        return f"#mark/{attrs['category']}/{attrs['id']}"
    if node["type"] == "attachments":
        return attrs["label"]
    if node["type"] == "break":
        return "\n"
    return node.get("text", "")


def _leaves(nodes: list[dict[str, object]]):
    for node in nodes:
        yield node
        yield from _leaves(node["children"])


def test_every_inline_construct_of_a_note_survives_into_the_document(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "target.md").write_text("# Target\n\n## Part\n", encoding="utf-8")
    (vault / "figure.svg").write_text("<svg/>", encoding="utf-8")
    (vault / "chapter.md").write_text(NOTE, encoding="utf-8")
    tokens = _tokens()

    document = build_document(vault / "manifest.md", capability_reference())

    nodes = list(_leaves(document["chapters"][0]["content"]))
    unmapped = {child.type for child in tokens} - TOKEN_KINDS.keys() - CLOSING
    assert unmapped == set(), f"inline tokens without a Document node kind: {unmapped}"
    kinds = Counter(node["type"] for node in nodes)
    for token_type in ("em_open", "strong_open", "s_open", "code_inline", "image", "hardbreak"):
        assert kinds[TOKEN_KINDS[token_type]] == sum(child.type == token_type for child in tokens)
    assert kinds["math"] == sum(child.type.startswith("math_inline") for child in tokens)
    display = [node["attrs"]["display"] for node in nodes if node["type"] == "math"]
    assert display.count(True) == sum(child.type == "math_inline_double" for child in tokens) == 1
    assert {"wikilinks", "embeds", "marks"} <= kinds.keys()
    thematic_breaks = sum(token.type == "hr" for token in _parser().parse(NOTE))
    assert thematic_breaks == 1
    assert kinds["rule"] == thematic_breaks
    linked = [node for node in nodes if node["type"] == "text" and "link" in node["attrs"]]
    assert "".join(node["text"] for node in linked) == "a marked link"
    inline_kinds = set(TOKEN_KINDS.values()) | SEMANTIC
    titles = {chapter["id"]: chapter["title"] for chapter in document["chapters"]}
    assert "".join(_node_text(node, titles) for node in nodes if node["type"] in inline_kinds) == "".join(
        _token_text(child) for child in tokens if child.type not in CLOSING | {"link_open"}
    )


@pytest.mark.parametrize("source", ["a  \nb\n", "a\\\nb\n"])
def test_a_hard_line_break_becomes_a_break_node(tmp_path, source) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text(source, encoding="utf-8")

    document = build_document(vault / "manifest.md", capability_reference())

    paragraph, = (node for node in document["chapters"][0]["content"] if node["type"] == "paragraph")
    assert paragraph["children"] == [
        {"type": "text", "attrs": {}, "children": [], "text": "a"},
        {"type": "break", "attrs": {}, "children": []},
        {"type": "text", "attrs": {}, "children": [], "text": "b"},
    ]


def test_a_soft_line_break_is_a_space_in_text(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text("a\nb\n", encoding="utf-8")

    document = build_document(vault / "manifest.md", capability_reference())

    paragraph, = (node for node in document["chapters"][0]["content"] if node["type"] == "paragraph")
    assert {node["type"] for node in paragraph["children"]} == {"text"}
    assert "".join(node["text"] for node in paragraph["children"]) == "a b"


def test_display_math_inside_a_line_becomes_a_display_math_node(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text("Text $$a^2$$ text\n", encoding="utf-8")

    document = build_document(vault / "manifest.md", capability_reference())

    paragraph, = (node for node in document["chapters"][0]["content"] if node["type"] == "paragraph")
    assert [(node["type"], node["attrs"], node.get("text")) for node in paragraph["children"]] == [
        ("text", {}, "Text "), ("math", {"display": True}, "a^2"), ("text", {}, " text"),
    ]
