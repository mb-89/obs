import json
import re
import subprocess
import sys

import pytest

from obs.config import CoreConfigError, load_core_config
from obs.document import DocumentError, build_document
from obs.input import (
    InputError,
    parse_card_spec,
    parse_callout,
    parse_property_editor,
    validate_base_definition,
    validate_command,
    validate_count_query,
    validate_note_profile,
    validate_project_config,
)


def test_core_input_contracts_validate_without_loading_adapter(tmp_path) -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import obs.input; import sys; raise SystemExit('obs_html_interim' in sys.modules)"],
        check=False,
    )
    assert result.returncode == 0

    config_path = tmp_path / "cfg.json"
    config_path.write_text(
        json.dumps(
            {
                "input": {
                    "manifestFilename": "manifest.md",
                    "projectConfigFilename": "project.json",
                },
                "execution": {"commandTimeoutSeconds": 5},
                "artifact": {"tablePageSize": 20},
            }
        ),
        encoding="utf-8",
    )

    config = load_core_config(config_path)

    assert config.manifest_filename == "manifest.md"
    assert config.project_config_filename == "project.json"
    assert config.command_timeout_seconds == 5


def test_core_input_contracts_reject_invalid_data_only_inputs(tmp_path) -> None:
    with pytest.raises(InputError, match=r"^A cmd fence cannot be empty\.$"):
        validate_command(" \t")
    note = tmp_path / "note.md"
    with pytest.raises(InputError, match=rf"^{re.escape(str(note))}: cards fence, cards: must hold "
                                         r"at least 1 items, not 0\. Add items; see "
                                         r"capabilities/cards-metrics\.$"):
        parse_card_spec('{"version": 1, "cards": []}', note)
    with pytest.raises(InputError, match=rf"^{re.escape(str(note))}: property-editor fence, label: "
                                         r"is missing\. Add label; see capabilities/property-editors\.$"):
        parse_property_editor("version: 1\nfield: title\n", note, {})
    with pytest.raises(CoreConfigError, match=r"^Invalid core configuration: "):
        load_core_config(tmp_path / "missing.json")


def test_core_input_contracts_parse_semantic_callout_and_queries() -> None:
    assert parse_callout("[!warning]- Investigate") == {
        "type": "warning",
        "tone": "warning",
        "fold": "-",
        "title": "Investigate",
    }
    assert parse_callout("[!unknown] Not a callout") is None

    spec = parse_card_spec(
        '{"version": 1, "cards": [{"title": "Coverage", "body": "", '
        '"metrics": [{"label": "Known", "where": []}]}]}',
        "note.md",
    )
    assert spec["cards"][0]["metrics"][0]["where"] == []


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("cards", '{"version": 1, "cards": []}'),
        ("query", {"where": "invalid"}),
        ("property", "version: 1\nfield: title\n"),
        ("base", {}),
        ("profile", {"obs": {"layout": "invalid"}}),
        ("project", {"input": {"manifestFilename": "bad"}}),
        ("command", ""),
    ],
)
def test_core_contracts_reject_invalid_input(name, value, tmp_path) -> None:
    validators = {
        "cards": lambda: parse_card_spec(value, tmp_path),
        "query": lambda: validate_count_query(value, tmp_path),
        "property": lambda: parse_property_editor(value, tmp_path, {}),
        "base": lambda: validate_base_definition(value, tmp_path),
        "profile": lambda: validate_note_profile(value, tmp_path),
        "project": lambda: validate_project_config(value, tmp_path),
        "command": lambda: validate_command(value),
    }
    with pytest.raises(InputError):
        validators[name]()


def test_document_construction_uses_core_fence_and_frontmatter_contracts(tmp_path) -> None:
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "chapter.md").write_text(
        "---\nquery: {where: invalid}\n---\n"
        "```cards\n{\"version\": 1, \"cards\": []}\n```\n"
        "```cmd\n\n```\n",
        encoding="utf-8",
    )

    reference = {"capabilities": [], "schemaVersion": 1}
    with pytest.raises(DocumentError, match=rf"^{re.escape(str(tmp_path / 'chapter.md'))}: query\.where: "):
        build_document(manifest, reference)


