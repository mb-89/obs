"""Validate data-only source contracts used to construct a Document."""
from __future__ import annotations

from functools import cache
from importlib.resources import files
import json
from math import isfinite
import re
from typing import Any

from jsonschema import Draft202012Validator
import yaml


class InputError(ValueError):
    """Raised when an authored input violates the core input contract."""


CALLOUT_TYPES: dict[str, tuple[str, tuple[str, ...]]] = {
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
    "important": ("accent", ()),
}
_CALLOUT_NAMES = {
    alias: kind for kind, (_, aliases) in CALLOUT_TYPES.items() for alias in (kind, *aliases)
}
_CALLOUT_MARKER = re.compile(r"\[!(?P<keyword>[A-Za-z]+)\](?P<fold>[+-]?)(?:[ \t]+|$)")


@cache
def _schema() -> dict[str, object]:
    return json.loads(files("obs").joinpath("input.schema.json").read_text(encoding="utf-8"))


@cache
def _validator(name: str) -> Draft202012Validator:
    schema = _schema()
    return Draft202012Validator({"$ref": f"#/$defs/{name}", "$defs": schema["$defs"]})


def parse_card_spec(text: str) -> dict[str, object]:
    try:
        specification = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise InputError(f"Cards: invalid YAML: {error}") from error
    errors = list(_validator("cards").iter_errors(specification))
    if errors:
        raise InputError(f"Cards: {errors[0].message[:200]}")
    return specification


def validate_count_query(query: object) -> None:
    errors = list(_validator("countQuery").iter_errors(query))
    if errors:
        raise InputError(f"Quantity query: {errors[0].message[:200]}")


def parse_property_editor(text: str, source_path: object | None = None) -> dict[str, object]:
    try:
        specification = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise InputError(f"Property editor: invalid YAML: {error}") from error
    errors = list(_validator("propertyEditor").iter_errors(specification))
    if errors:
        location = f" in {source_path}" if source_path is not None else ""
        raise InputError(f"Property editor{location}: {errors[0].message[:180]}")
    return specification


def validate_command(command: str) -> str:
    if not command.strip():
        raise InputError("A cmd fence cannot be empty.")
    return command


def parse_callout(line: str) -> dict[str, str] | None:
    match = _CALLOUT_MARKER.match(line)
    if match is None:
        return None
    kind = _CALLOUT_NAMES.get(match["keyword"].lower())
    if kind is None:
        return None
    return {
        "type": kind,
        "tone": CALLOUT_TYPES[kind][0],
        "fold": match["fold"],
        "title": line[match.end():].strip(),
    }


_QUANTITY_ALIAS = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,39}")
_NOTE_LINK = re.compile(r"(?<!!)\[[^\]]+\]\([^)]+\)|\[\[[^\]]+\]\]")


def validate_quantity(metadata: dict[str, object], source_path: object) -> None:
    """Validate a quantity note's frontmatter; see capabilities/quantities."""

    def fail(field: str, problem: str, remedy: str) -> None:
        raise InputError(f"Quantity note {source_path}: {field} {problem}; {remedy}.")

    if ("value" in metadata) == ("query" in metadata):
        if "value" in metadata:
            fail("value or query", "are both set",
                 "keep exactly one: value for a number, query for a count")
        fail("value or query", "is missing",
             "add value: <number> or query: {where: [...]} for a count")
    value = metadata.get("value")
    if "value" in metadata and (
        isinstance(value, bool) or not isinstance(value, (int, float))
        or isinstance(value, float) and not isfinite(value)
    ):
        fail("value", f"must be a finite number, not {value!r}",
             "write the bare number and put the unit in unit")
    if "query" in metadata:
        errors = list(_validator("countQuery").iter_errors(metadata["query"]))
        if errors:
            fail("query", f"is invalid: {errors[0].message[:200]}",
                 "write query: {where: [...], from?, distinct?} as capabilities/queries describes")
    unit = metadata.get("unit")
    if "unit" in metadata and (not isinstance(unit, str) or not unit.strip()):
        fail("unit", f"must be a non-empty string, not {unit!r}",
             "write the display unit, such as mm, or remove unit")
    aliases = metadata.get("aliases")
    aliases = [aliases] if isinstance(aliases, str) else aliases
    if not isinstance(aliases, list) or len(aliases) != 1 or not isinstance(aliases[0], str) \
            or not _QUANTITY_ALIAS.fullmatch(aliases[0].strip()):
        fail("aliases", f"must hold one variable-style alias, not {metadata.get('aliases')!r}",
             "keep one variable-style alias: a letter, then up to 39 letters, digits or "
             "underscores, such as maxLoad")
    source = metadata.get("source")
    sources = [source] if isinstance(source, str) else source
    if not isinstance(sources, list) or not sources or not all(
        isinstance(item, str) and item.strip() for item in sources
    ) or not any(_NOTE_LINK.search(item) for item in sources):
        fail("source", f"must contain a note link, not {source!r}",
             "link the supporting note, such as source: \"[[drawing]]\"")


def validate_query(query: object) -> None:
    validate_count_query(query)


def _validate_schema(name: str, value: object, label: str, source_path: object) -> None:
    schema = json.loads(files("obs").joinpath(name).read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        raise InputError(f"{label} in {source_path}: {errors[0].message}")


def validate_base_definition(definition: object, source_path: object) -> None:
    schema = json.loads(files("obs").joinpath("base.schema.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(definition))
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path)
        raise InputError(f"Invalid base definition at {path or 'root'} in {source_path}: {error.message}")


def validate_note_profile(profile: object, source_path: object) -> None:
    schema = json.loads(files("obs").joinpath("note-profile.schema.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(profile))
    if errors:
        raise InputError(f"Invalid obsHtml note profile in {source_path}: {errors[0].message}")
    if isinstance(profile, dict) and isinstance(profile.get("query"), dict):
        validate_query(profile["query"])


def validate_project_config(configuration: object, source_path: object) -> None:
    _validate_schema("project.schema.json", configuration, "Invalid project configuration", source_path)
