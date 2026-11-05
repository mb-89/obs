"""The semantic-index contract, including the actual Base/browser boundary."""
import base64
from io import BytesIO
import json
import math
import os
import random
import re
import struct
from zipfile import ZipFile
import zlib

import pytest
import yaml

from obs_html.content import parse_manifest
from obs_html.cli import main
from obs_html.renderer import render_artifact
from obs_html.artifact_data import decode_artifact_data
from obs_html.reproduction import embedded_archive
from obs_html.semantic_assets import SemanticAssets
from test_named_icons import PIXEL, icon_fixture, write_index
from test_semantic_identifier_exactness import LONG_NAME


def semantic_fixture(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.md").write_text("- [[chapter]]\n",
                                      encoding="utf-8")
    (root / "pixel.png").write_bytes(PIXEL)
    index = {"schemaVersion": 1, "assets": {
        "icon": {"children": {
            "unavailable": {"type": "icon", "value": {"glyph": "IN"}},
            "snapshot": {"value": {"asset": "pixel.png"}},
            "source": {"value": {"glyph": "ACT"}},
        }},
        "color": {"children": {
            "action": {"type": "color", "value": "#123456"},
            "text-muted": {"value": "#654321"},
        }},
        "project": {
            "type": "appearance", "defaultState": "active",
            "color": {"ref": "color.accent"},
            "states": {
                "active": {"color": {"ref": "color.action"}},
                "inactive": {"icon": {"ref": "icon.unavailable"}, "color": {"ref": "color.text-muted"}},
            },
            "children": {"evidence": {
                "color": {"ref": "color.failure"},
                "children": {
                    "snapshot": {"states": {"active": {"icon": {"ref": "icon.snapshot"}}}},
                    "source": {"states": {"active": {"icon": {"ref": "icon.source"}}}},
                },
            }},
        },
        "snapshotAlias": {"ref": "project.evidence.snapshot"},
    }}
    (root / "assets.json").write_text(json.dumps(index), encoding="utf-8")
    definition = {
        "filters": 'kind == "evidence"',
        "properties": {"actions": {"obsHtml": {"icons": [
            {"name": "snapshotAlias", "label": "Download evidence", "linkProperty": "document",
             "download": True, "unavailable": "Missing snapshot"},
            {"name": "project.evidence.source", "label": "Open source", "linkProperty": "source",
             "download": False, "unavailable": "Missing source"},
        ]}}},
        "views": [{"type": "table", "order": ["title", "actions"]}],
    }
    (root / "chapter.md").write_text("# Semantic resources\n\n```base\n" +
        yaml.safe_dump(definition, sort_keys=False) + "```\n", encoding="utf-8")
    (root / "entry.md").write_text(
        "---\nkind: evidence\ntitle: Available\ndocument: '![Snapshot](snapshot.txt)'\n"
        "source: '[Source](https://example.invalid/source)'\n---\n", encoding="utf-8")
    (root / "snapshot.txt").write_text("Snapshot evidence.\n", encoding="utf-8")
    (root / "missing.md").write_text("---\nkind: evidence\ntitle: Missing\n---\n", encoding="utf-8")
    return root / "manifest.md"


def test_semantic_hierarchy_alias_and_state_merge_reach_base_projection(tmp_path):
    manifest = semantic_fixture(tmp_path)
    data = decode_artifact_data(render_artifact(manifest, parse_manifest(manifest), asset_index="assets.json",
                                              embed_attachments=True))
    assert "icons" not in data
    assert data["assets"]["snapshotAlias"]["ref"] == "project.evidence.snapshot"
    appearance = data["assets"]["project.evidence.snapshot"]
    assert appearance["states"]["active"]["icon"] == "icon.snapshot"
    assert appearance["states"]["inactive"]["icon"] == "icon.unavailable"
    assert appearance["states"]["inactive"]["color"] == "color.text-muted"


