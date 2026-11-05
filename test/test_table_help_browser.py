import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile

import pytest
import yaml

from obs_html.content import parse_manifest
from obs_html.renderer import render_report
from pickers import choose_files
from test_reader_controls import reader_browser


ROOT = Path(__file__).resolve().parents[1]
HELP = (
    "Keep the **original evidence**.\n\n"
    "- Read [[target|the canonical instructions]].\n"
    "- Open [the official export](https://example.org/export).\n"
    "- Download [the source archive](obs-source:archive).\n\n"
    '<script>window.helpInjected = true</script>'
)
RUNTIME = """obsReport.registerApplication({
    id: 'help-fixture',
    actions: [{
        id: 'replaceEvidence', accept: '.txt', help: 'Choose replacement evidence.',
        handle: async ({file, noteId}) => {
            globalThis.helpSelection = {noteId, name: file.name, text: await file.text()};
        },
    }],
});"""


def write_help_fixture(root):
    root.mkdir(parents=True, exist_ok=True)
    spec = {
        "filters": 'kind == "evidence"',
        "properties": {
            "replace": {"obsHtml": {"icon": {
                "name": "replace", "label": "Replace evidence", "action": "replaceEvidence",
                "helpProperty": "instructions", "help": "Select the exported file, not a screenshot.",
            }}},
            "help": {"obsHtml": {"icon": {
                "name": "help", "label": "Evidence help", "helpProperty": "instructions",
            }}},
            "plain": {"obsHtml": {"icon": {
                "name": "help", "label": "Plain help", "help": "Plain text <em>is not HTML</em>.",
            }}},
            "missing": {"obsHtml": {"icon": {
                "name": "upload", "label": "Unavailable import", "unavailable": "No importer",
            }}},
        },
        "views": [{"type": "table", "order": ["title", "replace", "help", "plain", "missing"]}],
    }
    (root / "manifest.md").write_text("- [[chapter]]\n- [[target]]\n", encoding="utf-8")
    (root / "chapter.md").write_text(
        "# Evidence\n\n```base\n" + yaml.safe_dump(spec, sort_keys=False) + "```\n",
        encoding="utf-8",
    )
    (root / "target.md").write_text(
        "# Instructions\n\nCanonical instructions are kept here.\n", encoding="utf-8",
    )
    (root / "evidence.md").write_text(
        "---\n" + yaml.safe_dump({"kind": "evidence", "instructions": HELP}, sort_keys=False)
        + "---\n", encoding="utf-8",
    )
    (root / "runtime.js").write_text(RUNTIME, encoding="utf-8")
    return root / "manifest.md"


def render_help_fixture(root):
    manifest = write_help_fixture(root / "vault")
    report = root / "report.html"
    report.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    return report


def build_help_fixture_cli(root):
    manifest = write_help_fixture(root / "vault")
    report = root / "report.html"
    command = [
        sys.executable, "-c", "from obs_html.cli import main; raise SystemExit(main())",
        "--source", str(manifest), "--embed-source",
        "--trusted-runtime-bundle", f"help-fixture={manifest.parent / 'runtime.js'}",
    ]
    for mode, arguments in (
        ("check", ["--check"]), ("build", ["--output", str(report)]),
    ):
        result = subprocess.run(
            [*command, *arguments], cwd=ROOT, text=True, capture_output=True, timeout=60,
        )
        (root / f"cli-{mode}.txt").write_text(
            result.stdout + result.stderr, encoding="utf-8",
        )
        assert result.returncode == 0, result.stdout + result.stderr
    return report


