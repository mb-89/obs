"""Block node ids (input-model, Block node ids).

Reader: whoever changes how the core identifies a block node, reads an Obsidian block reference,
or resolves a comment's node target.

Every identified block node of a chapter carries an ``id``: an explicit ``^name`` where the author
wrote one, else ``<type>-<hash>`` of its normalized text, numbered among identical blocks. A keyed
row of a register or Base is ``<table id>:<record id>``.
"""
import json
from pathlib import Path

import pytest

from obs.document import build_document
from obs.input import InputError
from test_vault import capability_reference

OWNER = "input-model#Block node ids"
SCHEMA = Path(__file__).parents[1] / "src" / "obs" / "document.schema.json"
CONTAINERS = {"list", "list-item", "quote", "callouts", "table", "cards-metrics", "document"}

NOTE = """# Design

The first paragraph.

The second paragraph.

- one item
- another item
  - nested item

| Key | Value |
|-----|-------|
| a   | 1     |

> A quotation.

```python
x = 1
```

```cards
{"version": 1, "cards": [{"title": "Coverage", "body": "Current state."}]}
```

$$
x^2
$$

---
"""


def _build(tmp_path: Path, note: str = NOTE, extra: dict[str, str] | None = None) -> dict:
    (tmp_path / "manifest.md").write_text("- [[design]]\n", encoding="utf-8")
    (tmp_path / "design.md").write_text(note, encoding="utf-8")
    for name, text in (extra or {}).items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return build_document(tmp_path / "manifest.md", capability_reference())


def _blocks(nodes: list[dict]):
    """Every node in a block position, in document order."""
    for node in nodes:
        yield node
        if node["type"] in CONTAINERS:
            yield from _blocks(node["children"])


def _ids(document: dict) -> dict[str, str]:
    """Each identified block's id, by its type and text."""
    return {node["id"]: _text(node) for node in _blocks(document["chapters"][0]["content"]) if "id" in node}


def _text(node: dict) -> str:
    return node.get("text", "") + "".join(_text(child) for child in node["children"])


def _by_text(document: dict, text: str) -> dict:
    [node] = [node for node in _blocks(document["chapters"][0]["content"]) if _text(node) == text]
    return node


def test_every_identified_block_node_has_an_id_unique_in_its_chapter(tmp_path: Path) -> None:
    document = _build(tmp_path)
    identified = set(json.loads(SCHEMA.read_text(encoding="utf-8"))["$defs"]["identifiedType"]["enum"])
    blocks = list(_blocks(document["chapters"][0]["content"]))
    kinds = {node["type"] for node in blocks}
    assert {"section", "paragraph", "list", "list-item", "table", "table-row", "quote", "code", "math",
            "rule", "cards-metrics", "document"} <= kinds
    assert [node["type"] for node in blocks if _text(node) == "Current state." and "id" in node] == [
        "cards-metrics", "document", "paragraph"]  # A card and the blocks of its body have ids too.
    assert all("id" in node for node in blocks if node["type"] in identified)
    assert not any("id" in node for node in blocks if node["type"] not in identified)
    ids = [node["id"] for node in blocks if "id" in node]
    assert len(ids) == len(set(ids))
    assert _by_text(document, "The first paragraph.")["id"].startswith("paragraph-")


