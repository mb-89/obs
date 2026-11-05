"""Validate data-only source contracts used to construct a Document."""
from __future__ import annotations

from functools import cache
from importlib.resources import files
import json
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


def parse_property_editor(text: str) -> dict[str, object]:
    try:
        specification = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise InputError(f"Property editor: invalid YAML: {error}") from error
    errors = list(_validator("propertyEditor").iter_errors(specification))
    if errors:
        raise InputError(f"Property editor: {errors[0].message[:180]}")
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
