"""A vault's style, declared in its manifest by the name of an installed style component.

Owner: spec/design_input/architecture.md ("Declared style"). Errors are matched by their field path
and owner reference (AGENTS.md), never by wording.
"""
import base64
from pathlib import Path

import pytest

from obs.document import DocumentError, build_document, validate_document
from installed_components import install_adapter, install_style
from test_vault import capability_reference


OWNER = "architecture.md (Declared style)"
HOUSE = {"name": "house", "kind": "style", "version": "1.2.3", "commit": "1" * 40}


def style_vault(tmp_path: Path, style: str | None = "house", chapter: str = "") -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    front = f"---\nobs:\n  style: {style}\n---\n" if style is not None else ""
    (vault / "manifest.md").write_text(f"{front}- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text(f"{chapter}# Chapter\n", encoding="utf-8")
    return vault / "manifest.md"


def test_the_document_names_the_installed_style_its_folder_and_records_its_version(tmp_path) -> None:
    folder = install_style("house")
    reference = capability_reference()
    document = build_document(style_vault(tmp_path), reference)

    assert document["style"] == {"name": "house", "folder": str(folder.resolve())}
    assert document["components"] == [HOUSE]
    validate_document(document, reference)


def test_the_style_follows_the_adapter_among_the_components(tmp_path) -> None:
    install_style("house")
    adapter = {"name": "fixture", "kind": "adapter", "version": "1.0.0", "commit": "0" * 40}

    document = build_document(style_vault(tmp_path), capability_reference(), components=[adapter])

    assert document["components"] == [adapter, HOUSE]


def test_a_manifest_without_a_declaration_gives_a_document_without_a_style(tmp_path) -> None:
    document = build_document(style_vault(tmp_path, style=None), capability_reference())

    assert "style" not in document and document["components"] == []


def test_only_the_manifest_declares_a_style(tmp_path) -> None:
    install_style("house")
    manifest = style_vault(tmp_path, style=None, chapter="---\nobs:\n  style: house\n---\n")

    with pytest.raises(DocumentError) as refused:
        build_document(manifest, capability_reference())

    assert "chapter.md: obs.style:" in str(refused.value) and OWNER in str(refused.value)


def test_a_style_that_is_not_installed_fails_naming_the_command_that_installs_it(tmp_path) -> None:
    with pytest.raises(DocumentError) as refused:
        build_document(style_vault(tmp_path), capability_reference())

    message = str(refused.value)
    assert "manifest.md: obs.style:" in message and OWNER in message
    assert "obs-components install house" in message


def test_a_component_of_another_kind_is_no_style(tmp_path) -> None:
    install_adapter({"name": "house", "command": ["true"], "contractVersion": 1, "capabilities": []})

    with pytest.raises(DocumentError) as refused:
        build_document(style_vault(tmp_path), capability_reference())

    assert "manifest.md: obs.style:" in str(refused.value) and OWNER in str(refused.value)


def test_an_installed_style_without_a_stylesheet_fails_naming_the_field(tmp_path) -> None:
    (install_style("house") / "style.css").unlink()

    with pytest.raises(DocumentError) as refused:
        build_document(style_vault(tmp_path), capability_reference())

    assert "manifest.md: obs.style:" in str(refused.value) and OWNER in str(refused.value)


@pytest.mark.parametrize("style", [
    "{url: https://example.org/house/report-style.git, ref: 0123456789abcdef0123456789abcdef01234567}",
    "{url: https://example.org/house/report-style.git}",
])
def test_the_address_form_is_refused_naming_the_name_form(tmp_path, style) -> None:
    with pytest.raises(DocumentError) as refused:
        build_document(style_vault(tmp_path, style=style), capability_reference())

    message = str(refused.value)
    assert "manifest.md: obs.style:" in message and OWNER in message
    assert "obs.style: <name>" in message


@pytest.mark.parametrize("style", ["House", "'-house'", "12", "''"])
def test_a_style_that_is_no_component_name_is_refused(tmp_path, style) -> None:
    with pytest.raises(DocumentError) as refused:
        build_document(style_vault(tmp_path, style=style), capability_reference())

    assert "manifest.md: obs.style:" in str(refused.value) and OWNER in str(refused.value)


def rebuilt(document: dict[str, object], folder: Path) -> dict[str, object]:
    """The Document a rebuild from ``document``'s source archive builds: its files extracted into
    ``folder``, then built again as the recorded arguments do (--embed-source)."""
    for entry in document["sourceArchive"]["files"]:
        target = folder / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(entry["data"]))
    assert document["sourceArchive"]["build"]["arguments"] == ["--embed-source"]
    return build_document(folder / document["manifest"]["path"], capability_reference(), embed_source=True)


def test_the_archive_records_the_style_among_its_components_and_a_rebuild_finds_the_same_one(tmp_path) -> None:
    install_style("house")
    document = build_document(style_vault(tmp_path), capability_reference(), embed_source=True)

    assert document["sourceArchive"]["build"]["components"] == [HOUSE]
    assert "style" not in document["sourceArchive"]["build"]
    again = rebuilt(document, tmp_path / "extracted")
    assert again["style"] == document["style"] and again["sourceArchive"]["build"]["components"] == [HOUSE]
