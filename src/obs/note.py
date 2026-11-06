"""The core's one note reader and its one Markdown parser; see input-model "Chapter content".

Every part of the core that reads a note body reads it here, so comment removal, frontmatter
and the Markdown dialect are the same for producers, inclusion and conversion.
"""
from __future__ import annotations

from functools import cache
from pathlib import Path
import re
from typing import NamedTuple

from markdown_it import MarkdownIt
from mdit_py_plugins.dollarmath import dollarmath_plugin
import yaml

IGNORED = "ignored"
"""The frontmatter field that marks a note as ignored; see markdown-frontmatter."""
_FENCE = re.compile(r"[ \t]*(?P<marker>`{3,}|~{3,})")
_COMMENT = "%%"
_LINE = re.compile(r"[^\n]*\n|[^\n]+\Z")


class VaultError(ValueError):
    """Raised when vault input violates the neutral parsing contract."""


class Note(NamedTuple):
    """A note as read: its frontmatter, its body without comments, and for each body line the
    source file's line number."""

    metadata: dict[str, object]
    body: str
    lines: tuple[int, ...]

    def source_line(self, body_line: int) -> int:
        """The source file's line number of the body's 0-based line ``body_line``."""
        return self.lines[body_line]


def lines(text: str) -> list[str]:
    """The text's lines with their endings, split where Markdown splits them: at ``\\n``."""
    return _LINE.findall(text)


@cache
def parser() -> MarkdownIt:
    """The supported Markdown dialect: CommonMark, pipe tables, strikethrough and TeX math."""
    return MarkdownIt("commonmark", {"html": False, "linkify": False}).enable(
        ["table", "strikethrough"],
    ).use(
        dollarmath_plugin, allow_labels=False, allow_space=False, allow_digits=False,
        double_inline=True,
    )


def read_note(path: Path) -> Note:
    """Read a note once: frontmatter, then the body without its Obsidian comments."""
    try:
        source = path.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise VaultError(f"Cannot read note {path}: {error}") from error
    metadata, body = _split_frontmatter(source, path)
    body, numbers = _without_comments(body, path, source[:len(source) - len(body)].count("\n"))
    return Note(metadata, body, numbers)


def _without_comments(body: str, path: Path, first_line: int) -> tuple[str, tuple[int, ...]]:
    """The body without its Obsidian comments, and each kept line's source line number.

    A ``%%`` outside code opens a comment and the next ``%%`` closes it, on the same line or a
    later one. A line that held only comment text goes, so a manifest list runs on past it.
    """
    source_lines = lines(body)
    if _COMMENT not in body:
        return body, tuple(range(first_line + 1, first_line + 1 + len(source_lines)))
    kept: list[str] = []
    numbers: list[int] = []
    fence = ""
    opened = 0
    for number, line in enumerate(source_lines, first_line + 1):
        if not opened:
            if fence:
                kept.append(line)
                numbers.append(number)
                if re.fullmatch(rf"[ \t]*{re.escape(fence[0])}{{{len(fence)},}}[ \t]*\r?\n?", line):
                    fence = ""
                continue
            match = _FENCE.match(line)
            if match:
                fence = match["marker"]
                kept.append(line)
                numbers.append(number)
                continue
        if not opened and _COMMENT not in line:
            kept.append(line)
            numbers.append(number)
            continue
        text, opened, touched = _line_without_comments(line, opened, number)
        if text.strip() or not touched:
            kept.append(text)
            numbers.append(number)
    if opened:
        raise VaultError(
            f"{path}: line {opened}: the Obsidian comment opened here is not closed. Add the "
            f"closing {_COMMENT}, or write the percent signs in code; see input-model "
            '"Chapter content".'
        )
    return "".join(kept), tuple(numbers)


def _line_without_comments(line: str, opened: int, number: int) -> tuple[str, int, bool]:
    """One line's shown text, the line its open comment began on (0 for none), and whether a
    comment touched it; a code span keeps its ``%%``."""
    shown: list[str] = []
    touched = bool(opened)
    position = 0
    while position < len(line):
        if line.startswith(_COMMENT, position):
            opened = 0 if opened else number
            touched = True
            position += len(_COMMENT)
            continue
        if line[position] in "\r\n":
            shown.append(line[position])
        elif opened:
            pass
        elif line[position] == "`":
            run = re.match(r"`+", line[position:])[0]
            closing = re.compile(rf"(?<!`){run}(?!`)").search(line, position + len(run))
            end = closing.end() if closing else position + len(run)
            shown.append(line[position:end])
            position = end
            continue
        else:
            shown.append(line[position])
        position += 1
    return "".join(shown), opened, touched


def _split_frontmatter(source: str, path: Path) -> tuple[dict[str, object], str]:
    if not source.startswith("---\n"):
        return {}, source
    closing = source.find("\n---", 4)
    if closing < 0:
        raise VaultError(f"Frontmatter is not closed: {path}")
    try:
        metadata = yaml.safe_load(source[4:closing])
    except yaml.YAMLError as error:
        raise VaultError(f"Invalid frontmatter in {path}: {error}") from error
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise VaultError(f"Frontmatter must be a mapping: {path}")
    if not isinstance(metadata.get(IGNORED, False), bool):
        raise VaultError(
            f"Frontmatter field {IGNORED} must be true or false in {path}: "
            f"{metadata[IGNORED]!r}; write {IGNORED}: true to keep queries and Bases from "
            f"selecting the note, or remove the field."
        )
    body_start = closing + 4
    if source[body_start:body_start + 1] == "\n":
        body_start += 1
    return metadata, source[body_start:]
