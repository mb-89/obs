"""Select note records by Base filters and query conditions, to decide note inclusion.

The Bases filter grammar is owned by generic-tables ("Bases filter grammar"); query
conditions by input-model ("Chapter content"). The core uses both only to decide which
notes a Document includes.
"""
from __future__ import annotations

from functools import cache
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


NoteSelector = Callable[[dict[str, object], str], bool]
"""Whether a note record (fields, vault-relative path) is selected."""


def view_selectors(definition: dict[str, object]) -> list[NoteSelector | None]:
    """One selector per view of a Base definition; ``None`` for a view whose rows are not notes."""
    base = compile_base_filter(definition.get("filters"))
    members = (definition.get("obsHtml") or {}).get("members")
    paths = None if not isinstance(members, list) else {member.get("path") for member in members}

    def selector(view: dict[str, object]) -> NoteSelector | None:
        profile = view.get("obsHtml", {}) if isinstance(view.get("obsHtml"), dict) else {}
        if profile.get("records", (definition.get("obsHtml") or {}).get("records", "note")) != "note":
            return None
        own = compile_base_filter(view.get("filters"))

        def selects(fields: dict[str, object], path: str) -> bool:
            if not selectable(fields) or paths is not None and path not in paths:
                return False
            value_for = lambda field: note_value(fields, path, field)  # noqa: E731
            return base(value_for) and own(value_for)
        return selects
    return [selector(view) for view in definition.get("views", [])]


def base_selects(definition: dict[str, object]) -> NoteSelector:
    """Return whether any view of a Base definition selects a note record (fields, path)."""
    views = [view for view in view_selectors(definition) if view is not None]
    return lambda fields, path: any(view(fields, path) for view in views)


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
