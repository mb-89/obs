"""The core's Bases filter and query condition evaluators against the shared conformance fixture.

The HTML adapter's browser evaluators run the same fixture in its own
``bases-filter-conformance.test.js``.
"""
import json
from pathlib import Path

import pytest


FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "bases-filter-conformance.json").read_text(encoding="utf-8")
)


def _vault(tmp_path: Path, chapter: str, manifest_frontmatter: str = "") -> Path:
    manifest = tmp_path / "manifest.md"
    manifest.write_text(f"{manifest_frontmatter}- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "chapter.md").write_text(chapter, encoding="utf-8")
    return manifest


FENCE = "```base\n{filters}views:\n  - type: table\n    order: [kind]\n{view_filters}```\n\n"


@pytest.mark.parametrize("filters, view_filters, field, expression", [
    ("filters: 'status.contains(\"x\")'\n", "", "filters", 'status.contains("x")'),
    ("", "    filters:\n      or: ['kind == \"a\"', 'kind > 1']\n", "views[0].filters", "kind > 1"),
])
def test_the_core_names_the_note_fence_field_and_expression_of_an_unsupported_fence_filter(
        tmp_path, filters, view_filters, field, expression):
    from obs.document import DocumentError, build_document
    from test_vault import capability_reference

    valid = FENCE.format(filters="filters: 'kind == \"a\"'\n", view_filters="")
    invalid = FENCE.format(filters=filters, view_filters=view_filters)
    manifest = _vault(tmp_path, "# Chapter\n\n" + valid + invalid)
    with pytest.raises(DocumentError) as error:
        build_document(manifest, capability_reference())
    message = str(error.value)
    assert message.startswith(f"{tmp_path / 'chapter.md'}: base fence 2, {field}: "), message
    assert expression in message, message
    assert message.endswith("; see input-model#Bases filter grammar."), message


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda case: json.dumps(case["filter"]))
def test_core_evaluator_matches_fixture(case):
    from obs.selection import compile_base_filter as core_filter, note_value

    predicate = core_filter(case["filter"])
    actual = [
        record["id"] for record in FIXTURE["records"]
        if predicate(lambda field, record=record: note_value(record["frontmatter"], record["path"], field))
    ]
    assert actual == case["expected"]


@pytest.mark.parametrize("case", FIXTURE["conditions"], ids=lambda case: json.dumps(case["where"]))
def test_core_conditions_match_fixture(case):
    from obs.selection import conditions_select

    actual = [
        record["id"] for record in FIXTURE["records"]
        if conditions_select(case["where"], record["frontmatter"], record["path"],
                             [(mark["category"], mark["id"]) for mark in record.get("marks", [])])
    ]
    assert actual == case["expected"]


@pytest.mark.parametrize("filters", FIXTURE["unsupported"], ids=json.dumps)
def test_core_evaluator_rejects_unsupported_filters(filters):
    from obs.input import InputError
    from obs.selection import compile_base_filter as core_filter

    with pytest.raises(InputError, match="Unsupported Bases"):
        core_filter(filters)


def test_core_and_adapter_schemas_share_the_comparison_pattern():
    def pattern(package: Path) -> str:
        return json.loads((package / "base.schema.json").read_text(encoding="utf-8"))["$defs"]["comparison"]["pattern"]

    root = Path(__file__).parents[1]
    assert pattern(root / "src" / "obs") == pattern(root / "adapters" / "html" / "src" / "obs_html")


def test_match_case_flag_belongs_to_an_equals_condition():
    from obs.input import InputError as Error, validate_count_query

    validate_count_query({"where": [{"field": "status", "equals": "Open", "matchCase": True}]}, "note.md")
    with pytest.raises(Error) as error:
        validate_count_query({"where": [{"field": "status", "exists": True, "matchCase": True}]}, "note.md")
    assert str(error.value) == (
        "note.md: query.where[0].equals: is missing; matchCase needs it. "
        "Add equals or remove matchCase; see capabilities/queries."
    )


def test_case_folding_table_is_unicode_full_case_folding():
    """The core's table (src/obs/case-folding.json) folds as Python's str.casefold, Unicode's
    full case folding; at the table's own Unicode version it holds every folding code point."""
    import unicodedata
    from importlib.resources import files

    table = json.loads(files("obs").joinpath("case-folding.json").read_text(encoding="utf-8"))
    folds = {int(code, 16): folded for code, folded in table["folds"].items()}
    assert [code for code, folded in folds.items() if chr(code).casefold() != folded] == []
    if unicodedata.unidata_version == table["unicode"]:
        assert len(folds) == sum(chr(code).casefold() != chr(code)
                                 for code in range(0x110000) if not 0xD800 <= code <= 0xDFFF)
