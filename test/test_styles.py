from pathlib import Path

import pytest

from obs_html_interim.content import parse_manifest
from obs_html_interim.renderer import render_artifact


def _manifest(root: Path) -> Path:
    (root / "chapter.md").write_text("# Chapter\n\nBody.\n", encoding="utf-8")
    manifest = root / "manifest.md"
    manifest.write_text("- [[chapter]]\n", encoding="utf-8")
    return manifest


def test_default_style_is_packaged_generic_and_has_no_external_module(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)

    artifact = render_artifact(manifest, parse_manifest(manifest))

    assert 'font-content: Georgia, "Times New Roman", serif' in artifact
    assert "file:///" not in artifact
    assert '<link rel="stylesheet"' not in artifact


def test_explicit_style_module_overrides_the_default(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    style = tmp_path / "style"
    style.mkdir()
    (style / "style.css").write_text(":root { --module-style: selected; }", encoding="utf-8")
    (style / "assets.json").write_text(
        '{"schemaVersion":1,"assets":{"color":{"children":{"accent":{"value":{"light":"#123456","dark":"#abcdef"}}}}}}',
        encoding="utf-8",
    )

    artifact = render_artifact(manifest, parse_manifest(manifest), style_folder=style)

    assert "--module-style: selected" in artifact
    assert 'font-content: Georgia, "Times New Roman", serif' not in artifact
    assert "#123456" in artifact
    assert ".paper-sheet" in artifact


@pytest.mark.parametrize("geometry", ["@page { size: A4; }", ":root { --paper-width: 1mm; }"])
def test_style_module_cannot_declare_page_geometry(tmp_path: Path, geometry: str) -> None:
    manifest = _manifest(tmp_path)
    style = tmp_path / "style"
    style.mkdir()
    (style / "style.css").write_text(geometry, encoding="utf-8")

    with pytest.raises(ValueError, match="page geometry"):
        render_artifact(manifest, parse_manifest(manifest), style_folder=style)