def _error_message(callback) -> str:
    with pytest.raises(Exception) as raised:
        callback()
    return str(raised.value)


def test_core_and_adapter_contract_errors_match_for_shared_inputs(tmp_path) -> None:
    from obs_html_interim.cards import parse_card_spec as parse_adapter_cards
    from obs_html_interim.cards import validate_count_query as validate_adapter_count_query
    from obs_html_interim.commands import run_command
    from obs_html_interim.content import _validate_note_profile, validate_base_definition as validate_adapter_base
    from obs_html_interim.properties import property_editors
    from markdown_it import MarkdownIt

    card = '{"version": 1, "cards": []}'
    query = {"where": "invalid"}
    base = {}
    property_editor = "version: 1\nfield: title\n"
    token = next(token for token in MarkdownIt().parse(f"```property-editor\n{property_editor}```\n")
                 if token.type == "fence")

    class Chapter:
        source_path = tmp_path

    assert _error_message(lambda: parse_card_spec(card, tmp_path)) == _error_message(
        lambda: parse_adapter_cards(card, tmp_path)
    )
    assert _error_message(lambda: validate_count_query(query, tmp_path)) == _error_message(
        lambda: validate_adapter_count_query(query, tmp_path)
    )
    assert _error_message(lambda: validate_base_definition(base, tmp_path)) == _error_message(
        lambda: validate_adapter_base(base, tmp_path)
    )
    assert _error_message(lambda: validate_note_profile({"obs": {"document": "maybe"}}, tmp_path)) == _error_message(
        lambda: _validate_note_profile({"document": "maybe"}, tmp_path)
    ).replace("obsHtml.", "obs.")
    assert _error_message(lambda: parse_property_editor(property_editor, tmp_path, {})) == _error_message(
        lambda: property_editors([token], Chapter(), {})
    )
    assert _error_message(lambda: validate_command("")) == _error_message(
        lambda: run_command("", tmp_path, 5)
    )


FULL_CARD_SPEC = {
    "version": 1,
    "cards": [{
        "title": "Coverage", "body": "Current state.", "metricStyle": "lines",
        "obs": {"metricsFrom": {
            "sourceNote": "registers/risks", "property": "summary.groups",
            "labelProperty": "label", "distinctProperty": "field",
            "where": [{"field": "status", "equals": "open"}],
            "tone": "warning",
            "toneRules": [{"value": "primary", "when": "zero", "tone": "positive"}],
            "link": {"note": "registers/risks", "groupProperty": "group"},
        }},
        "metrics": [{
            "key": "open", "label": "Open", "where": [{"field": "status", "equals": "open"}],
            "from": "queries/findings", "secondary": "queries/closed", "distinct": "owner",
            "denominator": [{"field": "status", "exists": True}],
            "link": "#findings?tableFilter=status%3Aopen", "secondaryLink": "#closed",
            "tone": "neutral",
            "toneRules": [{"value": "remaining", "when": "positive", "tone": "negative"}],
            "obs": {"projection": "review.current"},
        }],
    }],
}


def test_core_cards_contract_accepts_the_full_card_metric_contract() -> None:
    from obs_html_interim.cards import parse_card_spec as parse_adapter_cards

    text = json.dumps(FULL_CARD_SPEC)
    interim = _interim_namespace(text)
    assert parse_card_spec(text, "note.md") == FULL_CARD_SPEC
    assert parse_adapter_cards(interim, "note.md") == json.loads(interim)


def _interim_namespace(text: str) -> str:
    """The same cards in the interim adapter's namespace, which it keeps reading (obs#3 deletes it)."""
    return text.replace('"obs":', '"obsHtml":')


