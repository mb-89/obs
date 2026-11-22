"""Block fields: whole ``key:: value`` lines of a paragraph, the block or section each attaches to,
and the values each block resolves from its own fields, its containers, its sections and its
note's front matter (input-model#Block fields).

``vault.py`` takes the lines out of the tokens and attaches them as the nodes are built, with
``take_lines`` and ``attach``; ``document.py`` resolves ``effective`` with ``resolve`` once the
node ids are assigned. ``document.schema.json`` states ``fields`` and ``effective``.
"""
from __future__ import annotations

import datetime
import re
from typing import Any, Iterator

from markdown_it.token import Token
import yaml

from obs.node_ids import CONTAINERS, IDENTIFIED, _alone
from obs.note import parser


OWNER = "input-model#Block fields"
LINE = re.compile(r"[ \t]*(?P<key>[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)*)::(?:[ \t]+(?P<value>.*?))?[ \t]*")
"""A field line: a dotted key, ``::``, and the value after a space, or nothing (unset)."""
FOLLOWED = frozenset({"table", "list", "quote", "callouts", "section"})
"""The blocks a paragraph made only of field lines right after them belongs to."""
PENDING = "block-fields"
"""The type of the stand-in a paragraph made only of field lines leaves first in a block list, which
the container that holds the list adopts (``adopt``); one no container adopts attaches to nothing."""
Node = dict[str, Any]


class FieldLineError(ValueError):
    """A field line the build refuses: its key, the 0-based line of the parsed text, the problem and
    the remedy, which ``vault.py`` turns into the core's one error form."""

    def __init__(self, key: str, line: int | None, problem: str, remedy: str) -> None:
        super().__init__(f"{key}:: {problem}. {remedy}.")
        self.key, self.line, self.problem, self.remedy = key, line, problem, remedy


def scalar(text: str | None) -> object:
    """A field line's value: None for an empty one (unset), else the YAML scalar the text is, or the
    text itself where YAML reads it as no single scalar."""
    if text is None or not text.strip():
        return None
    try:
        value = yaml.safe_load(text)
    except (yaml.YAMLError, ValueError):
        return text
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    if value is None or isinstance(value, (list, dict)) or isinstance(value, float) and value != value:
        return text
    return value if isinstance(value, (str, int, float, bool)) else text


def take_lines(tokens: list[Token], columns: bool, env: dict[str, Any]) -> None:
    """Take every paragraph's field lines out of its inline token, re-reading the rest as inline
    content with the note reader's ``parser(columns)`` and the parse's ``env``, and record them on
    the paragraph's opening token: ``meta["fields"]`` (key -> value),
    ``meta["fieldLine"]`` (the 0-based line of its first field line) and ``meta["fieldsOnly"]``,
    whether nothing but a ``^name`` line is left."""
    for opening, inline in zip(tokens, tokens[1:]):
        if opening.type != "paragraph_open" or inline.type != "inline" or "::" not in inline.content:
            continue
        start = opening.map[0] if opening.map else None
        fields: dict[str, object] = {}
        kept: list[str] = []
        first = None
        for index, text in enumerate(inline.content.split("\n")):
            match = LINE.fullmatch(text)
            if match is None:
                kept.append(text)
                continue
            line = None if start is None else start + index
            if match["key"] in fields:
                raise FieldLineError(match["key"], line, "sets a key its paragraph sets already",
                                     f"Set each key once per block; see {OWNER}")
            first = line if first is None else first
            fields[match["key"]] = scalar(match["value"])
        if not fields:
            continue
        rest = "\n".join(kept)
        inline.content = rest
        inline.children = parser(columns).parseInline(rest, env)[0].children if rest.strip() else []
        opening.meta = {**(opening.meta or {}), "fields": fields, "fieldLine": first,
                        "fieldsOnly": not rest.strip() or len(kept) == 1 and _alone(
                            {"type": "paragraph", "children": [{"type": "text", "text": rest}]}) is not None}


