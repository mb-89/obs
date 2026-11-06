"""The figure lint: what an author writes around figures that the figure contract replaces
(input-model, Figure captions and references). It reads a note's Markdown tokens and returns
warnings; it never changes the Document.

Every figure has a caption inside the figure: a `figure` fence without `caption` warns, and so
does an image alone in its paragraph (an image file; `![...]` of another file is an attachment). A paragraph directly before or after a figure that acts as
its caption (italic-only, or starting with a figure label and a number) warns. Prose that names a
figure by label and number warns and suggests the block link of the figure it most likely means:
the core knows no numbers, so that is the note's figure at the position the number's last
component gives.
"""
from __future__ import annotations

import mimetypes
import re
from collections.abc import Callable, Sequence

import yaml
from markdown_it.token import Token

from obs.note import parser


OWNER = "see input-model#Figure captions and references"
_BLOCK_ID = re.compile(r"\^([A-Za-z0-9-]+)")


def _fences(tokens: Sequence[Token]) -> list[tuple[int, str | None]]:
    """Each figure fence's token index and the block id on the paragraph after it, if any."""
    found = []
    for index, token in enumerate(tokens):
        if token.type != "fence" or token.info.split()[:1] != ["figure"]:
            continue
        block = None
        if (index + 3 < len(tokens) and tokens[index + 1].type == "paragraph_open"
                and (match := _BLOCK_ID.fullmatch(tokens[index + 2].content.strip()))):
            block = match[1]
        found.append((index, block))
    return found


def _caption(text: str) -> object:
    try:
        fence = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    return fence.get("caption") if isinstance(fence, dict) else None


def _prose(children: Sequence[Token]) -> str:
    """Plain prose of inline children; code and other inline markup break a phrase."""
    return "".join(child.content if child.type == "text" else " " if child.type in {"softbreak", "hardbreak"}
                   else "\x00" for child in children)


def _italic_only(children: Sequence[Token]) -> bool:
    visible = [child for child in children if child.type not in {"softbreak", "hardbreak"}
               and not (child.type == "text" and not child.content.strip())]
    if len(visible) < 3 or visible[0].type != "em_open" or visible[-1].type != "em_close":
        return False
    depth = 0
    for child in visible[:-1]:
        depth += {"em_open": 1, "em_close": -1}.get(child.type, 0)
        if depth == 0:
            return False
    return True


def figure_warnings(tokens: Sequence[Token], line: Callable[[int], int | None],
                    labels: Sequence[str]) -> list[tuple[int | None, str]]:
    """The lint's findings in one note's tokens, in source order: each with the note line ``line``
    gives for a token's 0-based body line, and its message."""
    pattern = "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
    typed = re.compile(rf"(?<!\w)(?:{pattern})\s+(?P<number>\d+(?:\.\d+)*)", re.IGNORECASE)
    caption_start = re.compile(rf"\s*(?:{pattern})\s+\d", re.IGNORECASE)
    findings: list[tuple[int | None, str]] = []

    def at(token: Token) -> int | None:
        return line(token.map[0]) if token.map else None

    def warn(token: Token, message: str) -> None:
        findings.append((at(token), f"{message}; {OWNER}."))

    fences = _fences(tokens)
    neighbours: list[tuple[int, int]] = []
    for position, block in fences:
        if not _caption(tokens[position].content):
            warn(tokens[position], "figure without caption. Add a caption to the figure fence")
        neighbours.append((position - 1, position + (4 if block is not None else 1)))
    for index, token in enumerate(tokens):
        children = token.children or []
        if (token.type == "inline" and index and tokens[index - 1].type == "paragraph_open"
                and len(children) == 1 and children[0].type == "image"
                and (mimetypes.guess_type(children[0].attrGet("src") or "")[0] or "").startswith("image/")):
            warn(token, "image without caption. Use a figure fence with kind: image, "
                        f"source: {children[0].attrGet('src')} and a caption")
            neighbours.append((index - 2, index + 2))
    outside: set[int] = set()
    for before, after in neighbours:
        candidates = []
        if before > 0 and tokens[before].type == "paragraph_close":
            candidates.append(before - 1)
        if after + 1 < len(tokens) and tokens[after].type == "paragraph_open":
            candidates.append(after + 1)
        for candidate in candidates:
            children = tokens[candidate].children or []
            if candidate not in outside and (_italic_only(children) or caption_start.match(_prose(children))):
                outside.add(candidate)
                warn(tokens[candidate], "caption outside the figure. Move the text into the figure's "
                                        "caption and delete the paragraph")

    def suggestion(number: str) -> str:
        ordinal = int(number.rsplit(".", 1)[-1])
        if not 1 <= ordinal <= len(fences):
            return "Link the figure instead with an Obsidian block link such as [[#^name]] or [[note#^name]]"
        position, block = fences[ordinal - 1]
        if block is not None:
            return f"Link the figure instead: [[#^{block}]]"
        return (f"Link the figure instead: add a block id after the figure at line {at(tokens[position])} "
                "and link it with [[#^name]]")

    def check(token: Token, children: Sequence[Token]) -> None:
        for match in typed.finditer(_prose(children)):
            warn(token, f"typed figure number '{match[0]}'. {suggestion(match['number'])}")

    for index, token in enumerate(tokens):
        if token.type == "inline" and index not in outside:
            check(token, token.children or [])
    for position, _ in fences:
        caption = _caption(tokens[position].content) or []
        for paragraph in caption if isinstance(caption, list) else [caption]:
            if isinstance(paragraph, str):
                for inline in parser().parseInline(paragraph):
                    check(tokens[position], inline.children or [])
    return sorted(findings, key=lambda finding: finding[0] or 0)
