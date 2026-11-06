"""A vault's style, declared in its manifest as a dependency pinned to a commit.

Owner: spec/design_input/architecture.md ("Declared style"). Errors are matched by their field path
and owner reference (AGENTS.md), never by wording.
"""
import base64
from pathlib import Path

import pytest

from obs.document import DocumentError, build_document, validate_document
from test_vault import capability_reference


OWNER = "architecture.md (Declared style)"
URL = "https://example.org/house/report-style.git"
REF = "0123456789abcdef0123456789abcdef01234567"


def style_vault(tmp_path: Path, style: str | None = f"{{url: {URL}, ref: {REF}, path: styles/house}}",
                chapter: str = "") -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    front = f"---\nobs:\n  style: {style}\n---\n" if style is not None else ""
    (vault / "manifest.md").write_text(f"{front}- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text(f"{chapter}# Chapter\n", encoding="utf-8")
    return vault / "manifest.md"


def test_the_document_carries_the_declared_style_s_identity_and_no_file_of_it(tmp_path) -> None:
    reference = capability_reference()
    document = build_document(style_vault(tmp_path), reference)

    assert document["style"] == {"url": URL, "ref": REF, "path": "styles/house"}
    validate_document(document, reference)


def test_a_manifest_without_a_declaration_gives_a_document_without_a_style(tmp_path) -> None:
    assert "style" not in build_document(style_vault(tmp_path, style=None), capability_reference())


def test_only_the_manifest_declares_a_style(tmp_path) -> None:
    manifest = style_vault(tmp_path, style=None, chapter=f"---\nobs:\n  style: {{url: {URL}, ref: {REF}}}\n---\n")

    with pytest.raises(DocumentError) as refused:
        build_document(manifest, capability_reference())

    assert "chapter.md: obs.style:" in str(refused.value) and OWNER in str(refused.value)


@pytest.mark.parametrize(("style", "field"), [
    (f"{{url: {URL}, ref: main}}", "obs.style.ref"),
    (f"{{url: {URL}}}", "obs.style.ref"),
    (f"{{url: 'git@example.org:house/report-style.git', ref: {REF}}}", "obs.style.url"),
])
def test_a_style_that_names_no_pin_or_public_url_names_the_style_and_the_remedy(tmp_path, style, field) -> None:
    with pytest.raises(DocumentError) as refused:
        build_document(style_vault(tmp_path, style=style), capability_reference())

    message = str(refused.value)
    assert f"manifest.md: {field}:" in message and OWNER in message
    assert "example.org" in message and message.count("obs.style") >= 2, (
        "the message names the declared style and, in its remedy, how to declare it")


def rebuilt(document: dict[str, object], folder: Path) -> dict[str, object]:
    """The Document a rebuild from ``document``'s source archive builds: its files extracted into
    ``folder``, then built again as the recorded arguments do (--embed-source)."""
    for entry in document["sourceArchive"]["files"]:
        target = folder / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(entry["data"]))
    assert document["sourceArchive"]["build"]["arguments"] == ["--embed-source"]
    return build_document(folder / document["manifest"]["path"], capability_reference(), embed_source=True)


def test_the_archive_records_the_declared_style_and_a_rebuild_resolves_the_same_one(tmp_path) -> None:
    document = build_document(style_vault(tmp_path), capability_reference(), embed_source=True)

    declared = {"url": URL, "ref": REF, "path": "styles/house"}
    assert document["sourceArchive"]["build"]["style"] == declared
    again = rebuilt(document, tmp_path / "extracted")
    assert again["style"] == declared and again["sourceArchive"]["build"]["style"] == declared


def test_without_a_declaration_the_archive_records_no_style(tmp_path) -> None:
    document = build_document(style_vault(tmp_path, style=None), capability_reference(), embed_source=True)

    assert "style" not in document["sourceArchive"]["build"]
