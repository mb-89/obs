import json
import base64
import os
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from obs_html_interim.cli import main
from obs_html_interim.config import load_config
from obs_html_interim.content import parse_manifest
from obs_html_interim.renderer import render_artifact
from obs_html_interim.artifact_data import decode_artifact_data
from obs_html_interim.reproduction import embedded_archive


ROOT = Path(__file__).parents[1]
PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a8xoAAAAASUVORK5CYII="
)


def write_index(path, definitions):
    assets = {}
    for name, value in definitions.items():
        parts = name.split(".")
        nodes = assets
        for segment in parts[:-1]:
            nodes = nodes.setdefault(segment, {}).setdefault("children", {})
        nodes[parts[-1]] = {"type": "icon", "value": value}
    path.write_text(json.dumps({"schemaVersion": 1, "assets": assets}), encoding="utf-8")


def icon_fixture(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.md").write_text("- [[chapter]]\n",
                                      encoding="utf-8")
    (root / "chapter.md").write_text(
        "# Named resources\n\nA decision. #mark/decision/chosen\n\n"
        "```base\nproperties:\n  evidence:\n    obsHtml:\n      icon:\n"
        "        name: project.evidence\n        label: Evidence instructions\n"
        "        help: Select replacement evidence.\n"
        "views:\n  - type: table\n    order: [title, evidence]\n```\n",
        encoding="utf-8",
    )
    write_index(root / "assets.json", {
        "project.evidence": {"glyph": "🧪\ufe0f"},
        "icon.menu": {"glyph": "CAT"},
        "icon.mark-decision": {"glyph": "DEC"},
    })
    return root / "manifest.md"


def test_custom_catalog_resolves_base_and_framework_icons(tmp_path):
    manifest = icon_fixture(tmp_path)
    artifact = render_artifact(manifest, parse_manifest(manifest), asset_index="assets.json")
    data = decode_artifact_data(artifact)
    assert data["assets"]["project.evidence"]["value"] == {"glyph": "🧪\ufe0f"}
    assert 'data-icon="menu" aria-hidden="true">CAT</span>' in artifact
    chapter = next(note for note in data["notes"] if note["slug"] == "chapter")
    assert 'data-icon="mark.decision" aria-hidden="true">DEC</span>' in chapter["html"]
    assert chapter["tables"][0]["definition"]["properties"]["evidence"]["obsHtml"]["icon"]["name"] == "project.evidence"


@pytest.mark.parametrize("check", [False, True])
@pytest.mark.parametrize("case,expected", [
    ("missing", "Missing icon resource"),
    ("invalid-json", "Invalid semantic asset index"),
    ("invalid-entry", "does not match"),
    ("missing-asset", "Missing icon resource"),
    ("escape", "escapes its boundary"),
    ("unknown", "unknown reference"),
    ("remote", "does not match"),
    ("script", "Unsupported icon SVG element"),
    ("malformed-svg", "Invalid icon SVG"),
])
def test_invalid_resources_fail_real_build_and_check(tmp_path, capsys, case, expected, check):
    source = tmp_path / "source"
    manifest = icon_fixture(source)
    catalog = source / "assets.json"
    if case == "missing":
        catalog.unlink()
    elif case == "invalid-json":
        catalog.write_text("{", encoding="utf-8")
    elif case == "invalid-entry":
        write_index(catalog, {"project.evidence": {"glyph": ""}})
    elif case == "missing-asset":
        write_index(catalog, {"project.evidence": {"asset": "absent.png"}})
    elif case == "escape":
        (tmp_path / "outside.png").write_bytes(PIXEL)
        write_index(catalog, {"project.evidence": {"asset": "../outside.png"}})
    elif case == "unknown":
        write_index(catalog, {})
    elif case == "remote":
        write_index(catalog, {"project.evidence": {"asset": "https://example.invalid/icon.png"}})
    else:
        write_index(catalog, {"project.evidence": {"asset": "bad.svg"}})
        (source / "bad.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
            if case == "script" else "<svg", encoding="utf-8",
        )
    (source / "cfg.json").write_text('{"artifact":{"assetIndex":"assets.json"}}', encoding="utf-8")
    output = tmp_path / "artifact.html"
    with pytest.raises(SystemExit) as failure:
        main(["--source", str(manifest), "--output", str(output)] + (["--check"] if check else []))
    assert failure.value.code == 2
    assert expected in capsys.readouterr().err
    assert not output.exists()


