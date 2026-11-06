"""Cover metadata names no application or vendor (input-model#Cover metadata and history).

The manifest's document number is `document number`; the removed `sap number` is an input error
naming the manifest, the old field and the new one, with no compatibility layer. Errors are
matched by their field path and owner reference (AGENTS.md), never by wording.
"""
from pathlib import Path

import pytest

from obs.capabilities import build_capability_reference
from obs.document import DocumentError, build_document

ROOT = Path(__file__).parents[1]
OWNER = "; see input-model#Cover metadata and history."


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