@pytest.mark.parametrize(
    "metric",
    [
        {"secondary": "queries/closed"},
        {"from": "queries/findings", "secondaryLink": "#closed"},
        {"link": "https://example.test"},
        {"tone": "loud"},
        {"toneRules": [{"value": "primary", "when": "zero", "tone": "positive"}] * 9},
        {"obs": {"projection": "Upper"}},
    ],
)
def test_core_cards_contract_rejects_what_the_adapter_rejects(metric) -> None:
    from obs_html_interim.cards import parse_card_spec as parse_adapter_cards

    text = json.dumps({"version": 1, "cards": [{
        "title": "Coverage", "body": "", "metrics": [{"label": "Open", "where": [], **metric}],
    }]})
    assert _error_message(lambda: parse_card_spec(text, "note.md")) == _error_message(
        lambda: parse_adapter_cards(_interim_namespace(text), "note.md")
    ).replace(".obsHtml.", ".obs.")


def _schema_fields(schema: dict[str, object], prefix: str = "") -> list[str]:
    fields = []
    for name, value in schema.get("properties", {}).items():
        path = f"{prefix}{name}"
        fields.append(path)
        fields.extend(_schema_fields(value, f"{path}."))
        if "items" in value:
            fields.extend(_schema_fields(value["items"], f"{path}[]."))
    return fields


def test_cards_capability_note_documents_each_card_field_once() -> None:
    from pathlib import Path

    root = Path(__file__).parents[1]
    schema = json.loads((root / "src" / "obs" / "input.schema.json").read_text(encoding="utf-8"))
    note = (root / "spec" / "capabilities" / "cards-metrics.md").read_text(encoding="utf-8")
    documented = re.findall(r"^- `([A-Za-z.\[\]]+)`", note, re.MULTILINE)
    fields = _schema_fields(schema["$defs"]["cards"])
    assert {"cards[].metrics[].denominator", "cards[].obs.metricsFrom",
            "cards[].metrics[].obs.projection"} <= set(fields)
    assert sorted(documented) == sorted(fields)


VALID_QUANTITY = "kind: quantity\naliases: [maxLoad]\nsource: '[[drawing]]'\nunit: kN\n"


@pytest.mark.parametrize(
    ("frontmatter", "field", "remedy"),
    [
        ("kind: quantity\naliases: [maxLoad]\nsource: '[[drawing]]'\n",
         "value or query", "Add value: <number> or query:"),
        (VALID_QUANTITY + "value: 1\nquery: {where: []}\n", "value or query", "Keep exactly one"),
        (VALID_QUANTITY + "value: 12 kN\n", "value", "put the unit in unit"),
        (VALID_QUANTITY + "value: .inf\n", "value", "put the unit in unit"),
        (VALID_QUANTITY + "value: true\n", "value", "put the unit in unit"),
        (VALID_QUANTITY + "query: {where: invalid}\n", "query.where", "Write a list"),
        (VALID_QUANTITY.replace("unit: kN", "unit: ' '") + "value: 1\n", "unit",
         "or remove unit"),
        (VALID_QUANTITY.replace("aliases: [maxLoad]", "aliases: [maxLoad, peak]") + "value: 1\n",
         "aliases", "Keep one variable-style alias"),
        (VALID_QUANTITY.replace("aliases: [maxLoad]", "aliases: max load") + "value: 1\n",
         "aliases", "Keep one variable-style alias"),
        (VALID_QUANTITY.replace("aliases: [maxLoad]\n", "") + "value: 1\n",
         "aliases", "Keep one variable-style alias"),
        (VALID_QUANTITY.replace("source: '[[drawing]]'\n", "") + "value: 1\n",
         "source", "Link the supporting note"),
        (VALID_QUANTITY.replace("'[[drawing]]'", "the drawing") + "value: 1\n",
         "source", "Link the supporting note"),
    ],
)
def test_core_rejects_an_invalid_quantity_note_naming_note_field_and_remedy(
    tmp_path, frontmatter, field, remedy,
) -> None:
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "chapter.md").write_text("[[load]]\n", encoding="utf-8")
    (tmp_path / "drawing.md").write_text("Drawing.\n", encoding="utf-8")
    (tmp_path / "load.md").write_text(f"---\n{frontmatter}---\nBody.\n", encoding="utf-8")

    message = _error_message(lambda: build_document(tmp_path / "manifest.md", {
        "capabilities": [], "schemaVersion": 1,
    }))

    assert message.startswith(f"{tmp_path / 'load.md'}: {field}: ")
    assert remedy in message
    assert re.search(r"\. [A-Z].*; see capabilities/(quantities|queries)\.$", message), message


