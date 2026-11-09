"""Block node ids: explicit Obsidian block references, else derived from the block's own text
(input-model#Block node ids).

The core assigns them after the note reader, so every adapter gets the same ids; comments and sync
records target them. ``document.schema.json`` (``$defs/identifiedType``) owns which types carry one.
"""
import copy
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterator

from obs.input import input_error


OWNER = "input-model#Block node ids"
IDENTIFIED = frozenset(json.loads(Path(__file__).with_name("document.schema.json").read_text(encoding="utf-8"))
                       ["$defs"]["identifiedType"]["enum"])
CONTAINERS = frozenset({"list", "list-item", "quote", "callouts", "table", "cards-metrics", "document"})
"""The block nodes whose children are blocks in turn; any other node's children are its content."""
ANCHORED = CONTAINERS - {"list-item"}
"""The containers whose derived id is anchored on their heading, not hashed over their children; a
list item's first paragraph is its own text (input-model#Derived ids)."""
KEYED_TABLES = frozenset({"registers", "bases"})
"""The tables whose rows are records, each keyed ``<table id>:<record id>``."""
AUTHORED_ATTRS = ("source", "target", "heading", "label", "kind", "caption", "alt", "title", "level",
                  "language", "ordered", "view", "category", "id")
"""The attributes that are authored content, part of a block's normalized text; what a build
computes (a command's ``output``, a register's ``rows``, a link's resolved ``chapter``) is not."""
_TRAILING = re.compile(r"(?:^|\s)\^([A-Za-z0-9-]+)\s*$")
_ALONE = re.compile(r"\s*\^([A-Za-z0-9-]+)\s*")


def assign_ids(document: dict[str, Any]) -> None:
    """Give every identified block node of the abstract and of each chapter its ``id``."""
    manifest = document["manifest"]
    paths = _chapter_paths(document["records"])
    if "abstract" in manifest:
        _assign(manifest["abstract"], manifest["path"])
    for chapter in _chapters(document["chapters"]):
        _assign(chapter["content"], paths.get(chapter["id"], f"chapter {chapter['id']}"))


def block_names(nodes: list[dict[str, Any]], source: str) -> set[str]:
    """The explicit ids of a chapter's or the abstract's blocks, its block link targets
    (capabilities/wikilinks), read as ``assign_ids`` reads them, leaving ``nodes`` as they are."""
    explicit: dict[int, str] = {}
    _read_references(copy.deepcopy(nodes), None, explicit, source)
    return set(explicit.values())


def chapter_targets(document: dict[str, Any]) -> dict[str, set[str]]:
    """Each chapter's node targets: its block ids and the keys of its keyed rows."""
    records = [record["id"] for record in document["records"]]
    return {chapter["id"]: set(_targets(chapter["content"], records)) for chapter in _chapters(document["chapters"])}


def _targets(nodes: list[dict[str, Any]], records: list[str]) -> Iterator[str]:
    for node in _blocks(nodes):
        if "id" not in node:
            continue
        yield node["id"]
        if node["type"] == "registers":
            yield from (f"{node['id']}:{record}" for rows in node["attrs"]["rows"] for record in rows)
        elif node["type"] == "bases":  # The adapter selects a Base fence's rows: any record may be one.
            yield from (f"{node['id']}:{record}" for record in records)


