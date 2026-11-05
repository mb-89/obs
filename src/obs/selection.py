"""Select records by Base filters and note records by query conditions.

The Bases filter grammar is owned by generic-tables ("Bases filter grammar"); query
conditions by input-model ("Chapter content"). The core uses both to decide which notes a
Document includes and which records a register's views select.
"""
from __future__ import annotations

from functools import cache
from itertools import pairwise
from importlib.resources import files
import json
from pathlib import PurePosixPath
import re
from typing import Callable, Sequence

from markdown_it import MarkdownIt

from obs.input import InputError


BaseFilter = Callable[[Callable[[str], object]], bool]
_MISSING = object()
_LIST_INDEX = re.compile(r"0|[1-9][0-9]*")
_MARK = re.compile(r"(?<!\S)#mark/(?P<category>[a-z_]+)/(?P<id>[a-z0-9]+(?:_[a-z0-9]+)*)(?=\s|$)")
_FILE_PROPERTIES = {"file.name", "file.path", "file.folder", "file.ext"}
IGNORED = "ignored"
"""The frontmatter field that marks a note as ignored; see markdown-frontmatter."""


def selectable(fields: dict[str, object]) -> bool:
    """Whether queries and Bases may select a note record; an ignored note is never selected."""
    return fields.get(IGNORED) is not True


def _key(mapping: dict[object, object], name: str) -> object:
    """The key a property name matches, ignoring case; see capabilities/bases#Comparisons."""
    if name in mapping:
        return name
    folded = name.lower()
    return next((key for key in mapping if isinstance(key, str) and key.lower() == folded), None)


def same_text(actual: str, expected: str, match_case: bool = False) -> bool:
    """Whether two texts are equal, ignoring case unless asked; see capabilities/bases#Comparisons."""
    if match_case:
        return actual == expected
    return re.fullmatch(re.escape(expected), actual, re.IGNORECASE) is not None


def note_value(fields: dict[str, object], path: str, field: str) -> object:
    """Resolve a Bases property of a note record at a vault-relative POSIX path."""
    value = _resolve(fields, path, field)
    return None if value is _MISSING else value


def _resolve(fields: dict[str, object], path: str, field: str) -> object:
    field = field.removeprefix("note.")
    location = PurePosixPath(path)
    if field == "file.name":
        return location.stem
    if field == "file.path":
        return path
    if field == "file.folder":
        return location.parent.as_posix().removesuffix(".")
    if field == "file.ext":
        return location.suffix.removeprefix(".")
    whole = _key(fields, field)
    if whole is not None:
        return fields[whole]

    def traverse(value: object, parts: list[str]) -> object:
        if not parts:
            return value
        if isinstance(value, list) and not _LIST_INDEX.fullmatch(parts[0]):
            matches: list[object] = []
            for item in value:
                match = traverse(item, parts)
                if isinstance(match, list):
                    matches.extend(match)
                elif match is not _MISSING:
                    matches.append(match)
            return matches
        if isinstance(value, list):
            index = int(parts[0])
            return traverse(value[index], parts[1:]) if index < len(value) else _MISSING
        key = _key(value, parts[0]) if isinstance(value, dict) else None
        if key is None:
            return _MISSING
        return traverse(value[key], parts[1:])

    return traverse(fields, field.split("."))


@cache
def _comparison() -> re.Pattern[str]:
    schema = json.loads(files("obs").joinpath("base.schema.json").read_text(encoding="utf-8"))
    return re.compile(schema["$defs"]["comparison"]["pattern"])


def _unsupported(filters: object, reason: str = "") -> InputError:
    text = filters if isinstance(filters, str) else json.dumps(filters, ensure_ascii=False, default=str)
    return InputError(f"Unsupported Bases filter: {text}{reason}")


def compile_base_filter(filters: object) -> BaseFilter:
    """Compile one Bases filter; ``None`` matches everything.

    The predicate receives a resolver from property name to typed value.
    """
    if filters is None:
        return lambda value_for: True
    if isinstance(filters, str):
        match = _comparison().fullmatch(filters)
        if not match:
            raise _unsupported(filters)
        simple, spaced, operator, literal = match.groups()
        if simple == "recordType":
            raise _unsupported(filters, " (recordType filters were removed; select rows with obsHtml.records)")
        name = simple or f'note["{spaced}"]'
        if (re.match(r'^note(?:\.file\.|\["file\.)', name) or name.startswith(("formula.", "this."))
                or name.startswith("file.") and name not in _FILE_PROPERTIES):
            raise _unsupported(filters, f" (Unsupported Bases property: {name})")
        field = spaced or simple.removeprefix("note.")
        expected = literal[1:-1] if literal[0] in "\"'" else json.loads(literal)

        def compare(value_for: Callable[[str], object]) -> bool:
            value = value_for(field)
            if isinstance(value, str) and isinstance(expected, str):
                equal = same_text(value, expected)
            else:
                equal = value == expected and (
                    type(value) is type(expected)
                    or type(value) in (int, float) and type(expected) in (int, float)
                )
            return equal if operator == "==" else not equal
        return compare
    if isinstance(filters, dict) and len(filters) == 1:
        operator, operand = next(iter(filters.items()))
        operands = operand if isinstance(operand, list) else [operand]
        if operator in {"and", "or", "not"} and operands and None not in operands:
            children = [compile_base_filter(item) for item in operands]
            if operator == "or":
                return lambda value_for: any(child(value_for) for child in children)
            if operator == "not":
                return lambda value_for: not any(child(value_for) for child in children)
            return lambda value_for: all(child(value_for) for child in children)
    raise _unsupported(filters)