def test_table_help_reuses_shared_rich_hover_dom(tmp_path):
    node = shutil.which("node")
    module = os.environ.get("OBS_HTML_TEST_DOM_MODULE") or str(
        ROOT / "test" / "browser" / "node_modules" / "linkedom",
    )
    if not node or not Path(module).is_dir():
        pytest.skip("Set OBS_HTML_TEST_DOM_MODULE to the existing linkedom adapter.")
    report = render_help_fixture(tmp_path)
    result = subprocess.run(
        [node, str(ROOT / "test" / "browser" / "report-ui.cjs"), str(report), module,
         "", "", "", "--table-help-only"],
        text=True, capture_output=True, cwd=ROOT, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_native_table_help_placement_keyboard_action_and_reopen(tmp_path, reader_browser):
    from playwright.sync_api import expect

    report = build_help_fixture_cli(tmp_path)
    context = reader_browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    errors = []
    requests = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    context.route("https://example.org/**", lambda route: (
        requests.append(route.request.url), route.fulfill(status=200, body="Export instructions"),
    ))
    try:
        page.goto(report.as_uri() + "#chapter")
        page.evaluate("obsHtmlReady")
        page.evaluate("obsPages.setPaged(false); obsReport.activateChapter('chapter')")
        page.evaluate("obsReport.whenChapterReady()")
        action = page.get_by_role("button", name="Replace evidence", exact=True)
        card = page.locator("#hover-card")
        expect(action).to_have_attribute("title", "Replace evidence")
        expect(page.locator(".data-table-icon-help")).to_have_count(0)
        picker_count = page.locator('input[type="file"]').count()
        action.focus()
        expect(card).to_be_visible()
        expect(card.locator("strong")).to_have_text("original evidence")
        expect(card).to_contain_text("Read the canonical instructions")
        assert page.evaluate("window.helpSelection") is None
        assert page.locator('input[type="file"]').count() == picker_count
        assert page.evaluate("window.helpInjected") is None
        assert requests == []
        assert card.locator("script, [onclick], a[href^='javascript:']").count() == 0

        def settle():
            # Resize and scroll events from a layout change fire before the next frames;
            # they hide the card, so let them pass before showing it again.
            page.evaluate("""() => new Promise(resolve =>
                requestAnimationFrame(() => requestAnimationFrame(resolve)))""")

        def verify_adjacent_placement(width, height, name):
            expect(card).to_be_visible()
            anchor = action.bounding_box()
            bounds = card.bounding_box()
            gap = card.evaluate("node => parseFloat(getComputedStyle(node).getPropertyValue('--hover-card-gap'))")
            assert bounds["x"] >= 0 and bounds["y"] >= 0
            assert bounds["x"] + bounds["width"] <= width
            assert bounds["y"] + bounds["height"] <= height
            assert bounds["x"] <= anchor["x"] + anchor["width"]
            assert bounds["x"] + bounds["width"] >= anchor["x"]
            assert min(
                abs(bounds["y"] - anchor["y"] - anchor["height"]),
                abs(anchor["y"] - bounds["y"] - bounds["height"]),
            ) == pytest.approx(gap, abs=1)
            (tmp_path / f"placement-{name}.json").write_text(json.dumps({
                "browser": reader_browser.version, "viewport": {"width": width, "height": height},
                "trigger": anchor, "card": bounds, "sharedGap": gap,
            }, indent=2), encoding="utf-8")
            page.screenshot(path=str(tmp_path / f"shared-help-{name}.png"))

        verify_adjacent_placement(1280, 900, "normal")
        page.keyboard.press("Escape")
        page.set_viewport_size({"width": 620, "height": 520})
        page.wait_for_function("innerWidth === 620 && innerHeight === 520")
        action.evaluate("node => node.style.cssText = 'position:fixed;right:16px;bottom:16px'")
        settle()
        action.blur()
        action.focus()
        expect(card).to_be_visible()
        verify_adjacent_placement(620, 520, "near-edge")
        page.keyboard.press("Escape")
        action.evaluate("node => node.removeAttribute('style')")
        settle()
        action.blur()
        action.focus()
        expect(card).to_be_visible()
        action.press("ArrowDown")
        internal = card.get_by_role("link", name="the canonical instructions")
        expect(internal).to_be_focused()
        page.keyboard.press("Escape")
        expect(card).to_be_hidden()
        expect(action).to_be_focused()
        action.hover()
        expect(card).to_be_visible()
        internal.hover()
        expect(card).to_be_visible()
        internal.click()
        expect(page.locator("[data-active-chapter]")).to_have_attribute("data-chapter", "target")
        expect(card).to_be_hidden()
        page.evaluate("obsReport.activateChapter('chapter')")
        page.evaluate("obsReport.whenChapterReady()")
        action.focus()
        expect(card).to_be_visible()
        with page.expect_popup() as popup:
            card.get_by_role("link", name="the official export").click()
        popup.value.close()
        assert requests == ["https://example.org/export"]
        action.blur()
        action.focus()
        expect(card).to_be_visible()
        with page.expect_download() as source_download:
            card.get_by_role("link", name="the source archive").click()
        archive = tmp_path / "source.zip"
        source_download.value.save_as(archive)
        with ZipFile(archive) as source:
            evidence = next(name for name in source.namelist() if name.endswith("/evidence.md"))
            assert yaml.safe_load(source.read(evidence).decode("utf-8").split("---")[1])["instructions"] == HELP
        choose_files(page, action.click, {
            "name": "replacement.txt", "mimeType": "text/plain", "buffer": b"replacement bytes",
        }, timeout=10_000)
        page.wait_for_function("globalThis.helpSelection?.name === 'replacement.txt'")
        assert page.evaluate("helpSelection") == {
            "noteId": "evidence", "name": "replacement.txt", "text": "replacement bytes",
        }
        help_control = page.get_by_role("button", name="Evidence help", exact=True)
        help_control.focus()
        expect(card).to_be_visible()
        expect(card).to_have_attribute("aria-label", "Evidence help")
        page.keyboard.press("Escape")
        help_control.press("Enter")
        expect(card).to_be_visible()
        # A click outside closes the card (report-ui.md "Overlays").
        page.evaluate("document.querySelector('[data-chapter-scroll]').click()")
        expect(card).to_be_hidden()
        help_control.blur()
        help_control.focus()
        expect(card).to_be_visible()
        saved = tmp_path / "reviewed.html"
        saved.write_text(page.evaluate("obsComments.reviewedHtml()"), encoding="utf-8")
        page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
        print_book = page.locator(".print-book")
        expect(card).to_be_hidden()
        expect(print_book).to_have_count(1)
        expect(print_book.locator(":scope > *").first).to_be_attached()
        assert print_book.locator(".hover-card, .data-table-icon-help").count() == 0
        page.evaluate("window.dispatchEvent(new Event('afterprint'))")
        page.goto(saved.as_uri() + "#chapter")
        page.evaluate("obsHtmlReady")
        page.evaluate("obsPages.setPaged(false); obsReport.activateChapter('chapter')")
        page.evaluate("obsReport.whenChapterReady()")
        expect(card).to_be_hidden()
        help_control.focus()
        expect(card).to_be_visible()
        expect(card.locator("strong")).to_have_text("original evidence")
        assert page.evaluate("""() => obsReport.canonicalNotes().find(note =>
            note.sourcePath === 'evidence.md').frontmatter.instructions""") == HELP
        assert errors == []
    finally:
        context.close()