def test_project_overlay_is_atomic_late_bound_and_keeps_defining_file_origin(tmp_path):
    semantic_fixture(tmp_path)
    assets = SemanticAssets(tmp_path, "assets.json")
    assert assets.icon("snapshotAlias", "active")["asset"].startswith("obs-asset:")
    assert assets.icon("snapshotAlias", "inactive") == {"glyph": "IN", "color": "color.text-muted"}
    assert assets.icon("project.evidence.source", "active") == {"glyph": "ACT", "color": "color.action"}
    assert assets.entry("color.action")["value"] == "#123456"
    # This file is inherited from the package, not sought alongside the project index.
    packaged = assets.icon("filter")["asset"].split(":")[1]
    assert assets.embedded_assets[packaged].startswith("data:image/svg+xml;")
    with pytest.raises(ValueError, match="state=unknown"):
        assets.icon("snapshotAlias", "unknown")


@pytest.mark.parametrize("check", [False, True])
@pytest.mark.parametrize("case,expected", [
    ("unknown-reference", "unknown reference"),
    ("cycle", "reference cycle"),
    ("type", "incompatible"),
    ("field-type", "reference type mismatch"),
    ("incomplete", "incomplete icon appearance"),
    ("default-state", "unknown default state"),
    ("duplicate", "Duplicate semantic definition"),
    ("null", "Invalid semantic asset index"),
    ("group-alias", "group/template cannot contain"),
    ("group-value", "group/template cannot contain"),
    ("unused-group-ref", "unknown reference"),
])
def test_invalid_semantic_resources_fail_build_and_check(tmp_path, capsys, case, expected, check):
    source = tmp_path / "source"
    semantic_fixture(source)
    path = source / "assets.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    project = data["assets"]["project"]
    snapshot = project["children"]["evidence"]["children"]["snapshot"]
    if case == "unknown-reference":
        snapshot["states"]["active"]["icon"] = {"ref": "missing.icon"}
    elif case == "cycle":
        data["assets"]["a"] = {"ref": "b"}
        data["assets"]["b"] = {"ref": "a"}
    elif case == "type":
        data["assets"]["color"]["children"]["text"] = {"type": "icon", "value": {"glyph": "X"}}
    elif case == "field-type":
        snapshot["states"]["active"]["color"] = {"ref": "icon.source"}
    elif case == "incomplete":
        del snapshot["states"]["active"]["icon"]
    elif case == "default-state":
        snapshot["defaultState"] = "missing"
    elif case == "null":
        snapshot["states"]["active"]["icon"] = None
    elif case == "group-alias":
        data["assets"]["unused"] = {"ref": "icon.source", "children": {}}
    elif case == "group-value":
        data["assets"]["unused"] = {"type": "icon", "value": {"glyph": "X"}, "children": {}}
    elif case == "unused-group-ref":
        data["assets"]["unused"] = {"type": "appearance", "icon": {"ref": "missing.icon"}, "children": {}}
    if case == "duplicate":
        path.write_text('{"schemaVersion":1,"assets":{"a":{},"a":{}}}', encoding="utf-8")
    else:
        path.write_text(json.dumps(data), encoding="utf-8")
    (source / "cfg.json").write_text('{"artifact":{"assetIndex":"assets.json"}}', encoding="utf-8")
    with pytest.raises(SystemExit) as failure:
        main(["--source", str(source), "--output", str(tmp_path / "bad.html")] + (["--check"] if check else []))
    assert failure.value.code == 2
    diagnostic = capsys.readouterr().err
    assert expected in diagnostic
    assert "assets.json" in diagnostic


@pytest.mark.skipif(not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"),
                    reason="Set OBS_HTML_TEST_NATIVE_BROWSER for semantic state checks.")
