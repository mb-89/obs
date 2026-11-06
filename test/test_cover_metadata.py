"""Cover metadata names no application or vendor (input-model#Cover metadata and history).

The manifest's document number is `document number`; the removed `sap number` is an input error
naming the manifest, the old field and the new one, with no compatibility layer. Errors are
matched by their field path and owner reference (AGENTS.md), never by wording.
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
