"""Explicit note-local text editing declarations."""
from functools import cache
from html import escape
from importlib.resources import files
import json
import math

from jsonschema import Draft202012Validator
import yaml

from obs.input import input_error, schema_error


def _projection_kind(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        try:
            return "number" if math.isfinite(value) else None
        except OverflowError:
            return None
    if isinstance(value, list):
        kinds = {_projection_kind(item) for item in value}
        return "array" if None not in kinds and len(kinds) <= 1 else None
    return None


def _projection_matches(existing, projected):
    existing_kind = _projection_kind(existing)
    projected_kind = _projection_kind(projected)
    if existing_kind != projected_kind or projected_kind is None:
        return False
    if projected_kind != "array" or not existing or not projected:
        return True
    return _projection_kind(existing[0]) == _projection_kind(projected[0])


@cache
def _schema():
    # Every note asks for editors; reading the packaged schema once avoids a file read per note.
    schema = json.loads(files("obs_html_interim").joinpath("property-editor.schema.json").read_text(encoding="utf-8"))
    return schema, Draft202012Validator(schema), frozenset(schema["$defs"]["editableField"]["not"]["enum"])


def property_editors(tokens, chapter, frontmatter):
    from obs_html_interim.content import ContentError

    editors = {}
    for token in tokens:
        if token.type != "fence" or token.info.strip() != "property-editor":
            continue
        schema, validator, protected_fields = _schema()
        place = "property-editor fence"
        try:
            spec = yaml.safe_load(token.content)
        except yaml.YAMLError as error:
            raise ContentError(str(input_error(
                chapter.source_path, place, f"is not valid YAML: {error}",
                "Write YAML; see capabilities/property-editors",
            ))) from error
        error = schema_error(list(validator.iter_errors(spec)), chapter.source_path,
                             "capabilities/property-editors", place=place)
        if error:
            raise ContentError(str(error))
        field = spec["field"]
        limit = spec.get("maxLength", schema["properties"]["maxLength"]["default"])
        if field.lower() in protected_fields:
            raise ContentError(f"Property editor cannot change a protected field: {field}")
        if chapter.generated or not isinstance(frontmatter.get(field), str):
            raise ContentError(f"Property editor requires an existing string field on an authored note: {field}")
        if len(frontmatter[field]) > limit:
            raise ContentError(f"Property editor initial text exceeds maxLength: {field}")
        if field in editors:
            raise ContentError(f"Property editor field is declared more than once: {field}")
        definition = {"label": spec["label"], "maxLength": limit}
        projection = spec.get("projection")
        if projection is not None:
            for branch in ("blank", "nonblank"):
                for projected_field, value in projection[branch].items():
                    if (projected_field == field or projected_field.lower() in protected_fields or
                            projected_field not in frontmatter or
                            not _projection_matches(frontmatter[projected_field], value)):
                        raise ContentError(
                            f"Property editor projection must match an existing field type: {projected_field}"
                        )
            definition["projection"] = projection
        editors[field] = definition
    return editors


def render_property_editor(text, chapter, editors):
    spec = yaml.safe_load(text)
    field = spec["field"]
    definition = editors[field]
    return (
        '<label class="property-editor">'
        f'<span>{escape(definition["label"])}</span>'
        f'<textarea data-property-editor data-property-note="{escape(chapter.slug, quote=True)}" '
        f'data-property-field="{escape(field, quote=True)}" maxlength="{definition["maxLength"]}" '
        f'aria-label="{escape(definition["label"], quote=True)}" rows="2"></textarea>'
        '</label>\n'
    )