def test_native_obsidian_parent_states_resolve_icon_image_and_computed_color(tmp_path):
    from playwright.sync_api import sync_playwright, expect

    manifest = semantic_fixture(tmp_path)
    output = tmp_path / "semantic.html"
    output.write_text(render_artifact(manifest, parse_manifest(manifest), asset_index="assets.json",
                                              embed_attachments=True),
                      encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"])
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(output.as_uri() + "#chapter")
            page.evaluate("obsHtmlReady")
            page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('chapter')")
            page.evaluate("obsArtifact.whenChapterReady()")
            active = page.locator('[data-row-key="note:entry"] [aria-label="Download evidence"]')
            missing = page.locator('[data-row-key="note:missing"] .data-table-icon-action')
            expect(active.locator("img")).to_have_count(1)
            assert active.locator("img").evaluate("image => image.complete && image.naturalWidth === 1")
            assert active.locator("[data-icon]").evaluate("icon => getComputedStyle(icon).color") == "rgb(18, 52, 86)"
            assert missing.locator("[data-icon]").all_text_contents() == ["IN", "IN"]
            assert missing.locator("[data-icon]").evaluate_all(
                "icons => icons.every(icon => getComputedStyle(icon).color === 'rgb(101, 67, 33)')")
            expect(missing.first).to_be_disabled()
            source = page.locator('[data-row-key="note:entry"] [aria-label="Open source"]')
            expect(source.locator("[data-icon]")).to_have_text("ACT")
            expect(source).to_have_attribute("target", "_blank")
            assert source.get_attribute("download") is None
            assert active.get_attribute("download") == ""
            page.screenshot(path=str(tmp_path / "semantic-active-states.png"), full_page=True)
            page.evaluate("obsArtifact.commitCanonicalProjection([{slug:'entry',fields:{document:''}}])")
            unavailable = page.locator('[data-row-key="note:entry"] [aria-label="Download evidence: Missing snapshot"]')
            expect(unavailable).to_be_disabled()
            expect(unavailable.locator("[data-icon]")).to_have_text("IN")
            assert unavailable.locator("[data-icon]").evaluate(
                "e => getComputedStyle(e).color") == "rgb(101, 67, 33)"
            assert source.get_attribute("download") is None
            page.evaluate("""() => {
                const sample=document.createElement('span');
                sample.id='palette-proof'; sample.style.color='var(--color-surface)';
                document.body.append(sample); document.documentElement.dataset.theme='dark';
            }""")
            # The packaged palette owns the dark surface; the vault index here does not override it.
            dark = SemanticAssets(tmp_path, "assets.json").entry("color.surface")["value"]["dark"]
            expected = "rgb({}, {}, {})".format(*(int(dark[i:i + 2], 16) for i in (1, 3, 5)))
            assert page.locator("#palette-proof").evaluate("e => getComputedStyle(e).color") == expected
            page.emulate_media(media="print")
            assert page.locator("#palette-proof").evaluate("e => getComputedStyle(e).color") == "rgb(255, 255, 255)"
            page.emulate_media(media="screen")
            page.evaluate("document.documentElement.dataset.theme='light'")
            page.screenshot(path=str(tmp_path / "semantic-parent-states.png"), full_page=True)
            assert errors == []
        finally:
            browser.close()


@pytest.mark.skipif(not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"),
                    reason="Set OBS_HTML_TEST_NATIVE_BROWSER for composed opening checks.")
def test_native_semantic_resources_compose_with_early_header_and_reviewed_reopening(tmp_path):
    from playwright.sync_api import sync_playwright, expect

    manifest = semantic_fixture(tmp_path)
    manifest.write_text(
        "---\ntitle: Not an opening fallback\nproduct: {name: 'Product <&>'}\n"
        "document type: Matrix\nconfidentiality: Internal\n---\n- [[chapter]]\n",
        encoding="utf-8",
    )
    index = json.loads((tmp_path / "assets.json").read_text(encoding="utf-8"))
    index["assets"]["icon"]["children"]["menu"] = {"value": {"asset": "pixel.png"}}
    (tmp_path / "assets.json").write_text(json.dumps(index), encoding="utf-8")
    output = tmp_path / "composed.html"
    output.write_text(render_artifact(manifest, parse_manifest(manifest), asset_index="assets.json",
                                              embed_attachments=True),
                      encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"])
        context = browser.new_context(viewport={"width": 1200, "height": 900})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("""(() => {
            const frame = requestAnimationFrame, waiting = [];
            globalThis.requestAnimationFrame = callback => waiting.push(callback);
            globalThis.releaseOpening = () => {
                globalThis.requestAnimationFrame = frame;
                waiting.splice(0).forEach(callback => frame(callback));
            };
        })();""")
        try:
            for path in (output, tmp_path / "composed-reviewed.html"):
                navigation = context.new_cdp_session(page)
                with page.expect_navigation(wait_until="load"):
                    navigation.send("Page.navigate", {"url": path.as_uri()})
                navigation.detach()
                page.wait_for_function("document.documentElement.dataset.artifactStatus === 'loading'")
                expect(page.locator(".reader-opening [role=status]")).to_be_visible()
                assert page.locator(".reader-opening .paper-header > span").all_text_contents() == [
                    "Product <&> · Matrix", "Internal",
                ]
                assert page.evaluate("typeof obsAssets") == "undefined"
                assert page.locator(".app-shell").get_attribute("inert") is not None
                assert page.locator("[data-menu-button]").is_disabled()
                page.evaluate("releaseOpening()")
                page.evaluate("obsHtmlReady")
                menu = page.locator("[data-menu-button] [data-icon] img")
                expect(menu).to_have_count(1)
                page.wait_for_function(
                    "document.querySelector('[data-menu-button] img')?.naturalWidth === 1")
                page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('chapter')")
                page.evaluate("obsArtifact.whenChapterReady()")
                expect(page.locator(
                    '[data-row-key="note:missing"] .data-table-icon-action [data-icon]').first).to_have_text("IN")
                if path == output:
                    page.evaluate("obsArtifact.commitCanonicalProjection([{slug:'entry',fields:{document:''}}])")
                    page.evaluate("""() => {
                        document.querySelector('#running-header-script').dataset.headerMetadata =
                            JSON.stringify({product: {name: 'Stale product'}});
                    }""")
                    (tmp_path / "composed-reviewed.html").write_text(
                        page.evaluate("obsComments.reviewedHtml()"), encoding="utf-8")
                else:
                    assert page.evaluate(
                        "JSON.parse(obsArtifact.serializeModel()).notes.find(note => note.slug === 'entry').frontmatter.document") == ""
            assert errors == []
        finally:
            context.close()
            browser.close()


def test_packaged_inactive_actions_keep_identity_and_explicit_shared_overrides(tmp_path):
    assets = SemanticAssets(tmp_path)
    assert "icon" not in assets.nodes["action"]["states"]["inactive"]
    for name in ("download", "upload", "source", "snapshot", "link", "replace", "reload"):
        assert "states" not in assets.nodes[f"action.{name}"]
        active = assets.icon(name, "active")
        inactive = assets.icon(name, "inactive")
        assert {k: v for k, v in active.items() if k != "color"} == {
            k: v for k, v in inactive.items() if k != "color"}
        assert inactive["color"] == "color.text-muted"
    (tmp_path / "assets.json").write_text(json.dumps({"schemaVersion": 1, "assets": {
        "action": {"states": {"inactive": {"icon": {"ref": "icon.unavailable"}}}},
    }}), encoding="utf-8")
    overridden = SemanticAssets(tmp_path, "assets.json")
    assert overridden.icon("snapshot", "inactive")["glyph"] == "□"
    assert overridden.icon("snapshot", "active")["glyph"] == assets.icon("snapshot", "active")["glyph"]


def test_color_only_appearance_is_valid_but_icon_consumers_require_an_icon(tmp_path):
    (tmp_path / "assets.json").write_text(json.dumps({"schemaVersion": 1, "assets": {
        "textAppearance": {"type": "appearance", "color": {"ref": "color.action"}},
    }}), encoding="utf-8")
    assets = SemanticAssets(tmp_path, "assets.json")
    assert assets.entry("textAppearance") == {"type": "appearance", "color": "color.action"}
    with pytest.raises(ValueError, match="incomplete icon appearance"):
        assets.icon("textAppearance")


def _png():
    def chunk(kind, raw):
        return struct.pack(">I", len(raw)) + kind + raw + struct.pack(">I", zlib.crc32(kind + raw))

    pixels = random.Random(1028).randbytes(256 * 256 * 3)
    scanlines = b"".join(b"\0" + pixels[offset:offset + 768] for offset in range(0, len(pixels), 768))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 256, 256, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(scanlines)) + chunk(b"IEND", b""))


