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
from markdown_it.rules_block import StateBlock
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
def parser(columns: bool = False) -> MarkdownIt:
    """The supported Markdown dialect: CommonMark, pipe tables, strikethrough and TeX math, and
    with ``columns`` the ``|||`` delimiter lines of capabilities/columns."""
    markdown = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable(
        ["table", "strikethrough"],
    ).use(
        dollarmath_plugin, allow_labels=False, allow_space=False, allow_digits=False,
        double_inline=True,
    )
    if columns:
        # Before the table rule, and ending a paragraph, a table, a list or a quote as a thematic
        # break does (the table rule ends at the blockquote rule's terminators).
        markdown.block.ruler.before(
            "table", "columns", _delimiter_rule, {"alt": ["paragraph", "reference", "blockquote", "list"]},
        )
    return markdown


DELIMITER = "columns_delimiter"
"""The token type of a ``|||`` line (capabilities/columns#Delimiters); its ``info`` is the text
after the marks, the weights an opening line may carry."""
_DELIMITER_LINE = re.compile(r"\|\|\|(?:[ \t]+(?P<rest>.*?))?[ \t]*")
_CANDIDATE = re.compile(r"^[ \t>*+\-0-9.)]*\|\|\|(?:[ \t].*)?$", re.M)
"""A line that may be a delimiter, at the top level or in a list item or a quote, where it is an error."""
_WEIGHTS = re.compile(r"(?P<first>[0-9]+):(?P<second>[0-9]+)")
WEIGHT_RANGE = range(1, 9)
"""The weights a columns block's opening line may name (input-model#Document home and abstract)."""


def _delimiter_rule(state: StateBlock, start: int, _end: int, silent: bool) -> bool:
    """A ``|||`` line at most three spaces in, as one ``columns_delimiter`` token."""
    if state.is_code_block(start):
        return False
    begin = state.bMarks[start] + state.tShift[start]
    match = _DELIMITER_LINE.fullmatch(state.src[begin:state.eMarks[start]])
    if match is None:
        return False
    if not silent:
        token = state.push(DELIMITER, "", 0)
        token.map = [start, start + 1]
        token.markup = "|||"
        token.info = match["rest"] or ""
    state.line = start + 1
    return True


def column_weights(info: str) -> tuple[int, int]:
    """The weights of an opening line whose text after the marks is ``info``: ``(1, 1)`` without
    any; column_blocks checked them."""
    weights = _WEIGHTS.fullmatch(info)
    return (int(weights["first"]), int(weights["second"])) if weights else (1, 1)


def has_delimiters(text: str) -> bool:
    """Whether ``text`` may hold a ``|||`` delimiter line: only such text is parsed with them."""
    return "|||" in text and _CANDIDATE.search(text) is not None


class ColumnBlock(NamedTuple):
    """One block of capabilities/columns: its number in the text (from 1), its weights and the
    0-based lines of its opening, separator and closing delimiters."""

    number: int
    weights: tuple[int, int]
    opening: int
    separator: int
    closing: int


class ColumnsError(ValueError):
    """A malformed columns block: its number in the text, the 0-based line of the delimiter at
    fault, the problem and the remedy (capabilities/columns#Input errors)."""

    def __init__(self, number: int, line: int, problem: str, remedy: str) -> None:
        super().__init__(f"columns block {number}: {problem}. {remedy}.")
        self.number, self.line, self.problem, self.remedy = number, line, problem, remedy


