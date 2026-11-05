"""Runtime records and Base row projections, observed in the rendered report.

Owners: flattened frontmatter is the JS ``flattenFrontmatter`` (metadata-flatten-once);
projected rows follow the Bases filter grammar in generic-tables.md; mark ids belong to the
marked paragraph (input-model, Mark tags).
"""
import json
from pathlib import Path

import pytest

from obs_html.content import parse_manifest
from obs_html.renderer import render_report
from obs_html.report_data import decode_report_data
from test_browser import run_report_dom_contract


def _base(filters: str, order: str, records: str = "") -> str:
    profile = f"obsHtml: {{records: {records}}}\n" if records else ""
    return (f"```base\nfilters:\n  and: [{filters}]\nviews:\n  - type: table\n    order: [{order}]\n"
            f"{profile}```\n\n")


@pytest.fixture(scope="module")
def projected(tmp_path_factory):
    vault = tmp_path_factory.mktemp("projections")
    (vault / "extra").mkdir()
    (vault / "manifest.md").write_text("- [[registers]]\n", encoding="utf-8")
    (vault / "registers.md").write_text(
        "# Registers\n\nCheck the register. #mark/risk/register_check\n\n"
        + _base("'status == \"approved\"'", "term", "glossary")
        + _base("'sourcePath == \"extra/located.md\"'", "title", "note")
        + _base("'slug == \"custom\"'", "title", "note")
        + _base("'slug == \"slugged\"'", "title", "note")
        + _base("'type == \"open_point\"'", "label", "tag")
        + _base("'kind == \"evidence\"'", "file.name")
        + _base("'type == \"risk\"'", "label", "tag"),
        encoding="utf-8",
    )
    (vault / "glossary.md").write_text(
        "---\nkind: glossary\nterm: Datum\ndefinition: A reference.\nstatus: approved\n---\n# Datum\n",
        encoding="utf-8",
    )
    (vault / "draft-term.md").write_text(
        "---\nkind: glossary\nterm: Draft\ndefinition: Not yet.\nstatus: draft\n---\n# Draft\n",
        encoding="utf-8",
    )
    (vault / "extra" / "located.md").write_text("---\nkind: other\n---\n# Located\n", encoding="utf-8")
    (vault / "extra" / "elsewhere.md").write_text("---\nkind: other\n---\n# Elsewhere\n", encoding="utf-8")
    (vault / "slugged.md").write_text(
        "---\nkind: evidence\nslug: custom\ntags: [a, b]\nnested: {owner: Ann}\nempty: []\n"
        "blank: {}\nitems: [{name: x}, {name: y}]\n---\n# Slugged\n",
        encoding="utf-8",
    )
    (vault / "marked.md").write_text(
        "---\ntype: risk\n---\n# Marked\n\nWatch the datum. #mark/open_point/datum_watch\n",
        encoding="utf-8",
    )
    manifest = vault / "manifest.md"
    html = render_report(manifest, parse_manifest(manifest))
    report = vault / "report.html"
    report.write_text(html, encoding="utf-8")
    notes = decode_report_data(html)["notes"]
    inspected = json.loads(run_report_dom_contract(report, "--inspect-json", arguments=(json.dumps(["registers"]),)))
    return {"notes": {note["sourcePath"]: note["slug"] for note in notes}, **inspected}


def test_record_projections_select_the_same_notes_in_generator_and_browser(projected):
    slugs = projected["notes"]
    assert sorted(slugs) == [
        "extra/located.md", "glossary.md", "manifest.md", "marked.md", "registers.md", "slugged.md",
    ]
    assert projected["chapters"]["registers"]["tables"] == [
        [f"glossary:{slugs['glossary.md']}"],
        [f"note:{slugs['extra/located.md']}"],
        [],
        [f"note:{slugs['slugged.md']}"],
        [f"{slugs['marked.md']}:open_point:datum_watch"],
        [f"note:{slugs['slugged.md']}"],
        [f"{slugs['registers.md']}:risk:register_check"],
    ]


def test_filter_attributes_come_from_the_single_flattened_frontmatter(projected):
    record = next(item for item in projected["records"] if item["slug"] == projected["notes"]["slugged.md"])
    assert [entry[:2] for entry in record["metadataEntries"]] == [
        ["kind", "evidence"], ["slug", "custom"], ["tags", "a, b"], ["nested.owner", "Ann"],
        ["empty", "[]"], ["blank", "{}"], ["items.0.name", "x"], ["items.1.name", "y"],
    ]
    assert record["filterAttributes"] == {
        "title": ["Slugged"], "slug": ["custom"], "depth": ["0"], "mark": [],
        "kind": ["evidence"], "tags": ["a", "b"], "nested.owner": ["Ann"], "empty": [],
        "items.0.name": ["x"], "items.1.name": ["y"],
    }


def test_marked_paragraph_and_tag_table_row_have_unique_ids(projected):
    assert projected["chapters"]["registers"]["duplicateIds"] == []
