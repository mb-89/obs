"""Validate data-only source contracts used to construct a Document."""
from __future__ import annotations

from functools import cache
from importlib.resources import files
import json
from math import isfinite
import re
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError, best_match
import yaml


class InputError(ValueError):
    """Raised when an authored input violates the core input contract."""


def input_error(source: object, field: str, problem: str, remedy: str) -> InputError:
    """The one contract-failure message form; see input-model "Chapter content"."""
    return InputError(f"{source}: {field or 'top level'}: {problem}. {remedy}.")


def schema_error(
    errors: list[ValidationError], source: object, reference: str, field: str = "", place: str = "",
) -> InputError | None:
    """Turn a schema validation failure into the one message form, or None without errors.

    ``field`` prefixes a frontmatter field (``query``), ``place`` a fence (``cards fence 1``);
    ``reference`` names the note that owns the contract.
    """
    if not errors:
        return None
    error = best_match(errors)
    parts, problem, remedy = _describe(error)
    path = field
    for part in [*error.absolute_path, *parts]:
        path += f"[{part}]" if isinstance(part, int) else f".{part}" if path else str(part)
    path = ", ".join(item for item in (place, path) if item)
    return input_error(source, path, problem, f"{remedy}; see {reference}")


_TYPES = {
    "array": "a list", "object": "a mapping", "string": "text", "boolean": "true or false",
    "integer": "a whole number", "number": "a number", "null": "empty",
}


def _shown(value: object) -> str:
    text = json.dumps(value, default=str, ensure_ascii=False)
    return text if len(text) <= 60 else text[:57] + "..."