@pytest.mark.parametrize(
    "fields",
    ["value: 12.5", "value: -3\nunit: mm", "query: {where: [{field: status, exists: true}]}",
     "value: 1\naliases: maxLoad\nsource: ['[[drawing]]', 'site visit']"],
)
def test_core_accepts_a_valid_quantity_note(tmp_path, fields) -> None:
    (tmp_path / "manifest.md").write_text("- [[load]]\n", encoding="utf-8")
    (tmp_path / "drawing.md").write_text("Drawing.\n", encoding="utf-8")
    frontmatter = "kind: quantity\n" + (
        fields if "aliases" in fields else f"aliases: [maxLoad]\nsource: '[[drawing]]'\n{fields}"
    )
    (tmp_path / "load.md").write_text(f"---\n{frontmatter}\n---\n", encoding="utf-8")

    document = build_document(tmp_path / "manifest.md", {"capabilities": [], "schemaVersion": 1})

    assert document["chapters"][0]["metadata"]["kind"] == "quantity"


RAW_SCHEMA_TEXT = ("is not of type", "is a required property", "Additional properties",
                   "is not one of", "is a dependency of", "is not valid under", "Failed validating")


def _build_message(vault, manifest: str = "- [[chapter]]\n") -> str:
    (vault / "manifest.md").write_text(manifest, encoding="utf-8")
    return _error_message(lambda: build_document(vault / "manifest.md", {
        "capabilities": [], "schemaVersion": 1,
    }))


def test_an_invalid_quantity_query_names_the_note_the_field_and_a_remedy(tmp_path) -> None:
    (tmp_path / "chapter.md").write_text("[[load]]\n", encoding="utf-8")
    (tmp_path / "drawing.md").write_text("Drawing.\n", encoding="utf-8")
    (tmp_path / "load.md").write_text(
        f"---\n{VALID_QUANTITY}query: {{where: invalid}}\n---\n", encoding="utf-8",
    )

    message = _build_message(tmp_path)

    assert message == (
        f"{tmp_path / 'load.md'}: query.where: must be a list, not \"invalid\". "
        "Write a list; see capabilities/queries."
    )


def test_a_non_boolean_document_profile_names_the_note_the_field_and_a_remedy(tmp_path) -> None:
    (tmp_path / "chapter.md").write_text("---\nobs: {document: maybe}\n---\nBody.\n",
                                         encoding="utf-8")

    message = _build_message(tmp_path)

    assert message == (
        f"{tmp_path / 'chapter.md'}: obs.document: must be true or false, not \"maybe\". "
        "Write true or false; see capabilities/profiles."
    )


INVALID_CONTRACTS = {
    "quantity": ("load.md", f"---\n{VALID_QUANTITY}query: {{where: [{{field: 1, exists: true}}]}}\n---\n",
                 "query.where[0].field", "capabilities/queries"),
    "note profile": ("chapter.md", "---\nobs: {document: maybe}\n---\n",
                     "obs.document", "capabilities/profiles"),
    "query": ("chapter.md", "---\nquery: {where: [{equals: open}]}\n---\n",
              "query.where[0].field", "capabilities/queries"),
    "base fence": ("chapter.md", "```base\nviews:\n  - type: table\n```\n",
                   "base fence 1, views[0].order", "capabilities/bases"),
    "cards fence": ("chapter.md", '```cards\n{"version": 1, "cards": [{"title": "T", "body": "", '
                    '"metrics": [{"label": "L", "where": [], "tone": "loud"}]}]}\n```\n',
                    "cards fence 1, cards[0].metrics[0].tone", "capabilities/cards-metrics"),
    "property-editor fence": ("chapter.md", "```property-editor\nversion: 1\nfield: title\n```\n",
                              "property-editor fence 1, label", "capabilities/property-editors"),
    "figure fence": ("chapter.md", '```figure\nversion: 1\nkind: plot\ncontent: {"schemaVersion": 1}\n```\n',
                     "figure fence 1, content.id", "capabilities/figure-descriptor"),
    "figure fence kind": ("chapter.md", "```figure\nversion: 1\n```\n", "figure fence 1, kind",
                          "capabilities/figures"),
    "embedded base": ("x.base", "views:\n  - type: table\n", "views[0].order", "capabilities/bases"),
}


