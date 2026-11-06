"""Runtime records and Base row projections, observed in the rendered artifact.

Owners: flattened frontmatter is the JS ``flattenFrontmatter`` (metadata-flatten-once);
projected rows follow the Bases filter grammar in generic-tables.md; mark ids belong to the
marked paragraph (input-model, Mark tags).
"""
import json
from pathlib import Path

import pytest

from obs_html_interim.content import parse_manifest
from obs_html_interim.renderer import render_artifact
from obs_html_interim.artifact_data import decode_artifact_data
from test_browser import run_artifact_dom_contract


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
    html = render_artifact(manifest, parse_manifest(manifest))
    artifact = vault / "artifact.html"
    artifact.write_text(html, encoding="utf-8")
    notes = decode_artifact_data(html)["notes"]
    inspected = json.loads(run_artifact_dom_contract(artifact, "--inspect-json", arguments=(json.dumps(["registers"]),)))
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


REGISTER_BASE = """\
views:
  - type: table
    name: Risks
    filters: 'type == "risk"'
    order: [label]
    obsHtml: {records: tag}
  - type: table
    name: Terms
    filters: 'status == "approved"'
    order: [term]
    obsHtml: {records: glossary}
"""


@pytest.fixture(scope="module")
def register_rows(tmp_path_factory):
    """One vault built by the interim adapter (DOM rows) and by the core (registers rows)."""
    from obs.capabilities import build_capability_reference
    from obs.document import build_document

    vault = tmp_path_factory.mktemp("register-projections")
    (vault / "manifest.md").write_text("- [[registers]]\n", encoding="utf-8")
    (vault / "x.base").write_text(REGISTER_BASE, encoding="utf-8")
    (vault / "registers.md").write_text(
        "# Registers\n\nCheck the register. #mark/risk/register_check\n\n"
        "![[x.base#Risks]]\n\n![[x.base#Terms]]\n",
        encoding="utf-8",
    )
    (vault / "marked.md").write_text(
        "# Marked\n\nWatch the datum. #mark/risk/datum_watch\n\nAsk. #mark/open_point/ask_once\n",
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
    manifest = vault / "manifest.md"
    html = render_artifact(manifest, parse_manifest(manifest))
    artifact = vault / "artifact.html"
    artifact.write_text(html, encoding="utf-8")
    paths = {note["slug"]: note["sourcePath"] for note in decode_artifact_data(html)["notes"]}
    inspected = json.loads(run_artifact_dom_contract(
        artifact, "--inspect-json", arguments=(json.dumps(["registers"]),),
    ))
    tags, terms = inspected["chapters"]["registers"]["tables"]
    interim = {
        "tags": sorted((paths[key.split(":")[0]], *key.split(":")[1:]) for key in tags),
        "terms": sorted(paths[key.removeprefix("glossary:")] for key in terms),
    }
    reference = build_capability_reference(
        Path(__file__).parents[1] / "spec" / "capabilities",
        Path(__file__).parents[1] / "spec" / "capabilities" / "coverage.json",
    )
    # The interim adapter reads records in its own namespace; the core reads them in obs.
    (vault / "x.base").write_text(REGISTER_BASE.replace("obsHtml:", "obs:"), encoding="utf-8")
    document = build_document(manifest, reference)
    records = {record["id"]: record for record in document["records"]}
    [chapter] = [item for item in document["chapters"] if item["id"] == "registers"]
    risks, glossary = [node["attrs"] for node in chapter["content"] if node["type"] == "registers"]
    def fields(identifier: str) -> dict[str, object]:
        return records[identifier]["fields"]
    core = {
        "tags": sorted((fields(row)["sourcePath"], fields(row)["type"], fields(row)["label"])
                       for row in risks["rows"][risks["view"]]),
        "terms": sorted(fields(row)["sourcePath"] for row in glossary["rows"][glossary["view"]]),
    }
    return interim, core


def test_a_register_over_tag_records_yields_the_rows_the_interim_adapter_shows(register_rows):
    interim, core = register_rows
    assert interim["tags"] == [("marked.md", "risk", "datum_watch"), ("registers.md", "risk", "register_check")]
    assert core["tags"] == interim["tags"]


def test_a_register_over_the_glossary_yields_the_rows_the_interim_adapter_shows(register_rows):
    interim, core = register_rows
    assert interim["terms"] == ["glossary.md"]
    assert core["terms"] == interim["terms"]
