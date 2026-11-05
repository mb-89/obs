"""The generator's Bases filter evaluator against the shared conformance fixture.

The browser evaluator runs the same fixture in ``bases-filter-conformance.test.js``.
"""
import json
from pathlib import Path

import pytest

from obs_html.content import ContentError, base_note_value, compile_base_filter, parse_manifest
from obs_html.renderer import render_report
from obs_html.report_data import decode_report_data

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
        render_report(manifest, parse_manifest(manifest))
    message = str(error.value)
    assert "Unsupported Bases" in message
    assert "chapter.md" in message and "base fence 2" in message and location in message
    assert ('status.contains("x")' if location == "filters" else "kind > 1") in message


def test_inclusion_uses_the_grammar_for_indexed_and_literal_dotted_paths(tmp_path):
    (tmp_path / "indexed.md").write_text("---\nitems: [{name: first}, {name: second}]\n---\n# Indexed\n",
                                         encoding="utf-8")
    (tmp_path / "literal.md").write_text("---\na.b: literal\na: {b: nested}\n---\n# Literal\n", encoding="utf-8")
    (tmp_path / "other.md").write_text("---\nitems: [{name: second}]\na: {b: nested}\n---\n# Other\n",
                                       encoding="utf-8")
    fence = ("```base\nfilters:\n  or: ['items.0.name == \"first\"', 'note[\"a.b\"] == \"literal\"']\n"
             "views:\n  - type: table\n    order: [file.name]\n```\n")
    manifest = _vault(tmp_path, "# Chapter\n\n" + fence)
    notes = decode_report_data(render_report(manifest, parse_manifest(manifest)))["notes"]
    assert sorted(note["sourcePath"] for note in notes) == [
        "chapter.md", "indexed.md", "literal.md", "manifest.md",
    ]