def test_local_asset_and_catalog_survive_actual_cli_extraction_and_rebuild(tmp_path):
    source = tmp_path / "source"
    icon_fixture(source)
    (source / "pixel.png").write_bytes(PIXEL)
    write_index(source / "assets.json", {
        "project.evidence": {"asset": "pixel.png"}, "icon.menu": {"glyph": "<🧪>"},
    })
    (source / "cfg.json").write_text(
        '{"artifact":{"assetIndex":"assets.json","inactiveIconOpacity":0.3}}', encoding="utf-8",
    )
    config = load_config(ROOT / "src" / "obs_html_interim" / "cfg.json", source / "cfg.json")
    assert config.asset_index == "assets.json"
    output = tmp_path / "artifact.html"
    assert main(["--source", str(source), "--output", str(output), "--embed-source"]) == 0
    artifact = output.read_text(encoding="utf-8")
    assert "&lt;🧪&gt;" in artifact
    data = decode_artifact_data(artifact)
    resource = data["assets"]["project.evidence"]["value"]["asset"]
    assert resource.startswith("obs-asset:")
    descriptor = data["embeddedAssets"][resource.split(":")[1]]
    assert descriptor["archivePath"] == "vault/pixel.png"
    assert base64.b64encode(PIXEL).decode() not in json.dumps(data)
    extracted = tmp_path / "extracted"
    with ZipFile(BytesIO(embedded_archive(artifact))) as archive:
        assert json.loads(archive.read("build-config.json"))["artifact"]["assetIndex"] == "assets.json"
        assert json.loads(archive.read("build-config.json"))["artifact"]["inactiveIconOpacity"] == 0.3
        assert archive.read("vault/pixel.png") == PIXEL
        assert "generator/src/obs_html_interim/icons/filter.svg" in archive.namelist()
        assert "generator/src/obs_html_interim/running-header.js" in archive.namelist()
        archive.extractall(extracted)
    environment = os.environ | {"PYTHONPATH": str(extracted / "generator" / "src"), "PYTHONUTF8": "1"}
    rebuilt = subprocess.run(
        [sys.executable, str(extracted / "reproduce.py")],
        cwd=extracted, env=environment, capture_output=True, text=True, timeout=60,
    )
    assert rebuilt.returncode == 0, rebuilt.stdout + rebuilt.stderr
    rebuilt_data = decode_artifact_data((extracted / "document.html").read_text(encoding="utf-8"))
    assert rebuilt_data["assets"] == data["assets"]
    assert rebuilt_data["inactiveIconOpacity"] == 0.3


def test_download_compatibility_is_normalized_before_browser_projection(tmp_path):
    manifest = icon_fixture(tmp_path)
    chapter = tmp_path / "chapter.md"
    chapter.write_text(
        "```base\nproperties:\n  old:\n    obsHtml:\n      icon:\n"
        "        name: snapshot\n        label: Old snapshot\n"
        "        linkProperty: url\n        unavailable: Missing\n"
        "  explicit:\n    obsHtml:\n      icon:\n"
        "        name: snapshot\n        label: Source navigation\n"
        "        linkProperty: url\n        unavailable: Missing\n        download: false\n"
        "views: [{type: table, order: [old, explicit]}]\n```\n", encoding="utf-8",
    )
    data = decode_artifact_data(render_artifact(manifest, parse_manifest(manifest)))
    note = next(note for note in data["notes"] if note["slug"] == "chapter")
    properties = note["tables"][0]["definition"]["properties"]
    assert properties["old"]["obsHtml"]["icon"]["download"] is True
    assert properties["explicit"]["obsHtml"]["icon"]["download"] is False