@pytest.mark.parametrize("contract", INVALID_CONTRACTS)
def test_every_validated_contract_names_the_note_and_the_field(tmp_path, contract) -> None:
    note, text, field, reference = INVALID_CONTRACTS[contract]
    (tmp_path / "drawing.md").write_text("Drawing.\n", encoding="utf-8")
    if note != "chapter.md":
        (tmp_path / "chapter.md").write_text(
            "![[x.base]]\n" if note == "x.base" else f"[[{note[:-3]}]]\n", encoding="utf-8",
        )
    (tmp_path / note).write_text(text, encoding="utf-8")

    message = _build_message(tmp_path)

    assert message.startswith(f"{tmp_path / note}: {field}: "), message
    assert f"; see {reference}." in message
    assert not any(raw in message for raw in RAW_SCHEMA_TEXT), message


def test_the_project_configuration_names_the_file_and_the_field(tmp_path) -> None:
    message = _error_message(lambda: validate_project_config(
        {"input": {"manifestFilename": 1}}, tmp_path / "project.json",
    ))

    assert message.startswith(f"{tmp_path / 'project.json'}: input.manifestFilename: "), message
    assert "; see configuration." in message


@pytest.mark.parametrize(
    ("schema", "value", "expected"),
    [
        ({"type": "boolean"}, "maybe", 'x: must be true or false, not "maybe". Write true or false'),
        ({"enum": ["a", "b"]}, "c", 'x: must be one of "a", "b", not "c". Write one of them'),
        ({"const": True}, False, "x: must be true, not false. Write true"),
        ({"required": ["id"]}, {}, "x.id: is missing. Add id"),
        ({"additionalProperties": False}, {"y": 1}, "x.y: is not a known field. Remove it or correct its spelling"),
        ({"dependentRequired": {"b": ["a"]}}, {"b": 1}, "x.a: is missing; b needs it. Add a or remove b"),
        ({"minItems": 2}, [1], "x: must hold at least 2 items, not 1. Add items"),
        ({"maxItems": 1}, [1, 2], "x: must hold at most 1 items, not 2. Remove items"),
        ({"minLength": 1}, "", "x: must not be empty. Write a value"),
        ({"minLength": 3}, "ab", "x: must be at least 3 characters long, not 2. Lengthen it"),
        ({"maxLength": 1}, "ab", "x: must be at most 1 characters long, not 2. Shorten it"),
        ({"pattern": "\\S"}, " ", "x: must not be blank. Write a value"),
        ({"pattern": "^a$"}, "b", 'x: "b" does not have the form ^a$. Write a value of that form'),
        ({"minProperties": 1}, {}, "x: must hold at least 1 fields, not 0. Add fields"),
        ({"maxProperties": 0}, {"a": 1}, "x: must hold at most 0 fields, not 1. Remove fields"),
        ({"minimum": 1}, 0, "x: must be at least 1, not 0. Write a number at least 1"),
        ({"maximum": 1}, 2, "x: must be at most 1, not 2. Write a number at most 1"),
        ({"exclusiveMinimum": 0}, 0, "x: must be more than 0, not 0. Write a number more than 0"),
        ({"exclusiveMaximum": 0}, 0, "x: must be less than 0, not 0. Write a number less than 0"),
        ({"uniqueItems": True}, [1, 1], "x: repeats an item. Remove the repeated item"),
        ({"not": {"enum": ["title"]}}, "title", 'x: "title" is reserved. Choose another name'),
        ({"not": {"required": ["a", "b"]}}, {"a": 1, "b": 2}, "x: cannot hold both a and b. Keep only one of them"),
        ({"not": {}}, 1, "x: is not allowed here. Remove it"),
        ({"oneOf": [{"required": ["a"]}, {"required": ["b"]}]}, {},
         "x: must hold exactly one of a, b, not none. Add one of them"),
        ({"oneOf": [{"required": ["a"]}, {"required": ["b"]}]}, {"a": 1, "b": 1},
         "x: must hold exactly one of a, b, not a, b. Keep one of them"),
        ({"anyOf": [{"type": "string"}, {"type": "integer"}]}, [],
         "x: [] matches none of the allowed forms. Write one of the forms the contract describes"),
        ({"multipleOf": 2}, 3, "x: 3 is invalid. Correct it as the contract describes"),
    ],
)
def test_each_schema_failure_has_its_own_problem_and_remedy(schema, value, expected) -> None:
    from jsonschema import Draft202012Validator

    from obs.input import schema_error

    error = schema_error(list(Draft202012Validator(schema).iter_errors(value)), "note.md",
                         "capabilities/queries", field="x")

    assert str(error) == f"note.md: {expected}; see capabilities/queries."


