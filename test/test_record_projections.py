"""Register rows the core projects from records: a register over mark tags and one over the
glossary (capabilities/registers). The interim adapter showed the same rows for this vault until
obs#3 deleted it; its runtime projections are the HTML adapter's (test_moved_dom_contracts.py).
"""
from pathlib import Path

import pytest


REGISTER_BASE = """\
views:
  - type: table
    name: Risks
    filters: 'type == "risk"'
    order: [label]
    obs: {records: tag}
  - type: table
    name: Terms
    filters: 'status == "approved"'
    order: [term]
    obs: {records: glossary}
"""


@pytest.fixture(scope="module")
def register_rows(tmp_path_factory):
    """One vault built by the core: the rows of its two registers."""
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
    reference = build_capability_reference(
        Path(__file__).parents[1] / "spec" / "capabilities",
        Path(__file__).parents[1] / "spec" / "capabilities" / "coverage.json",
    )
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
    return core


def test_a_register_over_tag_records_yields_a_row_per_mark(register_rows):
    assert register_rows["tags"] == [("marked.md", "risk", "datum_watch"), ("registers.md", "risk", "register_check")]


def test_a_register_over_the_glossary_yields_the_approved_terms(register_rows):
    assert register_rows["terms"] == ["glossary.md"]
