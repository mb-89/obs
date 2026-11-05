"""Author presentation control from the vault: styling hooks, print setup and wide tables."""
import json
import os
import re
from importlib.resources import files
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from obs_html.content import ContentError, parse_manifest
from obs_html.renderer import render_artifact
from obs_html.artifact_data import decode_artifact_data

SNIPPET = ".brand-note h1 { color: rgb(1, 2, 3); }\n"


def _styled_vault(tmp_path: Path, *, snippets: str = "[brand]", classes: str = "[brand-note, compact]") -> Path:
    (tmp_path / ".obsidian" / "snippets").mkdir(parents=True)
    (tmp_path / ".obsidian" / "snippets" / "brand.css").write_text(SNIPPET, encoding="utf-8")
    (tmp_path / ".obsidian" / "snippets" / "unlisted.css").write_text(
        "h1 { color: rgb(9, 9, 9); }\n", encoding="utf-8",
    )
    (tmp_path / "styled.md").write_text(
        f"---\ncssclasses: {classes}\n---\n# Styled\n\nStyled body.\n", encoding="utf-8",
    )
    (tmp_path / "plain.md").write_text("# Plain\n\nPlain body.\n", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text(
        f"---\nobsHtml: {{cssSnippets: {snippets}}}\n---\n- [[styled]]\n- [[plain]]\n", encoding="utf-8",
    )
    return manifest


def test_listed_snippets_and_cssclasses_reach_the_rendered_html(tmp_path):
    manifest = _styled_vault(tmp_path)
    html = render_artifact(manifest, parse_manifest(manifest))
    styles = re.findall(r'<style data-css-snippet="([^"]+)">(.*?)</style>', html, re.S)
    assert styles == [("brand", SNIPPET)]
    assert html.index('id="artifact-styles"') < html.index('data-css-snippet="brand"') < html.index("</head>")
    assert "rgb(9, 9, 9)" not in html
    notes = {note["slug"]: note for note in decode_artifact_data(html)["notes"]}
    assert notes["styled"]["cssClasses"] == ["brand-note", "compact"]
    assert notes["plain"]["cssClasses"] == []


def test_a_single_cssclasses_string_is_one_class(tmp_path):
    manifest = _styled_vault(tmp_path, classes="brand-note")
    notes = {note["slug"]: note for note in decode_artifact_data(
        render_artifact(manifest, parse_manifest(manifest)))["notes"]}
    assert notes["styled"]["cssClasses"] == ["brand-note"]


@pytest.mark.parametrize("snippets,classes,message", [
    ("[missing]", "[brand-note]", r"\.obsidian/snippets/missing\.css"),
    ("[brand]", "['two words']", "cssclasses"),
    ("[brand]", "[{a: 1}]", "cssclasses"),
    ("['../brand']", "[brand-note]", "obsHtml"),
])
def test_unusable_styling_hooks_are_input_errors(tmp_path, snippets, classes, message):
    manifest = _styled_vault(tmp_path, snippets=snippets, classes=classes)
    with pytest.raises(ContentError, match=message):
        render_artifact(manifest, parse_manifest(manifest))


def test_a_snippet_cannot_close_its_style_element(tmp_path):
    manifest = _styled_vault(tmp_path)
    (tmp_path / ".obsidian" / "snippets" / "brand.css").write_text(
        "/* </style><script>alert(1)</script> */", encoding="utf-8",
    )
    with pytest.raises(ContentError, match="brand"):
        render_artifact(manifest, parse_manifest(manifest))


def test_source_archive_carries_listed_snippets_but_no_other_dotfiles(tmp_path):
    from obs_html.cli import PROJECT_ROOT
    from obs_html.config import load_config
    from obs_html.reproduction import source_archive

    vault = tmp_path / "vault"
    vault.mkdir()
    manifest = _styled_vault(vault)
    config = load_config(files("obs_html").joinpath("cfg.json"))
    with ZipFile(BytesIO(source_archive(vault, manifest, PROJECT_ROOT, config, False))) as archive:
        names = set(archive.namelist())
        inventory = json.loads(archive.read("source-inventory.json"))["vault"]
    assert "vault/.obsidian/snippets/brand.css" in names
    assert "vault/.obsidian/snippets/unlisted.css" not in names
    assert ".obsidian/snippets/brand.css" in inventory


@pytest.mark.skipif(not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"),
                    reason="Set OBS_HTML_TEST_NATIVE_BROWSER for native styling checks.")
def test_native_snippet_styles_classed_notes_in_reader_pages_and_print(tmp_path):
    from playwright.sync_api import sync_playwright

    manifest = _styled_vault(tmp_path)
    artifact = tmp_path.parent / f"{tmp_path.name}-artifact.html"
    artifact.write_text(render_artifact(manifest, parse_manifest(manifest)), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(artifact.as_uri() + "#styled")
            heading = page.locator("[data-active-chapter] h1").filter(has_text="Styled").first
            heading.wait_for()
            assert heading.evaluate("node => getComputedStyle(node).color") == "rgb(1, 2, 3)"
            assert page.locator(".paged-reader .paper-sheet.brand-note.compact").count() >= 1
            page.evaluate("obsPages.setPaged(false)")
            assert heading.evaluate("node => getComputedStyle(node).color") == "rgb(1, 2, 3)"
            page.goto(artifact.as_uri() + "#plain")
            plain = page.locator("[data-active-chapter] h1").filter(has_text="Plain").first
            plain.wait_for()
            assert plain.evaluate("node => getComputedStyle(node).color") != "rgb(1, 2, 3)"
            assert page.locator("[data-active-chapter].brand-note").count() == 0
            page.evaluate("window.print = () => {}; obsPages.exportPDF()")
            page.emulate_media(media="print")
            printed = page.locator('.print-book .paper-sheet[data-page-chapter="styled"]')
            assert printed.count() >= 1
            assert printed.evaluate_all("nodes => nodes.every(node => node.matches('.brand-note.compact'))")
            assert printed.locator("h1").first.evaluate("node => getComputedStyle(node).color") == "rgb(1, 2, 3)"
            assert page.locator('.print-book .paper-sheet[data-page-chapter="plain"].brand-note').count() == 0
            assert errors == []
        finally:
            browser.close()


def _print_vault(tmp_path: Path, profile: str = "") -> Path:
    (tmp_path / "chapter.md").write_text(
        "# Chapter\n\nLEFT-EDGE " + "Long paragraph text. " * 400 + "\n", encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    front = f"---\nobsHtml: {{print: {profile}}}\n---\n" if profile else ""
    manifest.write_text(front + "- [[chapter]]\n", encoding="utf-8")
    return manifest


@pytest.mark.parametrize("profile,paper", [
    ("", {"widthMillimeters": 210, "heightMillimeters": 297, "marginMillimeters": 20}),
    ("{paper: Letter, margin: 12.5mm}",
     {"widthMillimeters": 215.9, "heightMillimeters": 279.4, "marginMillimeters": 12.5}),
    ("{margin: 15mm}", {"widthMillimeters": 210, "heightMillimeters": 297, "marginMillimeters": 15}),
    ("{paper: A3}", {"widthMillimeters": 297, "heightMillimeters": 420, "marginMillimeters": 20}),
])
def test_manifest_print_setup_resolves_paper_geometry(tmp_path, profile, paper):
    manifest = _print_vault(tmp_path, profile)
    assert decode_artifact_data(render_artifact(manifest, parse_manifest(manifest)))["paper"] == paper


@pytest.mark.parametrize("profile,message", [
    ("{paper: B9}", "obsHtml.print.paper"),
    ("{margin: 50mm}", "obsHtml.print.margin"),
    ("{margin: 2mm}", "obsHtml.print.margin"),
    ("{margin: 20}", "obsHtml"),
    ("{orientation: landscape}", "obsHtml"),
])
def test_unusable_manifest_print_setup_is_an_input_error(tmp_path, profile, message):
    manifest = _print_vault(tmp_path, profile)
    with pytest.raises(ContentError, match=message):
        render_artifact(manifest, parse_manifest(manifest))


@pytest.mark.skipif(not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"),
                    reason="Set OBS_HTML_TEST_NATIVE_BROWSER for native PDF checks.")
@pytest.mark.parametrize("profile,size,margin", [
    ("", (210, 297), 20),
    ("{paper: Letter, margin: 12.5mm}", (215.9, 279.4), 12.5),
])
def test_native_manifest_print_setup_shapes_the_printed_pdf(tmp_path, profile, size, margin):
    from playwright.sync_api import sync_playwright
    from pypdf import PdfReader

    manifest = _print_vault(tmp_path, profile)
    artifact = tmp_path.parent / f"{tmp_path.name}-artifact.html"
    artifact.write_text(render_artifact(manifest, parse_manifest(manifest)), encoding="utf-8")
    points = 72 / 25.4
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(artifact.as_uri())
            page.evaluate("window.print = () => {}; obsPages.exportPDF()")
            page.emulate_media(media="print")
            pdf = PdfReader(BytesIO(page.pdf(prefer_css_page_size=True, print_background=True)))
            assert len(pdf.pages) > 2
            for physical in pdf.pages:
                assert float(physical.mediabox.width) == pytest.approx(size[0] * points, abs=1)
                assert float(physical.mediabox.height) == pytest.approx(size[1] * points, abs=1)
            lefts = []

            def left(text, cm, tm, _font, _size):
                if "LEFT-EDGE" in text:
                    lefts.append(tm[4] * cm[0] + tm[5] * cm[2] + cm[4])

            next(p for p in pdf.pages if "LEFT-EDGE" in p.extract_text()).extract_text(visitor_text=left)
            assert lefts and lefts[0] == pytest.approx(margin * points, abs=2)
            assert errors == []
        finally:
            browser.close()
