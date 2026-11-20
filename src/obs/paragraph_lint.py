"""The long-paragraph lint (input-model, Long paragraphs): a paragraph whose prose, wrapped at a
line width, runs over a number of lines warns. It reads a note's Markdown tokens and returns
warnings; it never changes the Document.

The estimate is the interim adapter's: the paragraph's text and inline code pieces, joined by
spaces, without a piece that starts with a paragraph mark and without a callout's marker, wrapped
with textwrap. A wikilink counts as its link text; an image embed counts nothing.
"""
from __future__ import annotations

import mimetypes
import re
from collections.abc import Callable, Mapping, Sequence
from textwrap import wrap

from markdown_it.token import Token

from obs.input import _CALLOUT_MARKER, _CALLOUT_NAMES


OWNER = "see input-model#Long paragraphs"
_LINK = re.compile(r"(?P<embed>!)?\[\[(?P<target>[^\]|]+)(?:\|(?P<label>[^\]]+))?\]\]")
_FILE = re.compile(r"\.[A-Za-z0-9]{1,10}$")


def _items(children: Sequence[Token], labels: Mapping[tuple[str, str], str]) -> list[tuple[str, str]]:
    """The paragraph's inline content as the interim's tokens hold it: ("text", ...) for text
    (strikethrough marks included, as the interim reads no strikethrough), ("piece", ...) for inline
    code and a wikilink's visible text, ("break", "") for any other token."""
    items: list[tuple[str, str]] = []
    for child in children:
        if child.type in {"s_open", "s_close"}:
            items.append(("text", child.markup))
        elif child.type == "code_inline":
            items.append(("piece", child.content))
        elif child.type != "text":
            items.append(("break", ""))
        else:
            position = 0
            for match in _LINK.finditer(child.content):
                target = match["target"].strip()
                name = target.partition("#")[0].strip()
                suffix = name[name.rfind("."):].casefold() if _FILE.search(name) else ""
                file = suffix not in {"", ".md", ".base"}
                embed = match["embed"] is not None and file  # A note embed's "!" stays text.
                items.append(("text", child.content[position:match.start() + (0 if embed else len(match["embed"] or ""))]))
                if embed and (mimetypes.guess_type(name)[0] or "").startswith("image/"):
                    items.append(("break", ""))
                else:
                    note, _, heading = target.partition("#")
                    shown = labels.get((note.strip(), heading)) if not file else None
                    items.append(("piece", (match["label"] or shown or target.rsplit("/", 1)[-1].removesuffix(".md")).strip()))
                position = match.end()
            items.append(("text", child.content[position:]))
    return items


def _pieces(children: Sequence[Token], labels: Mapping[tuple[str, str], str]) -> list[str]:
    """The paragraph's text and inline code pieces; adjacent text is one piece, as markdown-it joins it."""
    pieces: list[str] = []
    run: str | None = None
    for kind, content in _items(children, labels) + [("break", "")]:
        if kind == "text":
            run = (run or "") + content
            continue
        if run:
            pieces.append(run)
        run = None
        if kind == "piece":
            pieces.append(content)
    return pieces


def paragraph_warnings(tokens: Sequence[Token], line: Callable[[int], int | None],
                       labels: Mapping[tuple[str, str], str], warning_lines: int,
                       line_characters: int) -> list[tuple[int | None, str]]:
    """The lint's findings in one note's tokens: each long paragraph with the note line ``line``
    gives for its 0-based body line, and its message. ``labels`` holds what an unlabelled wikilink
    shows, by its target and heading: the linked note's title, then " > " and the heading."""
    findings: list[tuple[int | None, str]] = []
    for index, token in enumerate(tokens):
        if token.type != "inline" or index == 0 or tokens[index - 1].type != "paragraph_open":
            continue
        text = " ".join(piece for piece in _pieces(token.children or [], labels) if not piece.startswith("#mark/"))
        callout = _CALLOUT_MARKER.match(text)
        if callout and callout["keyword"].lower() in _CALLOUT_NAMES and tokens[index - 2].type == "blockquote_open":
            text = text[callout.end():]
        lines = len(wrap(text.strip(), width=line_characters))
        if lines > warning_lines:
            findings.append((line(token.map[0]) if token.map else None,
                             f"long paragraph ({lines} estimated lines at {line_characters} characters; "
                             f"maximum {warning_lines}). Split it into shorter paragraphs; {OWNER}."))
    return findings
