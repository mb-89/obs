"""The Bases filter and query condition evaluators against the shared conformance fixture.

The browser evaluators run the same fixture in ``bases-filter-conformance.test.js``.
"""
import json
from pathlib import Path

import pytest

from obs_html_interim.content import ContentError, base_note_value, compile_base_filter, parse_manifest
from obs_html_interim.renderer import render_artifact
from obs_html_interim.artifact_data import decode_artifact_data

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "bases-filter-conformance.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda case: json.dumps(case["filter"]))
def test_generator_evaluator_matches_fixture(case):
    predicate = compile_base_filter(case["filter"])
    actual = [
        record["id"] for record in FIXTURE["records"]
        if predicate(lambda field, record=record: base_note_value(record["frontmatter"], record["path"], field))
    ]
    assert actual == case["expected"]


@pytest.mark.parametrize("filters", FIXTURE["unsupported"], ids=json.dumps)
def test_generator_rejects_unsupported_filters(filters):
    with pytest.raises(ContentError, match="Unsupported Bases"):
        compile_base_filter(filters)


def _vault(tmp_path: Path, chapter: str, manifest_frontmatter: str = "") -> Path:
    manifest = tmp_path / "manifest.md"
    manifest.write_text(f"{manifest_frontmatter}- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "chapter.md").write_text(chapter, encoding="utf-8")
    return manifest


FENCE = "```base\n{filters}views:\n  - type: table\n    order: [kind]\n{view_filters}```\n\n"


@pytest.mark.parametrize("filters, view_filters, location", [
    ("filters: 'status.contains(\"x\")'\n", "", "filters"),
    ("", "    filters:\n      or: ['kind == \"a\"', 'kind > 1']\n", "views.0.filters"),
])
def test_unsupported_fence_filter_names_file_fence_and_expression(tmp_path, filters, view_filters, location):
    valid = FENCE.format(filters="filters: 'kind == \"a\"'\n", view_filters="")
    invalid = FENCE.format(filters=filters, view_filters=view_filters)
    manifest = _vault(tmp_path, "# Chapter\n\n" + valid + invalid)
    with pytest.raises(ContentError) as error:
        render_artifact(manifest, parse_manifest(manifest))
    message = str(error.value)
    assert "Unsupported Bases" in message
    assert "chapter.md" in message and "base fence 2" in message and location in message
    assert ('status.contains("x")' if location == "filters" else "kind > 1") in message


@pytest.mark.parametrize("filters, view_filters, expression", [
    ("filters: 'status.contains(\"x\")'\n", "", 'status.contains("x")'),
    ("", "    filters:\n      or: ['kind == \"a\"', 'kind > 1']\n", "kind > 1"),
])
def test_the_core_names_the_note_fence_and_expression_of_an_unsupported_fence_filter(
        tmp_path, filters, view_filters, expression):
    from obs.document import DocumentError, build_document
    from test_vault import capability_reference

    valid = FENCE.format(filters="filters: 'kind == \"a\"'\n", view_filters="")
    invalid = FENCE.format(filters=filters, view_filters=view_filters)
    manifest = _vault(tmp_path, "# Chapter\n\n" + valid + invalid)
    with pytest.raises(DocumentError) as error:
        build_document(manifest, capability_reference())
    message = str(error.value)
    assert message.startswith(f"Unsupported Bases filter: {expression} (base fence 2 in chapter.md)"), message
    assert message.endswith("use the Bases filter grammar of generic-tables."), message


def test_inclusion_uses_the_grammar_for_indexed_and_literal_dotted_paths(tmp_path):
    (tmp_path / "indexed.md").write_text("---\nitems: [{name: first}, {name: second}]\n---\n# Indexed\n",
                                         encoding="utf-8")
    (tmp_path / "literal.md").write_text("---\na.b: literal\na: {b: nested}\n---\n# Literal\n", encoding="utf-8")
    (tmp_path / "other.md").write_text("---\nitems: [{name: second}]\na: {b: nested}\n---\n# Other\n",
                                       encoding="utf-8")
    fence = ("```base\nfilters:\n  or: ['items.0.name == \"first\"', 'note[\"a.b\"] == \"literal\"']\n"
             "views:\n  - type: table\n    order: [file.name]\n```\n")
    manifest = _vault(tmp_path, "# Chapter\n\n" + fence)
    notes = decode_artifact_data(render_artifact(manifest, parse_manifest(manifest)))["notes"]
    assert sorted(note["sourcePath"] for note in notes) == [
        "chapter.md", "indexed.md", "literal.md", "manifest.md",
    ]


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


@pytest.mark.parametrize("package", ["core", "adapter"])
def test_match_case_flag_belongs_to_an_equals_condition(package):
    if package == "core":
        from obs.input import InputError as Error, validate_count_query
    else:
        from obs_html_interim.cards import validate_count_query
        from obs_html_interim.content import ContentError as Error

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