def _chapters(chapters: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for chapter in chapters:
        yield chapter
        yield from _chapters(chapter["children"])


def _chapter_paths(records: list[dict[str, Any]]) -> dict[str, str]:
    """Each chapter's note path, by chapter id, for the messages."""
    notes = {record["id"]: record.get("path") for record in records if record["type"] == "note"}
    return {record["fields"]["slug"]: notes.get(record.get("note"))
            for record in records if record["type"] == "chapter" and notes.get(record.get("note"))}


def _blocks(nodes: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Every node in a block position, in document order."""
    for node in nodes:
        yield node
        if node["type"] in CONTAINERS:
            yield from _blocks(node["children"])


def _assign(nodes: list[dict[str, Any]], source: str) -> None:
    explicit: dict[str, str] = {}
    _read_references(nodes, None, explicit, source)
    taken, seen, heading = set(explicit.values()), Counter(), ""
    for node in _blocks(nodes):
        if node["type"] not in IDENTIFIED:
            continue
        if id(node) in explicit:
            node["id"] = explicit[id(node)]
        else:
            text = f"{_own(node)}\0heading={heading}" if node["type"] in ANCHORED else _normalized(node)
            node["id"] = _derived(f"{node['type']}-{hashlib.sha256(text.encode()).hexdigest()[:8]}", taken, seen)
        if node["type"] == "section":
            heading = node["id"]


def _derived(base: str, taken: set[str], seen: Counter) -> str:
    """``base``, or numbered after the identical blocks before it and any explicit id it equals."""
    identifier = base
    while identifier in taken:
        seen[base] += 1
        identifier = f"{base}-{seen[base] + 1}"
    taken.add(identifier)
    return identifier


def _read_references(nodes: list[dict[str, Any]], item: dict[str, Any] | None, explicit: dict[int, str],
                     source: str) -> None:
    """Take each Obsidian block reference out of the text into ``explicit`` (block -> name): a
    paragraph's trailing ``^name`` names it, or ``item`` for a list item's first paragraph; a
    heading's names the heading; a paragraph that is only ``^name`` names the block before it. A
    figure's ``^name`` is its block."""
    index = 0
    while index < len(nodes):
        node = nodes[index]
        alone = _alone(node)
        if alone and index > 0:
            _name(nodes[index - 1], alone, explicit, source)
            del nodes[index]
            continue
        if node["type"] == "figures" and "block" in node["attrs"]:
            _name(node, node["attrs"]["block"], explicit, source)
        elif node["type"] in ("paragraph", "section"):
            name = _strip_trailing(node)
            if name:
                named = item if item is not None and index == 0 and node["type"] == "paragraph" else node
                _name(named, name, explicit, source)
        if node["type"] in CONTAINERS:
            _read_references(node["children"], node if node["type"] == "list-item" else None, explicit, source)
        index += 1


def _name(node: dict[str, Any], name: str, explicit: dict[int, str], source: str) -> None:
    if name in explicit.values():
        raise input_error(source, f"^{name}", "names two blocks of this chapter",
                          f"Give each block its own block reference; see {OWNER}")
    explicit[id(node)] = name


def _alone(node: dict[str, Any]) -> str | None:
    """The name of a paragraph that is only a block reference."""
    if node["type"] != "paragraph" or len(node["children"]) != 1 or node["children"][0]["type"] != "text":
        return None
    match = _ALONE.fullmatch(node["children"][0]["text"])
    return match[1] if match else None


def _strip_trailing(block: dict[str, Any]) -> str | None:
    """Remove a trailing ``^name`` from a paragraph's or heading's last text node; its name."""
    children = block["children"]
    if not children or children[-1]["type"] != "text":
        return None
    last = children[-1]
    match = _TRAILING.search(last["text"])
    if not match:
        return None
    last["text"] = last["text"][:match.start()].rstrip()
    while children and children[-1]["type"] in ("text", "break") and not children[-1].get("text", "").strip():
        children.pop()
    return match[1]


def _normalized(node: dict[str, Any]) -> str:
    """A block's authored content with whitespace runs collapsed (input-model#Block node ids)."""
    return " ".join(_content(node).split())


def _own(node: dict[str, Any]) -> str:
    """A container's own authored content: its attributes, none of its children's text, which a
    cards fence's ``source`` holds too."""
    attrs = {key: value for key, value in node["attrs"].items() if key != "source"}
    return " ".join(_content({**node, "attrs": attrs, "children": []}).split())


def _content(node: dict[str, Any]) -> str:
    """A node's authored content: its authored attributes, its text, then its children's content,
    inline children run together and block children and cells kept apart by a separator."""
    parts = []
    for key in AUTHORED_ATTRS:
        value = node["attrs"].get(key)
        if isinstance(value, list):
            value = "".join(_content(child) for child in value if isinstance(child, dict))
        elif value is None or isinstance(value, dict):
            continue
        parts.append(f"\0{key}={json.dumps(value)}\0")
    parts.append(node.get("text", ""))
    if node["type"] != "figures":  # A figure's one child is its kind's body, which a build renders.
        separator = "\0" if node["type"] in CONTAINERS or node["type"] == "table-row" else ""
        parts.append(separator.join(_content(child) for child in node["children"]))
    return "".join(parts)