def column_blocks(text: str) -> list[ColumnBlock]:
    """The columns blocks of a note's text, read from its lines; capabilities/columns owns the rules.

    Pure: the same text gives the same blocks or the same ColumnsError, the first malformed block's.
    """
    if not has_delimiters(text):
        return []
    tokens = parser(columns=True).parse(text)
    delimiters = [token for token in tokens if token.type == DELIMITER]
    content = [token.map[0] for token in tokens
               if token.level == 0 and token.type != DELIMITER and token.map and token.nesting >= 0]
    see = "see capabilities/columns"
    blocks: list[ColumnBlock] = []
    for start in range(0, len(delimiters), 3):
        group, number = delimiters[start:start + 3], len(blocks) + 1
        for place, token in zip(("opening", "separator", "closing"), group):
            line = token.map[0]
            if token.level:
                raise ColumnsError(number, line, f"has its {place} line inside a list item or a blockquote",
                                   f"Write the ||| line at the top level of the note; {see}")
            if place != "opening" and token.info:
                raise ColumnsError(number, line, f"has {token.info!r} on its {place} line, where no weights go",
                                   f"Name the weights on the opening line alone, as ||| 1:2; {see}")
        opening = group[0]
        weights = _WEIGHTS.fullmatch(opening.info) if opening.info else None
        if opening.info and (weights is None or not {int(weights["first"]), int(weights["second"])}
                             <= set(WEIGHT_RANGE)):
            raise ColumnsError(number, opening.map[0], f"has the weights {opening.info!r}, which are not two "
                               "integers from 1 to 8", f"Write two weights from 1 to 8, as ||| 1:2; {see}")
        if len(group) < 3:
            raise ColumnsError(number, group[-1].map[0], "is not closed: it has "
                               f"{'no separator and ' if len(group) < 2 else ''}no closing ||| line",
                               "Close the block with a ||| line after its second column; a block holds "
                               f"no other block; {see}")
        lines = [token.map[0] for token in group]
        for column, (first, last) in enumerate(zip(lines, lines[1:]), 1):
            if not any(first < line < last for line in content):
                raise ColumnsError(number, first, f"has no Markdown block in its {('first', 'second')[column - 1]} "
                                   "column", f"Write the column's content between its ||| lines, or remove the "
                                   f"block; a block holds no other block; {see}")
        blocks.append(ColumnBlock(number, column_weights(opening.info), *lines))
    return blocks


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
    # From the opening line's newline on, so PyYAML's line marks are the file's lines.
    frontmatter = source[3:closing]
    try:
        metadata = yaml.safe_load(frontmatter)
    except yaml.reader.ReaderError as error:
        raise VaultError(f"Invalid frontmatter in {path}: {_reader_error_text(error, frontmatter)}") from error
    except yaml.YAMLError as error:
        raise VaultError(f"Invalid frontmatter in {path}: {error}") from error
    except ValueError as error:
        node = _unloadable_scalar(frontmatter)
        where = f"line {node.start_mark.line + 1}: {node.value}" if node else "a value"
        raise VaultError(
            f"Invalid frontmatter in {path}: {where} is no real date or time ({error}); quote the value, "
            f"or write a real date or time."
        ) from error
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


def _reader_error_text(error: yaml.reader.ReaderError, frontmatter: str) -> str:
    """PyYAML's message for a character it refuses, its position given as the line and the 1-based
    column that PyYAML's line marks count in ``frontmatter``."""
    line = frontmatter.count("\n", 0, error.position) + 1
    column = error.position - frontmatter.rfind("\n", 0, error.position)
    return f"{str(error).removesuffix(f'position {error.position}')}line {line}, column {column}"


def _unloadable_scalar(frontmatter: str) -> yaml.ScalarNode | None:
    """The first frontmatter scalar, in source order, that the YAML loader cannot turn into a value."""
    constructor = yaml.SafeLoader("")
    pending, seen = [yaml.compose(frontmatter, Loader=yaml.SafeLoader)], set()
    while pending:
        node = pending.pop()
        if node is None or id(node) in seen:
            continue
        seen.add(id(node))
        if isinstance(node, yaml.ScalarNode):
            try:
                constructor.construct_object(node)
            except ValueError:
                return node
        elif isinstance(node, yaml.MappingNode):
            pending.extend(reversed([part for pair in node.value for part in pair]))
        else:
            pending.extend(reversed(node.value))
    return None
