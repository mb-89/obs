"""The core validates the manifest's cover metadata (input-model#Cover metadata and history).

Cover metadata names no application or vendor: the document number is `document number`, and the
removed `sap number` is an input error naming the manifest, the old field and the new one, with no
compatibility layer. The core checks every cover field against `src/obs/cover-metadata.schema.json`
through the one error formatter; the manifest's other frontmatter stays open. Errors are matched by
their field path and owner reference (AGENTS.md), never by wording.
"""
from importlib.resources import files
import json
import re
from pathlib import Path

import pytest

from obs.capabilities import build_capability_reference
from obs.document import DocumentError, build_document

ROOT = Path(__file__).parents[1]
OWNER = "; see input-model#Cover metadata and history."
VENDOR_WORDS = re.compile(r"\bsap\b", re.IGNORECASE)
"""Vendor words no field name may contain; a framework never names an application or vendor."""


def _build(tmp_path: Path, frontmatter: str) -> dict[str, object]:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text(f"---\ntitle: Cover\n{frontmatter}---\n- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text("# Chapter\n\nText.\n", encoding="utf-8")
    capabilities = ROOT / "spec" / "capabilities"
    return build_document(vault / "manifest.md",
                          build_capability_reference(capabilities, capabilities / "coverage.json"))


def test_the_document_number_reaches_the_document_metadata(tmp_path) -> None:
    document = _build(tmp_path, "document number: X-1\n")

    assert document["manifest"]["metadata"]["document number"] == "X-1"


def test_the_removed_sap_number_names_the_manifest_the_old_field_and_the_new_one(tmp_path) -> None:
    with pytest.raises(DocumentError) as raised:
        _build(tmp_path, "sap number: X-1\n")

    message = str(raised.value)
    assert message.startswith(f"{tmp_path / 'vault' / 'manifest.md'}: sap number: "), message
    assert "document number" in message
    assert message.endswith(OWNER), message


def _refused(tmp_path: Path, frontmatter: str) -> str:
    """The message of the input error the manifest frontmatter raises."""
    with pytest.raises(DocumentError) as raised:
        _build(tmp_path, frontmatter)
    return str(raised.value)


def _names(message: str, tmp_path: Path, field: str) -> None:
    """The message names the manifest, the field and a remedy, and points at the owner."""
    assert message.startswith(f"{tmp_path / 'vault' / 'manifest.md'}: {field}: "), message
    assert re.search(r"\. [A-Z][^.]*" + re.escape(OWNER) + "$", message), message


def test_a_non_string_author_names_the_manifest_the_field_and_the_remedy(tmp_path) -> None:
    _names(_refused(tmp_path, "authors: 5\n"), tmp_path, "authors")


def test_an_unknown_cover_metadata_field_names_the_manifest_the_field_and_the_remedy(tmp_path) -> None:
    _names(_refused(tmp_path, "product: {name: Pump, colour: red}\n"), tmp_path, "product.colour")


@pytest.mark.parametrize(("frontmatter", "field"), [
    ("document type: 3\n", "document type"),
    ("organization: [Acme]\n", "organization"),
    ("legal entity: {name: Acme}\n", "legal entity"),
    ("reviewers: [Ann, 7]\n", "reviewers[1]"),
    ("approvers: [Ann, ' ']\n", "approvers[1]"),
    ("product: Pump\n", "product"),
    ("product: {version: '2'}\n", "product.name"),
    ("product: {name: Pump, version: 2}\n", "product.version"),
    ("history: first\n", "history"),
    ("history: [{version: '1', author: Ann}]\n", "history[0].change"),
    ("history: [{version: '1', author: Ann, change: New, reviewer: Bob}]\n", "history[0].reviewer"),
    ("history: [{version: '1', author: Ann, change: New, date: 5 May}]\n", "history[0].date"),
    ("history: [{version: '1', author: Ann, change: New, date: '2026-02-30'}]\n", "history[0].date"),
    ("history: [{version: '1', author: Ann, change: A}, {version: '1', author: Ann, change: B}]\n",
     "history[1].version"),
    ("history: [{version: '1*', author: Ann, change: A}, {version: '2', author: Ann, change: B}]\n",
     "history[0].version"),
])
def test_each_cover_metadata_rule_names_the_manifest_the_field_and_the_remedy(
    tmp_path, frontmatter: str, field: str,
) -> None:
    _names(_refused(tmp_path, frontmatter), tmp_path, field)


def test_unassigned_cover_fields_and_other_frontmatter_are_accepted(tmp_path) -> None:
    document = _build(tmp_path, (
        "document type: ''\norganization:\nauthors: []\nreviewers: ' '\nproduct: {name: '', version: ''}\n"
        "history: [{version: '00', author: Ann, change: New, date: 2026-05-04},"
        " {version: '01*', author: Ann, change: Draft, date: ''}]\n"
        "status: draft\nobsHtml: {layout: paged}\n"
    ))

    assert document["manifest"]["metadata"]["status"] == "draft"


def _keys(value: object) -> list[str]:
    if isinstance(value, dict):
        return [*map(str, value), *(key for item in value.values() for key in _keys(item))]
    if isinstance(value, list):
        return [key for item in value for key in _keys(item)]
    return []


def test_no_core_schema_names_a_vendor_in_a_field_name() -> None:
    found = [f"src/obs/{schema.name}: {key!r}" for schema in files("obs").iterdir()
             if schema.name.endswith(".schema.json")
             for key in _keys(json.loads(schema.read_text(encoding="utf-8"))) if VENDOR_WORDS.search(key)]
    assert not found, f"a core schema names a vendor in a field name; name the field generically: {found}"