@pytest.mark.skipif(not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"),
                    reason="Set OBS_HTML_TEST_NATIVE_BROWSER for native resource checks.")
def test_native_resources_cover_static_late_disabled_saved_and_print_controls(tmp_path):
    import yaml
    from playwright.sync_api import sync_playwright, expect

    source = tmp_path / "source"
    icon_fixture(source)
    write_index(source / "assets.json", {
        "project.evidence": {"glyph": "🧪\ufe0f"},
        "icon.close": {"glyph": "⊗"},
        "icon.filter": {"glyph": "F"},
        "icon.collapsed": {"glyph": "C"},
        "icon.expanded": {"glyph": "E"},
        "icon.snapshot": {"glyph": "📎\ufe0f"},
        "icon.unavailable": {"glyph": "📎\ufe0f"},
        "icon.menu": {"asset": "pixel.png"},
    })
    (source / "pixel.png").write_bytes(PIXEL)
    (source / "figure.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 30">'
        '<rect width="100" height="30" fill="#237a3b"/></svg>', encoding="utf-8",
    )
    (source / "snapshot.txt").write_text("Actual snapshot bytes.\n", encoding="utf-8")
    definition = {
        "filters": 'kind == "evidence"',
        "properties": {"actions": {"obsHtml": {"icons": [
            {"name": "project.evidence", "label": "Evidence instructions", "help": "Replace the original."},
            {"name": "menu", "label": "Image resource instructions", "help": "Local image fallback."},
            {"name": "snapshot", "label": "Download included snapshot", "linkProperty": "snapshot",
             "download": True, "unavailable": "No snapshot"},
            {"name": "snapshot", "label": "Open source system", "linkProperty": "source",
             "download": False, "unavailable": "No source"},
        ]}}},
        "views": [{"type": "table", "order": ["title", "actions"],
                   "groupBy": {"property": "status"}}],
    }
    (source / "chapter.md").write_text(
        "# Named resources\n\n## Evidence\n\nA chosen decision. #mark/decision/chosen\n\n"
        "```base\n" + yaml.safe_dump(definition, sort_keys=False) +
        "```\n\n![Local figure](figure.svg)\n", encoding="utf-8",
    )
    for index in range(3):
        (source / f"evidence-{index}.md").write_text(
            f"---\nkind: evidence\ntitle: Evidence {index}\nstatus: Ready\n"
            "snapshot: '![Original](snapshot.txt)'\nsource: '[Source](https://example.invalid/source)'\n---\n",
            encoding="utf-8",
        )
    (source / "missing.md").write_text("---\nkind: evidence\ntitle: Missing evidence\nstatus: Ready\n---\n",
                                       encoding="utf-8")
    (source / "cfg.json").write_text('{"artifact":{"assetIndex":"assets.json","tablePageSize":2}}',
                                   encoding="utf-8")
    output = tmp_path / "resources.html"
    assert main(["--source", str(source), "--output", str(output), "--embed-source",
                 "--embed-attachments"]) == 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"])
        context = browser.new_context(accept_downloads=True, viewport={"width": 1500, "height": 1000})
        page = context.new_page()
        page.set_default_timeout(6000)
        errors, failed = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("requestfailed", lambda request: failed.append(request.url))
        try:
            page.goto(output.as_uri() + "#chapter")
            page.evaluate("obsHtmlReady")
            page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('chapter')")
            page.evaluate("obsArtifact.whenChapterReady()")
            menu_image = page.locator('[data-menu-button] [data-icon="menu"] img')
            expect(menu_image).to_have_count(1)
            assert menu_image.evaluate("image => image.complete && image.naturalWidth === 1")
            table = page.locator('[data-active-chapter] [data-data-table="chapter-base-1"]')
            expect(table.locator(".data-table-page")).to_have_text("Page 1 of 2")
            expect(table.locator('[data-icon="project.evidence"]').first).to_have_text("🧪\ufe0f")
            expect(table.locator('[data-icon="expanded"]').first).to_have_text("E")
            table.get_by_role("button", name="Next table page", exact=True).click()
            expect(table.locator(".data-table-page")).to_have_text("Page 2 of 2")
            missing = table.locator('[data-row-key="note:missing"]')
            unavailable = missing.get_by_role("button", name="Download included snapshot: No snapshot", exact=True)
            expect(unavailable).to_be_disabled()
            expect(unavailable.locator("[data-icon]")).to_have_text("📎\ufe0f")
            table.get_by_role("button", name="First table page", exact=True).click()
            snapshot = table.get_by_role("link", name="Download included snapshot", exact=True).first
            with page.expect_download() as downloading:
                snapshot.click()
            download_path = tmp_path / "downloaded-snapshot.txt"
            downloading.value.save_as(download_path)
            assert download_path.read_text(encoding="utf-8") == "Actual snapshot bytes.\n"
            source_link = table.get_by_role("link", name="Open source system", exact=True).first
            expect(source_link).to_have_attribute("target", "_blank")
            assert source_link.get_attribute("download") is None
            table.locator(".data-table-options-toggle").click()
            table.locator(".data-table-options").get_by_role("button", name="Filter", exact=True).click()
            table.get_by_role("searchbox", name="Filter table", exact=True).fill("title:Evidence")
            expect(table.locator(".filter-status-icon")).to_be_visible()
            expect(table.locator(".filter-status-icon")).to_have_text("F")
            expect(table.locator('[data-clear-table-filter] [data-icon="close"]')).to_have_text("⊗")
            table.locator("[data-clear-table-filter]").click()
            table.locator(".data-table-options-toggle").click()
            page.evaluate("obsArtifact.openBar('comments')")
            expect(page.locator('.review-action--accept [data-icon="accept"]').first).to_have_text("✓")
            page.locator('[data-bar-close="comments"]').click()
            figure = page.locator("[data-active-chapter] figure")
            figure.get_by_role("button", name="Expand figure", exact=True).click()
            expect(page.locator(".figure-overlay")).to_be_visible()
            expect(page.locator('.figure-overlay-close [data-icon="close"]')).to_have_text("⊗")
            page.locator(".figure-overlay-close").click()
            page.screenshot(path=str(tmp_path / "resources-native.png"), full_page=True)
            saved = tmp_path / "reviewed.html"
            saved.write_text(page.evaluate("obsComments.reviewedHtml()"), encoding="utf-8")
            page.goto(saved.as_uri() + "#chapter")
            page.evaluate("obsHtmlReady")
            page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('chapter')")
            page.evaluate("obsArtifact.whenChapterReady()")
            assert page.locator('[data-menu-button] img').evaluate("image => image.complete && image.naturalWidth > 0")
            assert page.locator('[data-bar-close] [data-icon="close"]').all_text_contents() == ["⊗"] * 5
            page.evaluate("window.print = () => {}; obsPages.exportPDF()")
            expect(page.locator('.print-book [data-icon="project.evidence"]').first).to_have_text("🧪\ufe0f")
            assert page.locator('.print-book [data-icon="menu"] img').first.evaluate(
                "image => image.complete && image.naturalWidth === 1")
            page.emulate_media(media="print")
            pdf = page.pdf(path=str(tmp_path / "resources-native.pdf"), prefer_css_page_size=True)
            assert pdf.startswith(b"%PDF-")
            assert len(pdf) > 5000
            from pypdf import PdfReader
            document = PdfReader(BytesIO(pdf))
            assert any("Named resources" in sheet.extract_text() for sheet in document.pages)
            assert any(sheet.images for sheet in document.pages)
            assert errors == []
            data = decode_artifact_data(output.read_text(encoding="utf-8"))
            content_placeholders = {
                f"obs-asset:{key}" for key, asset in data["embeddedAssets"].items()
                if isinstance(asset, dict) and asset.get("archivePath") == "vault/figure.svg"
            }
            assert not set(failed) - content_placeholders
        finally:
            context.close()
            browser.close()
