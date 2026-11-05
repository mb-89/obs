"""Shared safe Markdown source semantics."""
from functools import cache
import re

from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml
from markdown_it.token import Token


@cache
def _commonmark() -> MarkdownIt:
    return MarkdownIt("commonmark")


@cache
def shared_authoring_markdown() -> MarkdownIt:
    """Return one reusable parser for callers that never customize it."""
    return authoring_markdown()


def authoring_markdown() -> MarkdownIt:
    markdown = MarkdownIt("commonmark", {"html": False, "linkify": False})

    def comments(state) -> None:
        if "<!--" not in state.src:
            return
        source = state.src
        offsets = [0]
        for line in source.splitlines(keepends=True):
            offsets.append(offsets[-1] + len(line))
        # CommonMark identifies code blocks without mistaking fences inside HTML
        # comments for executable Markdown blocks.
        protected = {
            offsets[token.map[0]]: offsets[token.map[1]]
            for token in _commonmark().parse(source)
            if token.type in {"fence", "code_block"} and token.map
        }
        pieces = []
        position = 0
        while position < len(source):
            start = position
            if position in protected:
                position = protected[position]
            elif source[position] == "\\":
                position += 2
            elif source[position] == "`":
                run = re.match(r"`+", source[position:]).group()
                closing = re.search(rf"(?<!`){re.escape(run)}(?!`)", source[position + len(run):])
                position += len(run) + (closing.end() if closing else 0)
            elif source.startswith("<!--", position):
                end = source.find("-->", position + 4)
                position = len(source) if end < 0 else end + 3
                pieces.append("\n" * source[start:position].count("\n"))
                continue
            else:
                position += 1
            pieces.append(source[start:position])
        state.src = "".join(pieces)

    markdown.core.ruler.before("block", "authoring_comments", comments)

    def column_delimiter(state, start_line, _end_line, silent):
        from obs_html_interim.content import ContentError

        if state.sCount[start_line] - state.blkIndent >= 4:
            return False
        start = state.bMarks[start_line] + state.tShift[start_line]
        source = state.src[start:state.eMarks[start_line]].strip()
        match = re.fullmatch(r"\|\|\|(?:\s+(\d{1,2}):(\d{1,2}))?", source)
        if not match:
            return False
        ratio = match.groups() if match.group(1) else None
        if ratio and any(not 1 <= int(weight) <= 8 for weight in ratio):
            raise ContentError("Column weights must be integers from 1 to 8.")
        if silent:
            return True
        token = state.push("column_delimiter", "", 0)
        token.meta = {"ratio": ratio} if ratio else {}
        token.map = [start_line, start_line + 1]
        token.block = True
        state.line = start_line + 1
        return True

    def columns(state):
        from obs_html_interim.content import ContentError

        delimiters = [
            index for index, token in enumerate(state.tokens)
            if token.type == "column_delimiter"
        ]
        if not delimiters:
            return
        if len(delimiters) % 3 or any(state.tokens[index].level for index in delimiters):
            raise ContentError("Columns require three top-level ||| delimiters; nesting is not supported.")
        for offset in range(0, len(delimiters), 3):
            opening, separator, closing = delimiters[offset:offset + 3]
            if separator == opening + 1 or closing == separator + 1:
                raise ContentError("Columns require two nonempty Markdown blocks.")
            if state.tokens[separator].meta.get("ratio") or state.tokens[closing].meta.get("ratio"):
                raise ContentError("Column weights are declared only on the opening ||| delimiter.")

        result = []
        position = 0
        for index, token in enumerate(state.tokens):
            if token.type != "column_delimiter":
                token.level += 2 if position else 0
                result.append(token)
                continue
            definitions = (
                [("columns_open", 1, "markdown-columns"), ("column_open", 1, "markdown-column")],
                [("column_close", -1, ""), ("column_open", 1, "markdown-column")],
                [("column_close", -1, ""), ("columns_close", -1, "")],
            )[position]
            for name, nesting, class_name in definitions:
                replacement = Token(name, "div", nesting)
                replacement.block = True
                replacement.map = token.map
                if class_name:
                    replacement.attrSet("class", class_name)
                if name == "columns_open" and token.meta.get("ratio"):
                    left, right = (int(weight) for weight in token.meta["ratio"])
                    replacement.attrSet("class", "markdown-columns markdown-columns--weighted")
                    replacement.attrSet(
                        "style",
                        f"--markdown-column-template:minmax(0,{left}fr) minmax(0,{right}fr)",
                    )
                replacement.level = 0 if name in {"columns_open", "columns_close"} else 1
                result.append(replacement)
            position = (position + 1) % 3
        state.tokens = result

    markdown.block.ruler.before(
        "paragraph", "column_delimiter", column_delimiter,
        {"alt": ["paragraph", "reference", "blockquote", "list"]},
    )
    markdown.block.ruler.before(
        "paragraph", "base_embed", _base_embed,
        {"alt": ["paragraph", "reference", "blockquote", "list"]},
    )
    markdown.core.ruler.after("block", "columns", columns)
    markdown.add_render_rule("code_inline", _code_inline)
    return markdown


# An Obsidian embed of a reusable Bases file on its own line, optionally naming its initial view.
BASE_EMBED = re.compile(r"!\[\[(?P<target>[^\]|#]+\.base)(?:#(?P<view>[^\]|]+))?\]\]")


def _base_embed(state, start_line, _end_line, silent):
    if state.sCount[start_line] - state.blkIndent >= 4:
        return False
    start = state.bMarks[start_line] + state.tShift[start_line]
    match = BASE_EMBED.fullmatch(state.src[start:state.eMarks[start_line]].strip())
    if not match:
        return False
    if silent:
        return True
    token = state.push("base_embed", "", 0)
    token.meta = {"target": match["target"].strip(), "view": (match["view"] or "").strip()}
    token.map = [start_line, start_line + 1]
    token.block = True
    state.line = start_line + 1
    return True


# A separator run inside a code span is a break opportunity only between word characters,
# so a leading `/root`, trailing `trail.` or bare `--flag` never strand a lone mark.
_CODE_BREAK = re.compile(r"(?<=[^\s/\\._:\-])[/\\._:\-]+(?=[^\s/\\._:\-])")


def _code_inline(renderer, tokens, index, _options, _env) -> str:
    token = tokens[index]
    pieces, position = [], 0
    for separator in _CODE_BREAK.finditer(token.content):
        pieces.append(escapeHtml(token.content[position:separator.end()]))
        position = separator.end()
    pieces.append(escapeHtml(token.content[position:]))
    return f"<code{renderer.renderAttrs(token)}>{'<wbr>'.join(pieces)}</code>"
