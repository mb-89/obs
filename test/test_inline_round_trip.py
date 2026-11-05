"""Every inline construct of a note survives into the Document; see capabilities/markdown."""
from collections import Counter

from obs.document import build_document
from obs.vault import _parser
from test_vault import capability_reference


NOTE = (
    "# A *heading* with `code`\n\n"
    "Plain *em* _em_ **strong** __strong__ ***both*** ~~gone~~ `code` $x^2$ $$y$$ "
    "[a *marked* link](https://example.test) ![Alt](figure.svg) [[target|Target]] "
    "[[target#Part]] ![[target]] #mark/risk/watch soft\nbreak hard  \nbreak.\n\n"
    "- An *item* with **marks**\n  1. A ~~nested~~ `item`\n\n"
    "> A *quoted* $q$\n\n"
    "| *Head* | **Bold** |\n|:---|---:|\n| ~~cell~~ | `x` [[target]] |\n"
)
"""One note with every inline construct the input model supports, in every inline place."""

TOKEN_KINDS = {
    "text": "text", "softbreak": "text", "hardbreak": "text", "link_open": "text",
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
    return "\n" if child.type in {"softbreak", "hardbreak"} else child.content


def _node_text(node: dict[str, object]) -> str:
    attrs = node["attrs"]
    if node["type"] == "wikilinks":
        heading = f"#{attrs['heading']}" if attrs["heading"] else ""
        label = f"|{attrs['label']}" if attrs["label"] != attrs["target"] else ""
        return f"[[{attrs['target']}{heading}{label}]]"
    if node["type"] == "embeds":
        return f"![[{attrs['target']}]]"
    if node["type"] == "marks":
        return f"#mark/{attrs['category']}/{attrs['id']}"
    if node["type"] == "attachments":
        return attrs["label"]
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
    for token_type in ("em_open", "strong_open", "s_open", "code_inline", "image"):
        assert kinds[TOKEN_KINDS[token_type]] == sum(child.type == token_type for child in tokens)
    assert kinds["math"] == sum(child.type.startswith("math_inline") for child in tokens)
    assert {"wikilinks", "embeds", "marks"} <= kinds.keys()
    linked = [node for node in nodes if node["type"] == "text" and "link" in node["attrs"]]
    assert "".join(node["text"] for node in linked) == "a marked link"
    inline_kinds = set(TOKEN_KINDS.values()) | SEMANTIC
    assert "".join(_node_text(node) for node in nodes if node["type"] in inline_kinds) == "".join(
        _token_text(child) for child in tokens if child.type not in CLOSING | {"link_open"}
    )