@pytest.mark.parametrize("archive", [False, True])
def test_one_image_used_once_in_markdown_and_icon_has_one_payload_owner(tmp_path, archive):
    source = tmp_path / "source"
    manifest = icon_fixture(source)
    raw = _png()
    (source / "shared.png").write_bytes(raw)
    write_index(source / "assets.json", {"project.evidence": {"asset": "shared.png"}})
    with (source / "chapter.md").open("a", encoding="utf-8") as chapter:
        chapter.write("\n![Shared original](shared.png)\n")
    (source / "cfg.json").write_text('{"artifact":{"assetIndex":"assets.json"}}', encoding="utf-8")
    output = tmp_path / "shared.html"
    assert main(["--source", str(manifest), "--output", str(output)]
                + (["--embed-source"] if archive else [])) == 0
    artifact = output.read_text(encoding="utf-8")
    data = decode_artifact_data(artifact)
    key = data["assets"]["project.evidence"]["value"]["asset"].split(":")[1]
    chapter = next(note for note in data["notes"] if note["slug"] == "chapter")
    assert f'src="obs-asset:{key}"' in chapter["html"]
    uri = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    assert json.dumps(data).count(uri) == (0 if archive else 1)
    if archive:
        descriptor = data["embeddedAssets"][key]
        with ZipFile(BytesIO(embedded_archive(artifact))) as payload:
            assert descriptor["archivePath"] == "vault/shared.png"
            assert payload.read(descriptor["archivePath"]) == raw
            assert sum(payload.read(name) == raw for name in payload.namelist()
                       if not name.endswith("/")) == 1
    else:
        assert data["embeddedAssets"][key] == uri


