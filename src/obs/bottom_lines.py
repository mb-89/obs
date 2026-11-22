"""Bottom lines: a note's one ``[!bluf]`` callout, the problems that keep one from being a bottom
line, and the ``bottomLine`` the Document names for it (input-model#Bottom lines).

Pure: Document nodes in, nodes, names and messages out. ``vault.py`` checks each note's bottom line
with these functions, and ``document.py`` names it on its chapter or the manifest once ids are
assigned.
"""
from __future__ import annotations

from typing import Any, Iterator, NamedTuple


KIND = "bluf"
OWNER = "input-model#Bottom lines"
Node = dict[str, Any]
_INSIDE = {
    "list-item": "list item", "quote": "quote", "callouts": "callout", "table": "table",
    "columns": "columns block", "cards-metrics": "card",
}
"""The block nodes a bottom line may not sit in, as a message names them; ``list`` and a column's or
card's ``document`` are passed through to the item, columns block or card that holds them."""
_BLOCKS = {
    "section": "a heading", "list": "a list", "quote": "a quote", "callouts": "a callout",
    "table": "a table", "code": "a code block", "math": "display math", "rule": "a rule",
    "figures": "a figure", "embeds": "an embed", "registers": "a register", "bases": "a base",
    "cards-metrics": "a cards fence", "columns": "a columns block",
}
"""What a message calls the block a bottom line's body begins with, where it is no paragraph."""


class Found(NamedTuple):
    """A ``[!bluf]`` callout of a note: its node and the block it sits inside, or None in the note's
    own flow."""
    node: Node
    inside: str | None


def found(nodes: list[Node]) -> list[Found]:
    """Each ``[!bluf]`` callout of ``nodes`` (a note's content), in document order, with the
    innermost block it sits inside."""
    return list(_found(nodes, None))


def _found(nodes: list[Node], inside: str | None) -> Iterator[Found]:
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("children"), list):
            continue
        if is_bottom_line(node):
            yield Found(node, inside)
        yield from _found(node["children"], _INSIDE.get(node.get("type"), inside))


def is_bottom_line(node: Node) -> bool:
    """Whether ``node`` is a ``[!bluf]`` callout."""
    return node.get("type") == "callouts" and node.get("attrs", {}).get("kind") == KIND


def problem(callouts: list[Found], places: list[str]) -> tuple[str, str, str] | None:
    """The field, problem and remedy of the input error ``callouts`` (one note's, ``found``'s answer)
    make, each placed by ``places`` (``line 3``, ``cards fence 1``), or None where they make a bottom
    line or none."""
    for (_, inside), place in zip(callouts, places):
        if inside is not None:
            return (f"[!{KIND}] callout, {place}", f"it sits inside a {inside}, and a bottom line belongs "
                    "to the note itself", f"Move it out; see {OWNER}")
    if len(callouts) > 1:
        return (f"[!{KIND}] callouts, {_lines(places[:2])}", "a note has one bottom line",
                f"Keep one, and make the other another callout type or a link to it; see {OWNER}")
    if callouts and lead(callouts[0].node) is None:
        children = callouts[0].node["children"]
        begins = _BLOCKS.get(children[0].get("type"), f"a {children[0].get('type')} block") if children \
            else "nothing"
        return (f"[!{KIND}] callout, {places[0]}", f"its body begins with {begins}, so no first paragraph "
                "can go up a level", "Begin the body with one short paragraph; the marker line holds only "
                f"the title; see {OWNER}")
    return None


def _lines(places: list[str]) -> str:
    """``line 3`` and ``line 8`` as ``lines 3 and 8``; other places joined as they are."""
    if all(place.startswith("line ") for place in places):
        return "lines " + " and ".join(place.removeprefix("line ") for place in places)
    return " and ".join(places)


def lead(callout: Node) -> Node | None:
    """A bottom line's lead, the first block of its body where it is a paragraph, else None."""
    children = callout.get("children") or []
    return children[0] if children and children[0].get("type") == "paragraph" else None


def bottom_line(nodes: list[Node]) -> dict[str, str] | None:
    """The ``bottomLine`` of a note's content whose ids are assigned: its bottom line's id and its
    lead's, or None without one. The vault has checked that there is at most one, in the note's own
    flow, with a lead."""
    for node in nodes:
        if is_bottom_line(node):
            return {"callout": node["id"], "lead": lead(node)["id"]}
    return None


def assign(document: Node) -> None:
    """Name each chapter's bottom line, and the abstract's on the manifest, as ``bottomLine``; call
    once ids are assigned (node_ids.assign_ids)."""
    manifest = document["manifest"]
    named = bottom_line(manifest.get("abstract", []))
    if named is not None:
        manifest["bottomLine"] = named
    for chapter in _chapters(document["chapters"]):
        named = bottom_line(chapter["content"])
        if named is not None:
            chapter["bottomLine"] = named


def _chapters(chapters: list[Node]) -> Iterator[Node]:
    for chapter in chapters:
        yield chapter
        yield from _chapters(chapter["children"])