def test_a_file_top_level_and_a_fence_place_name_where_the_failure_is() -> None:
    from jsonschema import Draft202012Validator

    from obs.input import schema_error

    def message(schema, value, **where) -> str:
        return str(schema_error(list(Draft202012Validator(schema).iter_errors(value)), "x.base",
                                "capabilities/bases", **where))

    assert message({"type": "object"}, []) == (
        "x.base: top level: must be a mapping, not []. Write a mapping; see capabilities/bases."
    )
    assert message({"required": ["views"]}, {}, place="base fence 2") == (
        "x.base: base fence 2, views: is missing. Add views; see capabilities/bases."
    )
    assert schema_error([], "x.base", "capabilities/bases") is None


@pytest.mark.parametrize(
    ("fence", "expected"),
    [
        ("```cards\n{unclosed\n```\n", r"cards fence 1: is not valid YAML: .*\. Write JSON or YAML; "
         r"see capabilities/cards-metrics\.$"),
        ("```property-editor\n{unclosed\n```\n", r"property-editor fence 1: is not valid YAML: .*\. "
         r"Write YAML; see capabilities/property-editors\.$"),
        ("```base\n{unclosed\n```\n", r"base fence 1: is not valid YAML: .*\. Write YAML; "
         r"see capabilities/bases\.$"),
        ("```figure\n[1]\n```\n", r"figure fence 1: must be a mapping, not \[1\]\. Write a mapping; "
         r"see capabilities/figures\.$"),
        ("```base\nviews: []\n```\n```base\nviews: 1\n```\n", r"base fence 2, views: must be a list"),
        ("```cmd\necho ok\n```\n```cmd\n\n```\n", r"cmd fence 2: is empty\. Write the command to run "
         r"or remove the fence; see capabilities/command-fences\.$"),
    ],
)
def test_an_unreadable_fence_names_the_note_and_the_fence(tmp_path, fence, expected) -> None:
    (tmp_path / "chapter.md").write_text(fence, encoding="utf-8")

    message = _build_message(tmp_path)

    assert re.match(re.escape(f"{tmp_path / 'chapter.md'}: ") + expected, message, re.DOTALL), message


def test_the_adapter_names_a_nested_cards_fence_by_note_fence_and_card() -> None:
    from obs_html_interim.cards import parse_card_spec as parse_adapter_cards

    body = "```cards\\n{}\\n```"
    text = f'{{"version": 1, "cards": [{{"title": "T", "body": "{body}", "metrics": []}}]}}'

    assert _error_message(lambda: parse_adapter_cards(text, "note.md")) == (
        "note.md: cards fence, cards[0].body: contains a nested cards fence. Move the inner cards "
        "fence out of the card body; see capabilities/cards-metrics."
    )


@pytest.mark.parametrize("document", [True, False])
def test_a_boolean_document_profile_is_accepted(tmp_path, document) -> None:
    validate_note_profile({"obs": {"document": document}}, tmp_path / "chapter.md")
