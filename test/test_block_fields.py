"""Block fields (input-model, Block fields).

Reader: whoever changes how the core reads a ``key:: value`` line, attaches it to a block or a
section, or resolves a block's effective values.

A whole ``key:: value`` line of a paragraph is a field, not prose: it belongs to its paragraph, or,
in a paragraph made only of such lines, to the table, list, quote, callout or heading right before
it. A block's effective values are its own, then its containers', then its sections', then the
front matter's; ``key::`` unsets.
"""
import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from obs.block_fields import values
from obs.document import DocumentError, build_document
from obs.selection import conditions_select
from test_vault import capability_reference

OWNER = "input-model#Block fields"
SCHEMA = Path(__file__).parents[1] / "src" / "obs" / "document.schema.json"
CONTAINERS = {"list", "list-item", "quote", "callouts", "table", "cards-metrics", "document", "columns"}


def _content(tmp_path: Path, note: str) -> list[dict]:
    (tmp_path / "manifest.md").write_text("- [[design]]\n", encoding="utf-8")
    (tmp_path / "design.md").write_text(note, encoding="utf-8")
    return build_document(tmp_path / "manifest.md", capability_reference())["chapters"][0]["content"]


def _blocks(nodes: list[dict]):
    for node in nodes:
        yield node
        if node["type"] in CONTAINERS:
            yield from _blocks(node["children"])


def _text(node: dict) -> str:
    return node.get("text", "") + "".join(_text(child) for child in node["children"])


def _of(nodes: list[dict], kind: str, text: str = "") -> dict:
    return next(node for node in _blocks(nodes) if node["type"] == kind and text in _text(node))


def _shown(nodes: list[dict]) -> str:
    return "\n".join(_text(node) for node in _blocks(nodes) if node["type"] == "paragraph")


def _effective(node: dict) -> dict:
    return values(node["effective"])


def test_a_field_line_inside_a_paragraph_belongs_to_that_paragraph(tmp_path: Path) -> None:
    content = _content(tmp_path, "# Design\n\nThe pump runs.\nowner:: ana\nstatus:: open\n")
    paragraph = _of(content, "paragraph", "The pump runs.")
    assert paragraph["fields"] == {"owner": "ana", "status": "open"}
    assert _text(paragraph) == "The pump runs."
    assert "::" not in _shown(content)


def test_a_field_paragraph_after_a_table_belongs_to_the_table(tmp_path: Path) -> None:
    content = _content(tmp_path, "| Key | Value |\n|---|---|\n| a | 1 |\n\nowner:: ana\n")
    assert _of(content, "table")["fields"] == {"owner": "ana"}
    assert [node["type"] for node in content if node["type"] == "paragraph"] == []


def test_a_field_paragraph_after_a_list_belongs_to_the_list(tmp_path: Path) -> None:
    content = _content(tmp_path, "- one\n- two\n\nreview.owner:: ana\n")
    lists = _of(content, "list")
    assert lists["fields"] == {"review.owner": "ana"}
    assert _effective(_of(content, "paragraph", "two")) == {"review.owner": "ana"}


def test_a_field_paragraph_after_a_callout_belongs_to_the_callout(tmp_path: Path) -> None:
    content = _content(tmp_path, "> [!note] Pump\n> It runs.\n\nstatus:: done\n")
    assert _of(content, "callouts")["fields"] == {"status": "done"}


def test_a_field_paragraph_after_a_heading_belongs_to_its_section(tmp_path: Path) -> None:
    content = _content(tmp_path, "# Design\n\n## Pump\n\nowner:: ana\n\nIt runs.\n\n## Valve\n\nIt shuts.\n")
    pump = _of(content, "section", "Pump")
    assert pump["fields"] == {"owner": "ana"}
    assert _of(content, "paragraph", "It runs.")["effective"]["owner"] == {"value": "ana", "node": pump["id"]}
    assert "effective" not in _of(content, "paragraph", "It shuts.")


def test_field_lines_first_in_a_list_item_or_a_callout_belong_to_it(tmp_path: Path) -> None:
    content = _content(tmp_path, "- owner:: ana\n- two\n\n> [!note] Pump\n> status:: open\n")
    assert _of(content, "list-item", "")["fields"] == {"owner": "ana"}
    assert _of(content, "callouts")["fields"] == {"status": "open"}


def test_a_block_reference_line_beside_a_field_paragraph_still_names_the_block(tmp_path: Path) -> None:
    content = _content(tmp_path, "| Key |\n|---|\n| a |\n\n^pumps\n\nowner:: ana\n")
    table = _of(content, "table")
    assert (table["id"], table["fields"]) == ("pumps", {"owner": "ana"})