def _describe(error: ValidationError) -> tuple[list[object], str, str]:
    """The extra path parts, the problem and the remedy of one schema failure."""
    keyword, expected, instance = error.validator, error.validator_value, error.instance
    if keyword == "type":
        kinds = expected if isinstance(expected, list) else [expected]
        wanted = " or ".join(_TYPES.get(kind, kind) for kind in kinds)
        return [], f"must be {wanted}, not {_shown(instance)}", f"Write {wanted}"
    if keyword in {"enum", "const"}:
        choices = expected if keyword == "enum" else [expected]
        allowed = ", ".join(_shown(choice) for choice in choices)
        return [], f"must be {'one of ' if len(choices) > 1 else ''}{allowed}, not {_shown(instance)}", \
            f"Write {'one of them' if len(choices) > 1 else allowed}"
    if keyword == "required":
        missing = next(name for name in expected if name not in instance)
        return [missing], "is missing", f"Add {missing}"
    if keyword == "additionalProperties":
        known = set(error.schema.get("properties", {}))
        patterns = list(error.schema.get("patternProperties", {}))
        extra = next(name for name in instance if name not in known
                     and not any(re.search(pattern, name) for pattern in patterns))
        return [extra], "is not a known field", "Remove it or correct its spelling"
    if keyword == "dependentRequired":
        name = next(name for name, needed in expected.items() if name in instance
                    and any(item not in instance for item in needed))
        needed = next(item for item in expected[name] if item not in instance)
        return [needed], f"is missing; {name} needs it", f"Add {needed} or remove {name}"
    if keyword in {"minItems", "maxItems"}:
        bound = "at least" if keyword == "minItems" else "at most"
        return [], f"must hold {bound} {expected} items, not {len(instance)}", \
            f"{'Add' if keyword == 'minItems' else 'Remove'} items"
    if keyword in {"minLength", "maxLength"}:
        if keyword == "minLength" and expected == 1:
            return [], "must not be empty", "Write a value"
        bound = "at least" if keyword == "minLength" else "at most"
        return [], f"must be {bound} {expected} characters long, not {len(instance)}", \
            f"{'Lengthen' if keyword == 'minLength' else 'Shorten'} it"
    if keyword == "pattern":
        if expected == "\\S":
            return [], "must not be blank", "Write a value"
        return [], f"{_shown(instance)} does not have the form {expected}", \
            "Write a value of that form"
    if keyword in {"minProperties", "maxProperties"}:
        bound = "at least" if keyword == "minProperties" else "at most"
        return [], f"must hold {bound} {expected} fields, not {len(instance)}", \
            f"{'Add' if keyword == 'minProperties' else 'Remove'} fields"
    if keyword in {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"}:
        bound = {"minimum": "at least", "maximum": "at most",
                 "exclusiveMinimum": "more than", "exclusiveMaximum": "less than"}[keyword]
        return [], f"must be {bound} {expected}, not {_shown(instance)}", f"Write a number {bound} {expected}"
    if keyword == "uniqueItems":
        return [], "repeats an item", "Remove the repeated item"
    if keyword == "not":
        if isinstance(expected, dict) and "enum" in expected:
            return [], f"{_shown(instance)} is reserved", "Choose another name"
        if isinstance(expected, dict) and list(expected) == ["required"]:
            names = " and ".join(expected["required"])
            return [], f"cannot hold both {names}", "Keep only one of them"
        return [], "is not allowed here", expected.get("description", "Remove it") \
            if isinstance(expected, dict) else "Remove it"
    if keyword in {"oneOf", "anyOf"} and isinstance(instance, dict) and all(
        isinstance(branch, dict) and len(branch.get("required", [])) == 1 for branch in expected
    ):
        names = ", ".join(branch["required"][0] for branch in expected)
        held = [name for name in (branch["required"][0] for branch in expected) if name in instance]
        amount = "exactly one" if keyword == "oneOf" else "at least one"
        return [], f"must hold {amount} of {names}, not {', '.join(held) or 'none'}", \
            "Keep one of them" if held else "Add one of them"
    if keyword in {"oneOf", "anyOf"}:
        return [], f"{_shown(instance)} matches none of the allowed forms", \
            "Write one of the forms the contract describes"
    return [], f"{_shown(instance)} is invalid", "Correct it as the contract describes"


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


def parse_card_spec(text: str, source_path: object, place: str = "cards fence") -> dict[str, object]:
    try:
        specification = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise input_error(source_path, place, f"is not valid YAML: {error}",
                          "Write JSON or YAML; see capabilities/cards-metrics") from error
    cards = specification.get("cards") if isinstance(specification, dict) else None
    for index, card in enumerate(cards if isinstance(cards, list) else []):
        refuse_moved_keys(card, "card", source_path, f"cards[{index}]", place, "capabilities/cards-metrics")
        metrics = card.get("metrics") if isinstance(card, dict) else None
        for number, metric in enumerate(metrics if isinstance(metrics, list) else []):
            refuse_moved_keys(metric, "metric", source_path, f"cards[{index}].metrics[{number}]", place,
                              "capabilities/cards-metrics")
    error = schema_error(list(_validator("cards").iter_errors(specification)), source_path,
                         "capabilities/cards-metrics", place=place)
    if error:
        raise error
    return specification


def validate_count_query(query: object, source_path: object, field: str = "query") -> None:
    error = schema_error(list(_validator("countQuery").iter_errors(query)), source_path,
                         "capabilities/queries", field=field)
    if error:
        raise error


def parse_property_editor(
    text: str, source_path: object, place: str = "property-editor fence",
) -> dict[str, object]:
    try:
        specification = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise input_error(source_path, place, f"is not valid YAML: {error}",
                          "Write YAML; see capabilities/property-editors") from error
    error = schema_error(list(_validator("propertyEditor").iter_errors(specification)), source_path,
                         "capabilities/property-editors", place=place)
    if error:
        raise error
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
        "title": line[match.end():].strip() or _default_callout_title(kind, match["keyword"]),
    }


def _default_callout_title(kind: str, keyword: str) -> str:
    """An untitled callout's title: its keyword capitalized, none for important; see input-model."""
    return "" if kind == "important" else keyword[0].upper() + keyword[1:].lower()


_QUANTITY_ALIAS = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,39}")
_NOTE_LINK = re.compile(r"(?<!!)\[[^\]]+\]\([^)]+\)|\[\[[^\]]+\]\]")


def validate_quantity(metadata: dict[str, object], source_path: object) -> None:
    """Validate a quantity note's frontmatter; see capabilities/quantities."""

    def fail(field: str, problem: str, remedy: str) -> None:
        raise input_error(source_path, field, problem, f"{remedy[0].upper()}{remedy[1:]}; "
                          "see capabilities/quantities")

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
        validate_count_query(metadata["query"], source_path)
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