Record = dict[str, object]
"""A Document record (document.schema.json, $defs/record)."""
RecordSelector = Callable[[Record, "Record | None"], bool]
"""Whether a record is selected, given the note record it comes from (None for a row without one)."""
_RESOLVES_ON_NOTE = frozenset({"chapter", "glossary"})
"""The record types whose properties other than their own fields resolve on their note (generic-tables)."""


def record_value(record: Record, note: Record | None, field: str) -> object:
    """Resolve a Bases property of a record: a note's frontmatter and path, else a row's own fields first."""
    if record["type"] == "note":
        return note_value(record["fields"], str(record["path"]), field)
    own = record["fields"]
    key = _key(own, field.removeprefix("note."))
    if key is not None:
        return own[key]
    if record["type"] in _RESOLVES_ON_NOTE and note is not None:
        return note_value(note["fields"], str(note["path"]), field)
    return None


def view_selectors(definition: dict[str, object]) -> list[RecordSelector]:
    """One selector per view of a Base definition, over the record type its obsHtml.records names."""
    base = compile_base_filter(definition.get("filters"))
    profile = definition.get("obsHtml") if isinstance(definition.get("obsHtml"), dict) else {}
    members = profile.get("members")
    paths = None if not isinstance(members, list) else {member.get("path") for member in members}

    def selector(view: dict[str, object]) -> RecordSelector:
        own_profile = view.get("obsHtml") if isinstance(view.get("obsHtml"), dict) else {}
        kind = own_profile.get("records", profile.get("records", "note"))
        own = compile_base_filter(view.get("filters"))

        def selects(record: Record, note: Record | None) -> bool:
            owner = record if record["type"] == "note" else note
            if record["type"] != kind or owner is not None and (
                not selectable(owner["fields"]) or paths is not None and owner["path"] not in paths
            ):
                return False
            def value_for(field: str) -> object:
                return record_value(record, note, field)
            return base(value_for) and own(value_for)
        return selects
    return [selector(view) for view in definition.get("views", [])]


def base_selects(definition: dict[str, object]) -> RecordSelector:
    """Return whether any view of a Base definition selects a record, given its note."""
    views = view_selectors(definition)
    return lambda record, note: any(view(record, note) for view in views)


def _texts(value: object) -> list[str]:
    if isinstance(value, list):
        return [text for item in value for text in _texts(item)]
    if value is None or isinstance(value, dict):
        return []
    if isinstance(value, bool):
        return ["true" if value else "false"]
    if isinstance(value, float) and value.is_integer():
        return [str(int(value))]
    return [str(value)]


Mark = tuple[str, str]
"""A note's mark: its category and identifier (capabilities/marks)."""


@cache
def note_marks(body: str) -> tuple[Mark, ...]:
    """The marks a note's Markdown body holds outside code; see capabilities/marks."""
    marks: list[Mark] = []
    for token in MarkdownIt("commonmark", {"html": False, "linkify": False}).parse(body):
        for child in token.children or []:
            if child.type == "text":
                marks.extend((match["category"], match["id"]) for match in _MARK.finditer(child.content))
    return tuple(marks)


ParagraphMark = tuple[str, str, str]
"""A mark of a marked paragraph: its category, identifier and the paragraph's text without marks."""


@cache
def paragraph_marks(body: str) -> tuple[ParagraphMark, ...]:
    """The marks of a note's marked paragraphs, in order; see capabilities/marks."""
    tokens = MarkdownIt("commonmark", {"html": False, "linkify": False}).parse(body)
    marks: list[ParagraphMark] = []
    for previous, token in pairwise(tokens):
        if token.type != "inline" or previous.type != "paragraph_open":
            continue
        found = [match for child in token.children or [] if child.type == "text"
                 for match in _MARK.finditer(child.content)]
        text = token.content
        for match in found:
            text = text.replace(match.group(0), "", 1)
        marks.extend((match["category"], match["id"], " ".join(text.split())) for match in found)
    return tuple(marks)


def _condition_value(fields: dict[str, object], path: str, field: str, marks: Sequence[Mark]) -> object:
    """A note property, else its marks for mark and mark.<category> (capabilities/queries#Conditions)."""
    value = _resolve(fields, path, field)
    if value is not _MISSING:
        return value
    name = field.removeprefix("note.").lower()
    if name == "mark":
        return list(dict.fromkeys(category for category, _ in marks)) or None
    if name.startswith("mark."):
        return [identifier for category, identifier in marks if category.lower() == name[5:]] or None
    return None


def conditions_select(
    conditions: list[dict[str, object]], fields: dict[str, object], path: str, marks: Sequence[Mark] = (),
) -> bool:
    """Whether a note record has every query condition; see capabilities/queries#Conditions."""
    if not selectable(fields):
        return False
    for condition in conditions:
        texts = _texts(_condition_value(fields, path, str(condition["field"]), marks))
        if "equals" in condition and not any(
            same_text(text, str(condition["equals"]), condition.get("matchCase") is True) for text in texts
        ):
            return False
        if "exists" in condition and not any(text.strip() for text in texts):
            return False
    return True
