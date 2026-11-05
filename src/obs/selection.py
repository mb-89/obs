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
from typing import Callable

from obs.input import InputError


BaseFilter = Callable[[Callable[[str], object]], bool]
_MISSING = object()
_LIST_INDEX = re.compile(r"0|[1-9][0-9]*")
_FILE_PROPERTIES = {"file.name", "file.path", "file.folder", "file.ext"}


def note_value(fields: dict[str, object], path: str, field: str) -> object:
    """Resolve a Bases property of a note record at a vault-relative POSIX path."""
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
    if field in fields:
        return fields[field]

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
        if not isinstance(value, dict) or parts[0] not in value:
            return _MISSING
        return traverse(value[parts[0]], parts[1:])

    value = traverse(fields, field.split("."))
    return None if value is _MISSING else value


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
            raise _unsupported(filters, f" (unsupported Bases property: {name})")
        field = spaced or simple.removeprefix("note.")
        expected = literal[1:-1] if literal[0] in "\"'" else json.loads(literal)

        def compare(value_for: Callable[[str], object]) -> bool:
            value = value_for(field)
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


def base_selects(definition: dict[str, object]) -> Callable[[dict[str, object], str], bool]:
    """Return whether any view of a Base definition selects a note record (fields, path)."""
    base = compile_base_filter(definition.get("filters"))
    views = []
    for view in definition.get("views", []):
        profile = view.get("obsHtml", {}) if isinstance(view.get("obsHtml"), dict) else {}
        records = profile.get("records", (definition.get("obsHtml") or {}).get("records", "note"))
        if records == "note":
            views.append(compile_base_filter(view.get("filters")))
    members = (definition.get("obsHtml") or {}).get("members")
    paths = None if not isinstance(members, list) else {member.get("path") for member in members}

    def selects(fields: dict[str, object], path: str) -> bool:
        if paths is not None and path not in paths:
            return False
        value_for = lambda field: note_value(fields, path, field)  # noqa: E731
        return base(value_for) and any(view(value_for) for view in views)
    return selects


def _texts(value: object) -> list[str]:
    if isinstance(value, list):
        return [text for item in value for text in _texts(item)]
    if value is None or isinstance(value, dict):
        return []
    if isinstance(value, bool):
        return ["true" if value else "false"]
    return [str(value)]


def conditions_select(conditions: list[dict[str, object]], fields: dict[str, object], path: str) -> bool:
    """Whether a note record has every query condition (``equals`` text, ``exists``)."""
    for condition in conditions:
        texts = _texts(note_value(fields, path, str(condition["field"])))
        if "equals" in condition and condition["equals"] not in texts:
            return False
        if "exists" in condition and not any(text.strip() for text in texts):
            return False
    return True