def test_the_same_source_gets_the_same_ids(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first = _ids(_build(tmp_path / "a"))
    assert len(first) > 10
    assert first == _ids(_build(tmp_path / "b"))


def test_an_insertion_or_removal_elsewhere_leaves_ids_unchanged(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    before = _ids(_build(tmp_path / "a"))
    assert len(before) > 10
    edited = NOTE.replace("The second paragraph.\n\n", "").replace(
        "# Design\n", "# Design\n\nAn inserted paragraph.\n\n| X |\n|---|\n| y |\n")
    after = _ids(_build(tmp_path / "b", edited))
    removed = {identifier for identifier, text in before.items() if text == "The second paragraph."}
    assert {identifier: text for identifier, text in before.items() if identifier not in removed}.items() \
        <= after.items()


def test_an_edited_block_gets_a_new_id_and_the_others_keep_theirs(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    before = _build(tmp_path / "a")
    after = _build(tmp_path / "b", NOTE.replace("The first paragraph.", "The first paragraph, edited."))
    old, new = _by_text(before, "The first paragraph.")["id"], _by_text(after, "The first paragraph, edited.")["id"]
    assert old != new
    assert old not in _ids(after)
    assert _by_text(after, "The second paragraph.")["id"] == _by_text(before, "The second paragraph.")["id"]


def test_whitespace_alone_does_not_change_an_id(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    before = _build(tmp_path / "a")
    after = _build(tmp_path / "b", NOTE.replace("The first paragraph.", "The  first\nparagraph."))
    assert _by_text(before, "The first paragraph.")["id"] in _ids(after)


def test_an_obsidian_block_reference_is_the_blocks_id_and_is_not_shown(tmp_path: Path) -> None:
    note = ("# Design\n\nA pinned paragraph. ^pinned\n\nA paragraph\nover two lines ^two-lines\n\n"
            "- a pinned item ^item-ref\n- a plain item\n\n| K |\n|---|\n| v |\n\n^the-table\n\n> Quoted.\n\n^the-quote\n\n"
            "```figure\nversion: 1\nkind: svg\ncaption: A figure.\n"
            "content: '<svg xmlns=\"http://www.w3.org/2000/svg\"/>'\n```\n^the-figure\n")
    document = _build(tmp_path, note)
    content = document["chapters"][0]["content"]
    blocks = {node["id"]: node for node in _blocks(content) if "id" in node}
    assert _text(blocks["pinned"]) == "A pinned paragraph."
    assert _text(blocks["two-lines"]) == "A paragraph over two lines"
    assert blocks["item-ref"]["type"] == "list-item"
    assert _text(blocks["item-ref"]) == "a pinned item"
    assert blocks["the-table"]["type"] == "table"
    assert blocks["the-quote"]["type"] == "quote"
    assert blocks["the-figure"]["type"] == "figures"
    assert blocks["the-figure"]["attrs"]["block"] == "the-figure"
    assert "^" not in json.dumps([_text(node) for node in _blocks(content)])
    assert not any(_text(node).startswith("^") for node in _blocks(content))


def test_two_blocks_of_a_chapter_with_one_block_reference_name_the_note_and_the_owner(tmp_path: Path) -> None:
    with pytest.raises(InputError) as failure:
        _build(tmp_path, "First. ^same\n\nSecond. ^same\n")
    message = str(failure.value)
    assert "design.md" in message
    assert "^same" in message
    assert OWNER in message


def test_identical_blocks_stay_distinct_numbered_in_document_order(tmp_path: Path) -> None:
    document = _build(tmp_path, "Same.\n\nOther.\n\nSame.\n\n- Same.\n")
    paragraphs = [node["id"] for node in _blocks(document["chapters"][0]["content"])
                  if node["type"] == "paragraph" and _text(node) == "Same."]
    assert len(paragraphs) == 3
    assert paragraphs[1] == f"{paragraphs[0]}-2"
    assert paragraphs[2] == f"{paragraphs[0]}-3"


def test_a_derived_id_never_takes_an_explicit_ones_name(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    derived = _by_text(_build(tmp_path / "a", "Text.\n"), "Text.")["id"]
    (tmp_path / "b").mkdir()
    document = _build(tmp_path / "b", f"Other. ^{derived}\n\nText.\n")
    assert _by_text(document, "Text.")["id"] == f"{derived}-2"


def test_a_command_output_is_not_part_of_the_id(tmp_path: Path) -> None:
    note = "```cmd\necho hello\n```\n"
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "manifest.md").write_text("- [[design]]\n", encoding="utf-8")
    (tmp_path / "a" / "design.md").write_text(note, encoding="utf-8")
    executed = build_document(tmp_path / "a" / "manifest.md", capability_reference(), execute_commands=True)
    (tmp_path / "b" / "manifest.md").write_text("- [[design]]\n", encoding="utf-8")
    (tmp_path / "b" / "design.md").write_text(note.replace("hello", "world"), encoding="utf-8")
    other = build_document(tmp_path / "b" / "manifest.md", capability_reference(), execute_commands=True)
    [ran] = [node for node in executed["chapters"][0]["content"] if node["type"] == "command-fences"]
    [changed] = [node for node in other["chapters"][0]["content"] if node["type"] == "command-fences"]
    assert ran["attrs"]["output"]
    assert ran["id"].startswith("command-fences-") and ran["id"] != changed["id"]


def test_a_markdown_table_row_has_a_derived_id_from_its_cells(tmp_path: Path) -> None:
    document = _build(tmp_path, "| K | V |\n|---|---|\n| a | 1 |\n| a1 | |\n")
    [table] = [node for node in document["chapters"][0]["content"] if node["type"] == "table"]
    rows = [row["id"] for row in table["children"]]
    assert all(row.startswith("table-row-") for row in rows)
    assert len(set(rows)) == 3


REGISTER = "views:\n  - type: table\n    name: All\n    order: [file.name]\n"


def _overlay(tmp_path: Path, *targets: dict) -> None:
    comments = [{"id": f"c{index}", "author": "Alice", "created": "2026-11-09T08:00:00Z",
                 "body": {"mediaType": "text/plain", "text": "Comment."}, "state": "open",
                 "target": {"chapter": "design", **target}} for index, target in enumerate(targets)]
    (tmp_path / "manifest.comments.alice.json").write_text(json.dumps(
        {"version": 1, "principal": "alice", "comments": comments, "decisions": []}), encoding="utf-8")


def test_a_register_row_is_keyed_by_its_record_and_a_comment_can_target_it(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    document = _build(tmp_path / "a", "# Design\n\n![[notes.base#All]]\n", {"notes.base": REGISTER})
    [register] = [node for node in document["chapters"][0]["content"] if node["type"] == "registers"]
    [rows] = register["attrs"]["rows"]
    assert rows
    vault = tmp_path / "b"
    vault.mkdir()
    _overlay(vault, {"node": f"{register['id']}:{rows[0]}"}, {"node": f"{register['id']}:no-such-record"},
             {"node": _by_text(document, "Design")["id"]})
    warned = _build(vault, "# Design\n\n![[notes.base#All]]\n", {"notes.base": REGISTER})
    warnings = [item["message"] for item in warned["diagnostics"] if item["level"] == "warning"]
    assert len(warnings) == 1
    assert "comments[1].target.node" in warnings[0]


def test_a_base_fence_row_is_any_record_of_the_document(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    note = f"# Design\n\n```base\n{REGISTER}```\n"
    document = _build(tmp_path / "a", note)
    [base] = [node for node in document["chapters"][0]["content"] if node["type"] == "bases"]
    record = document["records"][0]["id"]
    vault = tmp_path / "b"
    vault.mkdir()
    _overlay(vault, {"node": f"{base['id']}:{record}"}, {"node": f"{base['id']}:no-such-record"})
    warned = _build(vault, note)
    warnings = [item["message"] for item in warned["diagnostics"] if item["level"] == "warning"]
    assert len(warnings) == 1
    assert "comments[1].target.node" in warnings[0]


def test_a_comment_can_target_any_block_and_an_unknown_one_still_warns(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    document = _build(tmp_path / "a")
    targets = [{"node": identifier} for identifier in _ids(document)]
    assert len(targets) > 10
    vault = tmp_path / "b"
    vault.mkdir()
    _overlay(vault, *targets, {"node": "paragraph-00000000"})
    warned = _build(vault)
    warnings = [item["message"] for item in warned["diagnostics"] if item["level"] == "warning"]
    assert len(warnings) == 1
    assert f"comments[{len(targets)}].target.node" in warnings[0]
    assert "input-model#Comments and reviews" in warnings[0]