@pytest.mark.parametrize("value", [
    {"asset": "shared.png", "monochrome": True},
    {"glyph": "X", "monochrome": True},
    {"asset": "shared.svg", "monochrome": "yes"},
])
def test_monochrome_opt_in_does_not_expand_the_file_or_markup_boundary(tmp_path, value):
    (tmp_path / "shared.png").write_bytes(_png())
    (tmp_path / "shared.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>', encoding="utf-8")
    write_index(tmp_path / "assets.json", {"sample": value})
    with pytest.raises(ValueError):
        SemanticAssets(tmp_path, "assets.json")


def _raster_pixels(page, image, expected):
    return page.evaluate("""async ({encoded, expected}) => {
        const bitmap = await createImageBitmap(await (
            await fetch('data:image/png;base64,' + encoded)).blob());
        const canvas = document.createElement('canvas');
        canvas.width = bitmap.width; canvas.height = bitmap.height;
        const context = canvas.getContext('2d');
        context.drawImage(bitmap, 0, 0);
        const rgba = context.getImageData(0, 0, canvas.width, canvas.height).data;
        let matches = 0, black = 0, colored = 0, dark = 0;
        for (let i=0; i<rgba.length; i+=4) {
            if (expected.every((value, j) => Math.abs(rgba[i+j] - value) <= 5)) matches++;
            if (rgba[i] < 8 && rgba[i+1] < 8 && rgba[i+2] < 8) black++;
            const rgb = [rgba[i],rgba[i+1],rgba[i+2]];
            if (Math.max(...rgb) - Math.min(...rgb) > 12) colored++;
            if (Math.max(...rgb) < 230) dark++;
        }
        return {matches, black, colored, dark, width: canvas.width, height: canvas.height};
    }""", {"encoded": base64.b64encode(image).decode("ascii"), "expected": expected})


def _contained_icon_screenshot(page, icon, path):
    icon.scroll_into_view_if_needed()
    bounds = icon.bounding_box()
    assert bounds is not None
    left, top = math.ceil(bounds["x"]), math.ceil(bounds["y"])
    right = math.floor(bounds["x"] + bounds["width"])
    bottom = math.floor(bounds["y"] + bounds["height"])
    assert right > left and bottom > top
    clip = {"x": left, "y": top, "width": right - left, "height": bottom - top}
    path.with_suffix(".bounds.json").write_text(
        json.dumps({"element": bounds, "sample": clip}, indent=2), encoding="utf-8")
    # Locator screenshots round outwards and can include a neighboring colored icon.
    return page.screenshot(path=str(path), clip=clip)


@pytest.mark.skipif(not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"),
                    reason="Set OBS_HTML_TEST_NATIVE_BROWSER for actual resource pixel checks.")
@pytest.mark.parametrize("archive", [False, True])
def test_native_packaged_svg_pixels_follow_foreground_in_screen_print_and_saved_artifact(tmp_path, archive):
    from playwright.sync_api import sync_playwright

    source = tmp_path / "source"
    source.mkdir()
    (source / "manifest.md").write_text("- [[chapter]]\n",
                                        encoding="utf-8")
    (source / "art.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<rect width="24" height="24" fill="#df2468"/></svg>', encoding="utf-8")
    (source / "assets.json").write_text(json.dumps({"schemaVersion": 1, "assets": {
        "proofFilter": {"type": "appearance", "icon": {"ref": "icon.filter"},
                        "color": {"ref": "color.action"}},
        "proofExpand": {"type": "appearance", "icon": {"ref": "icon.figure-expand"},
                        "color": {"ref": "color.action"}},
        "art": {"type": "icon", "value": {"asset": "art.svg"}},
        "imageAction": {"type": "appearance", "icon": {"ref": "art"},
                        "states": {"active": {"color": {"ref": "color.action"}},
                                   "inactive": {"color": {"ref": "color.text-muted"}}}},
        "color": {"children": {"action": {"value": {"light": "#128654", "dark": "#d9e8f7"}}}},
        LONG_NAME.split(".")[0]: {"children": {
            LONG_NAME.split(".")[1]: {"type": "icon", "value": {"glyph": "LONG"}}}},
    }}), encoding="utf-8")
    definition = {"filters": 'kind == "entry"', "properties": {"actions": {"obsHtml": {"icons": [
        {"name": name, "label": name, "help": "Pixel evidence"}
        for name in ("proofFilter", "proofExpand", "art")
    ] + [{"name": name, "label": name, "linkProperty": "document", "unavailable": "Missing"}
         for name in ("snapshot", "imageAction")]}}}, "views": [{"type": "table", "order": ["title", "actions"]}]}
    (source / "available.md").write_text(
        "---\nkind: entry\ntitle: Available\ndocument: '![Original](original.txt)'\n---\n", encoding="utf-8")
    (source / "original.txt").write_text("Original evidence.\n", encoding="utf-8")
    (source / "missing.md").write_text("---\nkind: entry\ntitle: Missing\n---\n", encoding="utf-8")
    (source / "chapter.md").write_text(
        "# Native semantic color\n\n```base\n" + yaml.safe_dump(definition, sort_keys=False) + "```\n",
        encoding="utf-8")
    (source / "cfg.json").write_text('{"artifact":{"assetIndex":"assets.json"}}', encoding="utf-8")
    output = tmp_path / "colors.html"
    assert main(["--source", str(source), "--output", str(output), "--embed-attachments"]
                + (["--embed-source"] if archive else [])) == 0
    results, passive_results, errors = [], [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"])
        context = browser.new_context(viewport={"width": 1400, "height": 1000}, device_scale_factor=3)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            for opening, path in (("fresh", output), ("saved", tmp_path / "saved.html")):
                page.emulate_media(media="screen")
                page.goto(path.as_uri() + "#chapter")
                page.evaluate("obsHtmlReady")
                page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('chapter')")
                page.evaluate("obsArtifact.whenChapterReady()")
                for mode in ("light", "dark", "print"):
                    if mode == "print":
                        page.evaluate("window.print=()=>{}; obsPages.exportPDF()")
                        page.emulate_media(media="print")
                        root = ".print-book"
                    else:
                        page.evaluate("theme => document.documentElement.dataset.theme=theme", mode)
                        root = "[data-active-chapter]"
                    page.wait_for_function("""selector => [...document.querySelectorAll(selector + ' img')]
                        .every(image => image.complete && image.naturalWidth > 0)""", arg=root)
                    for name in ("proofFilter", "proofExpand", "art"):
                        icon = page.locator(f'{root} [data-icon="{name}"]').first
                        image = _contained_icon_screenshot(
                            page, icon, tmp_path / f"{opening}-{mode}-{name}.png")
                        expected = ([223, 36, 104] if name == "art" else
                                    [217, 232, 247] if mode == "dark" else [18, 134, 84])
                        results.append({"opening": opening, "mode": mode, "name": name,
                                        **_raster_pixels(page, image, expected)})
                    for slug in ("available", "missing"):
                        for name in ("snapshot", "imageAction"):
                            icon = page.locator(
                                f'{root} [data-row-key="note:{slug}"] [data-icon="{name}"]'
                            ).first
                            image = _contained_icon_screenshot(
                                page, icon, tmp_path / f"{opening}-{mode}-{slug}-{name}.png")
                            passive_results.append({"opening": opening, "mode": mode, "name": name,
                                                    "slug": slug, **_raster_pixels(page, image, [0, 0, 0])})
                    if mode == "print":
                        pdf = page.pdf(path=str(tmp_path / f"{opening}.pdf"),
                                       print_background=True, prefer_css_page_size=True)
                        assert pdf.startswith(b"%PDF-")
                if opening == "fresh":
                    saved = page.evaluate("obsComments.reviewedHtml()")
                    assert not re.search(r'style="[^"]*--resource-icon-mask', saved)
                    (tmp_path / "saved.html").write_text(saved, encoding="utf-8")
            (tmp_path / "pixel-evidence.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
            (tmp_path / "passive-evidence.json").write_text(
                json.dumps(passive_results, indent=2), encoding="utf-8")
            assert all(item["matches"] >= 5 for item in results), results
            assert all(item["colored"] == 0 and item["dark"] >= 5
                       for item in passive_results if item["slug"] == "missing"), passive_results
            assert all(item["colored"] >= 5 for item in passive_results
                       if item["slug"] == "available"), passive_results
            page.evaluate("""name => obsBases.validate({properties:{sample:{obsHtml:{icon:{
                name,label:'Shared long name',help:'Valid'}}}},views:[{type:'table',order:['sample']}]})""",
                          LONG_NAME)
            invalid = page.evaluate("""() => {
                const assets=globalThis.obsAssets; globalThis.obsAssets=undefined;
                try {
                    return ['a..b', 'a'.repeat(65), Array(5).fill('a'.repeat(63)).join('.')].map(name => {
                        try { obsBases.validate({properties:{sample:{obsHtml:{icon:{name,label:'Bad',help:'Bad'}}}},
                            views:[{type:'table',order:['sample']}]}); return false; }
                        catch(error) { return error instanceof TypeError; }
                    });
                } finally { globalThis.obsAssets=assets; }
            }""")
            assert all(invalid)
            assert errors == []
        finally:
            context.close()
            browser.close()


@pytest.mark.skipif(not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"),
                    reason="Set OBS_HTML_TEST_NATIVE_BROWSER for shared conditional palette checks.")
def test_native_text_icons_and_conditional_card_tones_share_overridden_color_owner(tmp_path):
    from playwright.sync_api import sync_playwright, expect

    source = tmp_path / "source"
    source.mkdir()
    (source / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (source / "assets.json").write_text(json.dumps({"schemaVersion": 1, "assets": {
        "sharedIcon": {"type": "appearance", "icon": {"ref": "icon.help"},
                       "color": {"ref": "color.action"}},
        "textAppearance": {"type": "appearance", "color": {"ref": "color.action"}},
        "color": {"children": {
            "action": {"value": {"light": "#126b54", "dark": "#b9e8d7"}},
            "text": {"value": {"ref": "color.action"}},
            "success": {"value": {"ref": "color.action"}},
            "negative": {"value": {"ref": "color.warning"}},
            "warning": {"value": {"light": "#9a3421", "dark": "#f8b399"}},
        }},
    }}), encoding="utf-8")
    cards = {"version": 1, "cards": [{
        "title": "Shared conditional color", "body": "Canonical card prose, not an asset.",
        "metrics": [{"label": "Selected records", "where": [{"field": "kind", "equals": "entry"}],
                     "toneRules": [{"value": "primary", "when": "zero", "tone": "negative"},
                                   {"value": "primary", "when": "positive", "tone": "positive"}]}],
    }]}
    base = {"properties": {"help": {"obsHtml": {"icon": {
        "name": "sharedIcon", "label": "Shared icon", "help": "Existing content",
    }}}}, "views": [{"type": "table", "order": ["title", "help"]}]}
    (source / "manifest.md").write_text(
        "- [[chapter]]\n\nCanonical paragraph content.\n\n```cards\n" + yaml.safe_dump(cards)
        + "```\n\n```base\n" + yaml.safe_dump(base) + "```\n", encoding="utf-8")
    (source / "chapter.md").write_text("# Shared appearance\n", encoding="utf-8")
    (source / "entry.md").write_text("---\nkind: entry\ntitle: Selected\n---\n", encoding="utf-8")
    (source / "cfg.json").write_text('{"artifact":{"assetIndex":"assets.json"}}', encoding="utf-8")
    output = tmp_path / "shared-colors.html"
    assert main(["--source", str(source), "--output", str(output)]) == 0
    data = decode_artifact_data(output.read_text(encoding="utf-8"))
    assert "Canonical paragraph" not in json.dumps(data["assets"])
    assert "Canonical card prose" not in json.dumps(data["assets"])
    assert "Canonical paragraph" in next(note for note in data["notes"] if note["slug"] == "home")["html"]
    colors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"])
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(output.as_uri() + "#home")
            page.evaluate("obsHtmlReady")
            page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('home')")
            page.evaluate("obsArtifact.whenChapterReady()")
            root = page.locator("[data-active-chapter]")
            metric = root.locator(".record-metric")
            paragraph = root.get_by_text("Canonical paragraph content.", exact=True)
            icon = root.locator('[data-icon="sharedIcon"]').first
            for theme, positive, negative in (("light", "rgb(18, 107, 84)", "rgb(154, 52, 33)"),
                                              ("dark", "rgb(185, 232, 215)", "rgb(248, 179, 153)")):
                page.evaluate("theme=>document.documentElement.dataset.theme=theme", theme)
                page.evaluate("obsArtifact.setFilter(obsQuery.compile(''))")
                expect(metric).to_have_class(re.compile("record-metric--positive"))
                expect(metric.locator("strong")).to_have_text("1")
                actual = [node.evaluate("e=>getComputedStyle(e).color")
                          for node in (paragraph, icon, metric.locator(".record-metric-value"))]
                assert actual == [positive] * 3
                page.evaluate("obsArtifact.setFilter(obsQuery.compile('title:NoSuchRecord'))")
                expect(metric).to_have_class(re.compile("record-metric--negative"))
                expect(metric.locator("strong")).to_have_text("0")
                selected = metric.locator(".record-metric-value").evaluate("e=>getComputedStyle(e).color")
                assert selected == negative
                colors.append({"theme": theme, "paragraphIconPositiveMetric": actual,
                               "zeroCountNegativeMetric": selected})
                page.screenshot(path=str(tmp_path / f"conditional-{theme}.png"), full_page=True)
            page.evaluate("obsArtifact.setFilter(obsQuery.compile('')); window.print=()=>{}; obsPages.exportPDF()")
            page.emulate_media(media="print")
            printed = page.locator(".print-book .record-metric-value").first
            assert printed.evaluate("e=>getComputedStyle(e).color") == "rgb(18, 107, 84)"
            assert errors == []
            (tmp_path / "shared-color-evidence.json").write_text(json.dumps(colors, indent=2), encoding="utf-8")
        finally:
            browser.close()
