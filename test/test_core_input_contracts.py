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
        [sys.executable, "-c", "import obs.input; import sys; raise SystemExit('obs_html' in sys.modules)"],
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
    with pytest.raises(InputError, match=r"^Cards: "):
        parse_card_spec('{"version": 1, "cards": []}')
    with pytest.raises(InputError, match=r"^Property editor: "):
        parse_property_editor("version: 1\nfield: title\n")
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
        '"metrics": [{"label": "Known", "where": []}]}]}'
    )
    assert spec["cards"][0]["metrics"][0]["where"] == []


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("cards", '{"version": 1, "cards": []}'),
        ("query", {"where": "invalid"}),
        ("property", "version: 1\nfield: title\n"),
        ("base", {}),
        ("profile", {"layout": "invalid"}),
        ("project", {"input": {"manifestFilename": "bad"}}),
        ("command", ""),
    ],
)
def test_core_contracts_reject_invalid_input(name, value, tmp_path) -> None:
    validators = {
        "cards": lambda: parse_card_spec(value),
        "query": lambda: validate_count_query(value),
        "property": lambda: parse_property_editor(value),
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
    with pytest.raises(DocumentError, match=r"^Quantity query: "):
        build_document(manifest, reference)


def _error_message(callback) -> str:
    with pytest.raises(Exception) as raised:
        callback()
    return str(raised.value)


def test_core_and_adapter_contract_errors_match_for_shared_inputs(tmp_path) -> None:
    from obs_html.cards import parse_card_spec as parse_adapter_cards
    from obs_html.cards import validate_count_query as validate_adapter_count_query
    from obs_html.commands import run_command
    from obs_html.content import _validate_note_profile, validate_base_definition as validate_adapter_base
    from obs_html.properties import property_editors
    from markdown_it import MarkdownIt

    card = '{"version": 1, "cards": []}'
    query = {"where": "invalid"}
    base = {}
    profile = {"layout": "invalid"}
    property_editor = "version: 1\nfield: title\n"
    token = next(token for token in MarkdownIt().parse(f"```property-editor\n{property_editor}```\n")
                 if token.type == "fence")

    class Chapter:
        source_path = tmp_path

    assert _error_message(lambda: parse_card_spec(card)) == _error_message(
        lambda: parse_adapter_cards(card)
    )
    assert _error_message(lambda: validate_count_query(query)) == _error_message(
        lambda: validate_adapter_count_query(query)
    )
    assert _error_message(lambda: validate_base_definition(base, tmp_path)) == _error_message(
        lambda: validate_adapter_base(base, tmp_path)
    )
    assert _error_message(lambda: validate_note_profile(profile, tmp_path)) == _error_message(
        lambda: _validate_note_profile(profile, tmp_path)
    )
    assert _error_message(lambda: parse_property_editor(property_editor, tmp_path)) == _error_message(
        lambda: property_editors([token], Chapter(), {})
    )
    assert _error_message(lambda: validate_command("")) == _error_message(
        lambda: run_command("", tmp_path, 5)
    )


FULL_CARD_SPEC = {
    "version": 1,
    "cards": [{
        "title": "Coverage", "body": "Current state.", "metricStyle": "lines",
        "obsHtml": {"metricsFrom": {
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
            "obsHtml": {"projection": "review.current"},
        }],
    }],
}


def test_core_cards_contract_accepts_the_full_card_metric_contract() -> None:
    from obs_html.cards import parse_card_spec as parse_adapter_cards

    text = json.dumps(FULL_CARD_SPEC)
    assert parse_card_spec(text) == FULL_CARD_SPEC == parse_adapter_cards(text)


@pytest.mark.parametrize(
    "metric",
    [
        {"secondary": "queries/closed"},
        {"from": "queries/findings", "secondaryLink": "#closed"},
        {"link": "https://example.test"},
        {"tone": "loud"},
        {"toneRules": [{"value": "primary", "when": "zero", "tone": "positive"}] * 9},
        {"obsHtml": {"projection": "Upper"}},
    ],
)
def test_core_cards_contract_rejects_what_the_adapter_rejects(metric) -> None:
    from obs_html.cards import parse_card_spec as parse_adapter_cards

    text = json.dumps({"version": 1, "cards": [{
        "title": "Coverage", "body": "", "metrics": [{"label": "Open", "where": [], **metric}],
    }]})
    assert _error_message(lambda: parse_card_spec(text)) == _error_message(
        lambda: parse_adapter_cards(text)
    )


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
    assert {"cards[].metrics[].denominator", "cards[].obsHtml.metricsFrom",
            "cards[].metrics[].obsHtml.projection"} <= set(fields)
    assert sorted(documented) == sorted(fields)


VALID_QUANTITY = "kind: quantity\naliases: [maxLoad]\nsource: '[[drawing]]'\nunit: kN\n"


@pytest.mark.parametrize(
    ("frontmatter", "field", "remedy"),
    [
        ("kind: quantity\naliases: [maxLoad]\nsource: '[[drawing]]'\n",
         "value or query", "add value: <number> or query:"),
        (VALID_QUANTITY + "value: 1\nquery: {where: []}\n", "value or query", "keep exactly one"),
        (VALID_QUANTITY + "value: 12 kN\n", "value", "put the unit in unit"),
        (VALID_QUANTITY + "value: .inf\n", "value", "put the unit in unit"),
        (VALID_QUANTITY + "value: true\n", "value", "put the unit in unit"),
        (VALID_QUANTITY + "query: {where: invalid}\n", "query", "write query: {where:"),
        (VALID_QUANTITY.replace("unit: kN", "unit: ' '") + "value: 1\n", "unit",
         "or remove unit"),
        (VALID_QUANTITY.replace("aliases: [maxLoad]", "aliases: [maxLoad, peak]") + "value: 1\n",
         "aliases", "keep one variable-style alias"),
        (VALID_QUANTITY.replace("aliases: [maxLoad]", "aliases: max load") + "value: 1\n",
         "aliases", "keep one variable-style alias"),
        (VALID_QUANTITY.replace("aliases: [maxLoad]\n", "") + "value: 1\n",
         "aliases", "keep one variable-style alias"),
        (VALID_QUANTITY.replace("source: '[[drawing]]'\n", "") + "value: 1\n",
         "source", "link the supporting note"),
        (VALID_QUANTITY.replace("'[[drawing]]'", "the drawing") + "value: 1\n",
         "source", "link the supporting note"),
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

    assert message.startswith(f"Quantity note {tmp_path / 'load.md'}: {field} ")
    assert remedy in message


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
