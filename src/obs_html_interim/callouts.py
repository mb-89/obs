"""Obsidian callouts: blockquotes whose first line is ``[!type]``, rendered as content cards."""
from __future__ import annotations

import re

from markdown_it.token import Token

# Canonical type: (tone, Obsidian aliases). Tones are the shared semantic card colors.
TYPES: dict[str, tuple[str, tuple[str, ...]]] = {
    "note": ("accent", ()),
    "abstract": ("accent", ("summary", "tldr")),
    "info": ("accent", ()),
    "todo": ("accent", ()),
    "tip": ("accent", ("hint",)),
    "success": ("success", ("check", "done")),
    "question": ("warning", ("help", "faq")),
    "warning": ("warning", ("caution", "attention")),
    "failure": ("failure", ("fail", "missing")),
    "danger": ("failure", ("error",)),
    "bug": ("failure", ()),
    "example": ("accent", ()),
    "quote": ("neutral", ("cite",)),
    # This document's established untitled emphasis box, not Obsidian's alias of tip.
    "important": ("accent", ()),
}
CANONICAL = {alias: kind for kind, (_, aliases) in TYPES.items() for alias in (kind, *aliases)}
MARKER = re.compile(r"\[!(?P<keyword>[A-Za-z]+)\](?P<fold>[+-]?)(?:[ \t]+|$)")


def marker(line: str) -> re.Match[str] | None:
    """Return the callout marker at the start of a blockquote's first line, if any."""
    match = MARKER.match(line)
    return match if match and match["keyword"].lower() in CANONICAL else None


def decorate_callouts(tokens: list[Token]) -> None:
    """Turn callout blockquotes into ``aside`` cards with a title header, in place."""
    pairs: list[tuple[int, Token]] = []
    quotes: list[int] = []
    for index, token in enumerate(tokens):
        if token.type == "blockquote_open":
            quotes.append(index)
        elif token.type == "blockquote_close":
            pairs.append((quotes.pop(), token))
    # Inserted title tokens only shift later indices, so decorate the last opening first.
    for opening, closing in sorted(pairs, key=lambda pair: pair[0], reverse=True):
        _decorate(tokens, opening, closing)


def _decorate(tokens: list[Token], opening: int, end: Token) -> None:
    if tokens[opening + 1].type != "paragraph_open":
        return
    inline = tokens[opening + 2]
    children = inline.children or []
    if inline.type != "inline" or not children or children[0].type != "text":
        return
    match = marker(children[0].content)
    if not match:
        return
    if (not match.group().endswith((" ", "\t")) and len(children) > 1
            and children[1].type not in {"softbreak", "hardbreak"}):
        return
    keyword = match["keyword"].lower()
    kind = CANONICAL[keyword]
    tone = TYPES[kind][0]
    line_end = next((position for position, child in enumerate(children)
                     if child.type in {"softbreak", "hardbreak"}), len(children))
    title = children[:line_end]
    remainder = title[0].content[match.end():]
    title = ([_text(remainder)] if remainder else []) + title[1:]
    if not any(child.content.strip() or child.type != "text" for child in title):
        title = [] if kind == "important" else [_text(keyword[0].upper() + keyword[1:])]
    body = children[line_end + 1:]

    start = tokens[opening]
    start.tag = end.tag = "aside"
    if kind == "important":
        start.attrSet("class", "content-card content-emphasis")
    else:
        start.attrSet("class", f"content-card content-callout content-callout--{tone}")
        start.attrSet("data-callout", kind)
    start.attrSet("aria-label", kind[0].upper() + kind[1:])
    inline.children = body
    inline.content = inline.content.partition("\n")[2]
    if not body:
        tokens[opening + 1].hidden = tokens[opening + 3].hidden = True
    if title:
        header = Token("callout_title_open", "header", 1, block=True, level=start.level + 1)
        header.attrSet("class", "content-card-title")
        text = Token("inline", "", 0, level=start.level + 2, children=title)
        tokens[opening + 1:opening + 1] = [
            header, text, Token("callout_title_close", "header", -1, block=True, level=start.level + 1),
        ]


def _text(content: str) -> Token:
    return Token("text", "", 0, content=content)