def test_effective_values_inherit_override_and_unset(tmp_path: Path) -> None:
    content = _content(tmp_path, (
        "---\nowner: fm\nreview:\n  state: draft\nphase: 1\n---\n"
        "# Design\n\nowner:: chapter\n\n## Pump\n\nstate:: x\n\n"
        "Inherits.\n\nOverrides.\nowner:: me\n\nUnsets.\nowner::\nreview.state::\n"
    ))
    design = _of(content, "section", "Design")
    inherits = _of(content, "paragraph", "Inherits.")
    assert inherits["effective"]["owner"] == {"value": "chapter", "node": design["id"]}
    assert inherits["effective"]["review.state"] == {"value": "draft", "frontmatter": True}
    assert _effective(inherits)["phase"] == 1
    overrides = _of(content, "paragraph", "Overrides.")
    assert overrides["effective"]["owner"] == {"value": "me", "node": overrides["id"]}
    unsets = _of(content, "paragraph", "Unsets.")
    assert unsets["fields"] == {"owner": None, "review.state": None}
    assert "owner" not in unsets["effective"] and "review.state" not in unsets["effective"]
    assert _effective(unsets)["state"] == "x"


def test_values_are_yaml_scalars_and_other_text_is_text(tmp_path: Path) -> None:
    content = _content(tmp_path, "Values.\ncount:: 3\ndone:: true\ndue:: 2026-11-22\nwho:: [[Ana]]\nnote:: a: b\n")
    assert _of(content, "paragraph", "Values.")["fields"] == {
        "count": 3, "done": True, "due": "2026-11-22", "who": "[[Ana]]", "note": "a: b"}


def test_the_query_conditions_match_a_block_s_effective_fields(tmp_path: Path) -> None:
    content = _content(tmp_path, "---\nstatus: open\n---\n- one\n\nreview.owner:: ana\n")
    found = _effective(_of(content, "paragraph", "one"))
    assert conditions_select([{"field": "review.owner", "equals": "ANA"}, {"field": "status", "equals": "open"}],
                             found, "design.md")
    assert not conditions_select([{"field": "review.owner", "equals": "bo"}], found, "design.md")


def test_front_matter_alone_adds_no_block_fields(tmp_path: Path) -> None:
    content = _content(tmp_path, "---\nowner: fm\n---\n# Design\n\nText with std::vector inside.\n")
    assert not any("fields" in node or "effective" in node for node in _blocks(content))
    assert "std::vector" in _shown(content)


@pytest.mark.parametrize(("note", "line"), [
    ("owner:: ana\n\n# Design\n", 1),
    ("---\ntitle: Design\n---\n\nowner:: ana\n", 5),
    ("Text.\n\nowner:: ana\n", 3),
    ("```python\nx = 1\n```\n\nowner:: ana\n", 5),
])
def test_a_field_line_that_attaches_to_nothing_fails_the_build(tmp_path: Path, note: str, line: int) -> None:
    with pytest.raises(DocumentError) as error:
        _content(tmp_path, note)
    assert f"design.md: line {line}, owner::: attaches to no block" in str(error.value)
    assert OWNER in str(error.value)


def test_a_key_set_twice_on_one_block_fails_the_build(tmp_path: Path) -> None:
    with pytest.raises(DocumentError) as error:
        _content(tmp_path, "Text.\nowner:: ana\nowner:: bo\n")
    assert "design.md: line 3, owner::" in str(error.value) and OWNER in str(error.value)


def _node_validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    registry = Registry().with_resource(schema["$id"], Resource.from_contents(schema)) if "$id" in schema else Registry()
    return Draft202012Validator({"$ref": "#/$defs/node", "$defs": schema["$defs"]}, registry=registry)


def test_the_schema_validates_fields_and_effective_on_block_and_section_nodes() -> None:
    validator = _node_validator()
    node = {"type": "section", "attrs": {"level": 2}, "id": "section-1", "children": [],
            "fields": {"review.owner": "ana", "state": None},
            "effective": {"review.owner": {"value": "ana", "node": "section-1"},
                          "tags": {"value": ["a"], "frontmatter": True}}}
    assert list(validator.iter_errors(node)) == []
    for broken in (
        {"fields": {"bad key": "x"}},
        {"fields": {"owner": ["a"]}},
        {"effective": {"owner": {"value": "ana"}}},
        {"effective": {"owner": {"value": "ana", "node": "section-1", "frontmatter": True}}},
    ):
        assert list(validator.iter_errors({**copy.deepcopy(node), **broken})), broken
    without_id = {key: value for key, value in node.items() if key != "id"}
    assert list(validator.iter_errors(without_id))
    without_effective = {key: value for key, value in node.items() if key != "effective"}
    assert list(validator.iter_errors(without_effective))