def _validate_schema(name: str, value: object, source_path: object, reference: str,
                     field: str = "", place: str = "") -> None:
    schema = json.loads(files("obs").joinpath(name).read_text(encoding="utf-8"))
    error = schema_error(list(Draft202012Validator(schema).iter_errors(value)), source_path,
                         reference, field=field, place=place)
    if error:
        raise error


def validate_base_definition(definition: object, source_path: object, place: str = "") -> None:
    refuse_moved_keys(definition, "base", source_path, "", place, "capabilities/bases")
    views = definition.get("views") if isinstance(definition, dict) else None
    for index, view in enumerate(views if isinstance(views, list) else []):
        refuse_moved_keys(view, "view", source_path, f"views[{index}]", place, "capabilities/bases")
    profile = definition.get("obs") if isinstance(definition, dict) else None
    if isinstance(profile, dict) and "members" in profile:
        raise input_error(source_path, ", ".join(item for item in (place, "obs.members") if item),
                          "belongs to a view, not to the Base",
                          "Move it into the obs of each view it narrows; see capabilities/bases")
    _validate_schema("base.schema.json", definition, source_path, "capabilities/bases", place=place)


def validate_note_profile(metadata: dict[str, object], source_path: object) -> None:
    """Check a note's frontmatter profile: its obs mapping, and no key moved out of an adapter's."""
    refuse_moved_keys(metadata, "note", source_path, "", "", "capabilities/profiles")
    if "obs" in metadata:
        _validate_schema("note-profile.schema.json", metadata["obs"], source_path, "capabilities/profiles",
                         field="obs")


MOVED_KEYS = {
    "obsHtml": {
        "base": {"records": "obs.records", "members": "views[].obs.members"},
        "view": {"records": "obs.records", "members": "obs.members"},
        "card": {"metricsFrom": "obs.metricsFrom"},
        "metric": {"projection": "obs.projection"},
        "note": {"document": "obs.document"},
    },
}
"""Per adapter namespace and input contract, each key the core read there and its key under obs, the
core's namespace, with the same meaning; the core reads neither the old key nor an adapter's
namespace (input-model#Core and adapter namespaces)."""


ADAPTER_NAMESPACE = re.compile(r"obs[A-Z][A-Za-z0-9]*")
"""An adapter's namespace: obs and its name in camelCase (capabilities/trusted-actions), as
base.schema.json's patternProperties; the core neither reads nor validates it."""


def refuse_moved_keys(mapping: object, contract: str, source_path: object, field: str, place: str,
                      reference: str) -> None:
    """Refuse a key the core reads written under an adapter's namespace, naming its key under obs."""
    if not isinstance(mapping, dict):
        return
    prefix = f"{field}." if field else ""
    for namespace, contracts in MOVED_KEYS.items():
        options = mapping.get(namespace)
        moved = next((key for key in contracts[contract] if isinstance(options, dict) and key in options), None)
        if moved is not None:
            new = f"{prefix}{contracts[contract][moved]}"
            raise input_error(source_path, ", ".join(item for item in (place, f"{prefix}{namespace}.{moved}") if item),
                              f"the core reads this key as {new}, not in the adapter namespace {namespace}",
                              f"Rename it to {new}; see {reference}")


RENAMED_MANIFEST_FIELDS = {"sap number": "document number"}
"""Each manifest field the core no longer reads and the field that replaced it, with the same
meaning; the old field is an input error, never an alias (input-model#Cover metadata and history)."""


def refuse_renamed_manifest_fields(metadata: dict[str, object], source_path: object) -> None:
    """Refuse a renamed manifest field, naming the manifest, the old field and the new one."""
    for old, new in RENAMED_MANIFEST_FIELDS.items():
        if old in metadata:
            raise input_error(source_path, old, f"the manifest names this field {new}",
                              f"Rename it to {new}; see input-model#Cover metadata and history")


def validate_project_config(configuration: object, source_path: object) -> None:
    _validate_schema("project.schema.json", configuration, source_path, "configuration")
