"""Block and section embeds: the nodes an embed of ``note#^name`` or ``note#Heading`` shows, the
message for one that names nothing, and the embeds that show each other
(capabilities/embeds#Block and section embeds).

Pure: Document nodes in, nodes and messages out. ``vault.py`` checks the embeds of a build with
these functions, and ``document.py`` names each shown section by its id once ids are assigned.
"""
from __future__ import annotations

import re
from typing import Any, Iterator, NamedTuple

from obs.node_ids import CONTAINERS


OWNER = "capabilities/embeds"
LISTED = 10
"""How many block ids or headings the remedy of a missing target lists."""
_TRAILING = re.compile(r"(?:^|\s)\^[A-Za-z0-9-]+\s*$")
Node = dict[str, Any]


class Shown(NamedTuple):
    """A fragment embed of a build: its attributes, its note's path, the embed as written and the
    nodes it shows."""
    attrs: Node
    note: str
    written: str
    nodes: list[Node]


def shown(nodes: list[Node], fragment: str, named: dict[str, Node]) -> list[Node] | None:
    """The nodes of ``nodes`` (a chapter's content) that the fragment shows, or None where it names
    nothing: for ``^name`` the block ``named`` maps it to, a heading's section for a heading's
    name; for a heading, the section of the first heading a link to it reaches."""
    if fragment.startswith("^"):
        node = named.get(fragment[1:])
        if node is None:
            return None
        if node["type"] != "section":
            return [node]
        siblings = next(found for found in _lists(nodes) if any(item is node for item in found))
        return section(siblings, next(index for index, item in enumerate(siblings) if item is node))
    wanted = slug(fragment)
    for siblings, index in headings(nodes):
        if slug(heading_text(siblings[index])) == wanted:
            return section(siblings, index)
    return None


def section(siblings: list[Node], index: int) -> list[Node]:
    """The heading at ``index`` of ``siblings`` and the blocks after it, up to the next heading of the
    same or a higher level."""
    level = _level(siblings[index])
    end = next((at for at in range(index + 1, len(siblings))
                if siblings[at]["type"] == "section" and _level(siblings[at]) <= level), len(siblings))
    return siblings[index:end]


def headings(nodes: list[Node]) -> Iterator[tuple[list[Node], int]]:
    """Each heading a heading link reaches, as its sibling list and its index there: the chapter's
    own, and those in a columns block's columns, in document order."""
    for index, node in enumerate(nodes):
        if node["type"] == "section":
            yield nodes, index
        elif node["type"] == "columns":
            for column in node["children"]:
                yield from headings(column["children"])


def heading_text(node: Node) -> str:
    """A heading's text as a link to it reads it: its plain text without a trailing ``^name``."""
    return _TRAILING.sub("", _plain(node)).strip()


def slug(value: str) -> str:
    """The text lower-cased, every run of characters other than letters and digits one dash."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def missing(fragment: str, note: str, nodes: list[Node], named: dict[str, Node]) -> tuple[str, str]:
    """The problem and remedy of an embed whose fragment names nothing in ``note``."""
    if fragment.startswith("^"):
        problem = f"names the block id {fragment}, which no block of {note} carries"
        names = [f"^{name}" for name in named]
        remedy = (f"Embed one of its block ids, {_listed(names)}, or add {fragment} to a block there" if names
                  else f"{note} has no block id; add one there, a ^name at the end of a block or on the line "
                       "after it, and embed it")
    else:
        problem = f"names the heading {fragment}, which {note} lacks"
        names = [heading_text(siblings[index]) for siblings, index in headings(nodes)]
        remedy = (f"Embed one of its headings, {_listed(names)}, or correct the heading" if names
                  else f"{note} has no heading; add one there, or embed the note whole")
    return problem, f"{remedy}; see {OWNER}"


def cycle(embeds: list[Shown]) -> list[Shown] | None:
    """The first embeds of ``embeds`` that show each other, in the order they show each other,
    each once, starting with the earliest; None where none do. An embed shows the fragment embeds
    in the block positions of the nodes it shows."""
    by_attrs = {id(embed.attrs): embed for embed in embeds}
    done: set[int] = set()

    def visit(embed: Shown, path: list[Shown]) -> list[Shown] | None:
        if any(item is embed for item in path):
            return path[next(index for index, item in enumerate(path) if item is embed):]
        if id(embed.attrs) in done:
            return None
        path.append(embed)
        for node in _blocks(embed.nodes):
            inner = by_attrs.get(id(node["attrs"])) if node["type"] == "embeds" else None
            found = inner and visit(inner, path)
            if found:
                return found
        path.pop()
        done.add(id(embed.attrs))
        return None

    for embed in embeds:
        found = visit(embed, [])
        if found:
            return found
    return None


def cycle_problem(found: list[Shown]) -> tuple[str, str]:
    """The problem and remedy of embeds that show each other, as the first of ``found`` names them."""
    if len(found) == 1:
        problem = "shows itself: it sits in the block or section it shows"
    else:
        rest = [f"{embed.note}: {embed.written}" for embed in [*found[1:], found[0]]]
        problem = f"shows {', which shows '.join(rest)} again"
    return problem, f"Link one of them instead, without the ! before it; see {OWNER}"


def assign_sections(document: Node) -> None:
    """Give each heading embed its ``block``, the id of the section it shows; call once ids are
    assigned (node_ids.assign_ids) and the vault has checked that every one names a heading."""
    contents = {"home": document["manifest"].get("abstract", [])}
    contents.update({chapter["id"]: chapter["content"] for chapter in _chapters(document["chapters"])})
    for node in _embeds(document):
        attrs = node["attrs"]
        heading, chapter = attrs.get("heading"), attrs.get("chapter")
        if heading and not heading.startswith("^") and chapter in contents:
            found = shown(contents[chapter], heading, {})
            if found:
                attrs["block"] = found[0]["id"]


def _embeds(value: object) -> Iterator[Node]:
    if isinstance(value, dict):
        if value.get("type") == "embeds" and isinstance(value.get("attrs"), dict):
            yield value
        for item in value.values():
            yield from _embeds(item)
    elif isinstance(value, list):
        for item in value:
            yield from _embeds(item)


def _chapters(chapters: list[Node]) -> Iterator[Node]:
    for chapter in chapters:
        yield chapter
        yield from _chapters(chapter["children"])


def _lists(nodes: list[Node]) -> Iterator[list[Node]]:
    """``nodes`` and every list of block children below them."""
    yield nodes
    for node in nodes:
        if node["type"] in CONTAINERS:
            yield from _lists(node["children"])


def _blocks(nodes: list[Node]) -> Iterator[Node]:
    """Every node in a block position of ``nodes``, in document order."""
    for node in nodes:
        yield node
        if node["type"] in CONTAINERS:
            yield from _blocks(node["children"])


def _level(node: Node) -> int:
    return int(node["attrs"].get("level", 1))


def _plain(node: Node) -> str:
    return node.get("text", "") + "".join(
        _plain(child) if child["type"] != "wikilinks" else child["attrs"].get("label", "")
        for child in node["children"])


def _listed(names: list[str]) -> str:
    return ", ".join(names[:LISTED]) + (f" and {len(names) - LISTED} more" if len(names) > LISTED else "")