def attach(opening: Token, built: list[Node], result: list[Node]) -> None:
    """Attach the field lines ``opening`` holds: to the first node its paragraph ``built``, or, for a
    paragraph made only of them, to the table, list, quote, callout or section right before it in
    ``result`` (past ``^name`` lines), else to a ``PENDING`` stand-in first in ``result``."""
    meta = opening.meta or {}
    if "fields" not in meta:
        return
    fields, line = meta["fields"], meta["fieldLine"]
    if not meta["fieldsOnly"] and built:
        _set(built[0], fields, line)
        return
    previous = next((node for node in reversed(result) if _alone(node) is None), None)
    if previous is None:
        result.insert(0, {"type": PENDING, "attrs": {"line": line}, "children": [], "fields": fields})
    elif previous["type"] in FOLLOWED:
        _set(previous, fields, line)
    else:
        key = next(iter(fields))
        raise FieldLineError(key, line, f"attaches to no block: a paragraph of field lines after a "
                             f"{previous['type']} belongs to nothing",
                             "Write the field lines inside the paragraph they describe, or right after a table, "
                             f"a list, a quote, a callout or a heading; see {OWNER}")


def adopt(container: Node) -> Node:
    """The container, with the fields of a ``PENDING`` stand-in first among its children."""
    children = container["children"]
    if children and children[0]["type"] == PENDING:
        pending = children.pop(0)
        _set(container, pending["fields"], pending["attrs"]["line"])
    return container


def unattached(nodes: list[Node]) -> None:
    """Refuse a ``PENDING`` stand-in no container adopted: field lines that attach to nothing."""
    for node in _blocks(nodes):
        if node["type"] == PENDING:
            raise FieldLineError(next(iter(node["fields"])), node["attrs"]["line"],
                                 "attaches to no block: no table, list, quote, callout, heading or paragraph "
                                 "holds it", "Write the field lines inside the paragraph they describe, or right "
                                 f"after a table, a list, a quote, a callout or a heading; see {OWNER}")


def _set(node: Node, fields: dict[str, object], line: int | None) -> None:
    own = node.setdefault("fields", {})
    for key, value in fields.items():
        if key in own:
            raise FieldLineError(key, line, "sets a key its block sets already",
                                 f"Set each key once per block; see {OWNER}")
        own[key] = value


def _blocks(nodes: list[Node]) -> Iterator[Node]:
    for node in nodes:
        yield node
        if node["type"] in CONTAINERS:
            yield from _blocks(node["children"])


def resolve(document: dict[str, Any]) -> None:
    """Give each block node in reach of a field line its ``effective`` values: the abstract's from
    the manifest's front matter, a chapter's from its note's."""
    manifest = document["manifest"]
    if "abstract" in manifest:
        _resolve(manifest["abstract"], frontmatter(manifest.get("metadata") or {}))
    for chapter in _chapters(document["chapters"]):
        _resolve(chapter["content"], frontmatter(chapter.get("metadata") or {}))


def frontmatter(metadata: dict[str, Any], prefix: str = "") -> dict[str, Node | None]:
    """A note's front matter as the outermost effective values: each dotted key, nested mappings
    flattened, with ``{value, frontmatter: true}``."""
    flat: dict[str, Node | None] = {}
    for key, value in metadata.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            flat.update(frontmatter(value, f"{name}."))
        else:
            flat[name] = {"value": value, "frontmatter": True}
    return flat


def values(effective: dict[str, Node]) -> dict[str, object]:
    """A block's effective values as the mapping the query conditions read, as they read front
    matter (``selection.conditions_select``)."""
    return {key: entry["value"] for key, entry in effective.items()}


def _chapters(chapters: list[Node]) -> Iterator[Node]:
    for chapter in chapters:
        yield chapter
        yield from _chapters(chapter["children"])


Scope = tuple[dict[str, Node | None], bool]
"""The values in reach, nearest first, None for an unset key, and whether a field line is in reach."""


def _resolve(nodes: list[Node], base: dict[str, Node | None], reached: bool = False) -> None:
    sections: list[tuple[int, Scope]] = []
    for node in nodes:
        if node["type"] == "section":
            level = node["attrs"].get("level", 1)
            while sections and sections[-1][0] >= level:
                sections.pop()
        outer = sections[-1][1] if sections else (base, reached)
        scope = _own(node, outer)
        if node["type"] in IDENTIFIED and scope[1]:
            node["effective"] = {key: entry for key, entry in scope[0].items() if entry is not None}
        if node["type"] == "section":
            sections.append((node["attrs"].get("level", 1), scope))
        elif node["type"] in CONTAINERS:
            _resolve(node["children"], *scope)


def _own(node: Node, outer: Scope) -> Scope:
    own = node.get("fields")
    if not own:
        return outer
    return ({**outer[0], **{key: None if value is None else {"value": value, "node": node["id"]}
                             for key, value in own.items()}}, True)
