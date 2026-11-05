import json
import os
import re
from importlib.resources import files
from pathlib import Path

import pytest
import yaml

from obs_html.content import parse_manifest
from obs_html.renderer import render_report
from obs_html.report_data import decode_report_data
from test_reader_controls import _declare_query, _write_reader_fixture, reader_browser  # noqa: F401


@pytest.fixture
def opening_browser():
    if not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"):
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native opening-state checks.")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"],
        )
        yield browser
        browser.close()


def _hold_opening(page, report: Path, *, install: bool = True) -> None:
    if install:
        page.add_init_script("""(() => {
        const frame = requestAnimationFrame;
        const waiting = [];
        let held = true;
        globalThis.requestAnimationFrame = callback =>
            held ? waiting.push(callback) : frame(callback);
        globalThis.releaseOpening = () => {
            held = false;
            waiting.splice(0).forEach(callback => frame(callback));
        };
        globalThis.openingHeadings = [];
        new MutationObserver(records => records.forEach(record =>
            record.addedNodes.forEach(node => {
                if (node.nodeType === 1 && node.matches("[data-chapter-body] h1")) {
                    openingHeadings.push(node.textContent);
                }
            }))).observe(document, {childList: true, subtree: true});
    })();""")
    # Navigation deliberately stops before the normal fixture's ready boundary.
    navigation = page.context.new_cdp_session(page)
    with page.expect_navigation(wait_until="load"):
        navigation.send("Page.navigate", {"url": report.as_uri()})
    navigation.detach()
    page.wait_for_function("document.documentElement.dataset.reportStatus === 'loading'")


@pytest.mark.parametrize("width", [1440, 390])
@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        (
            {"product": {"name": "Example <&>"},
             "document type": "Trace matrix",
             "confidentiality": "Internal <&>, Review"},
            ["Example <&> · Trace matrix", "Internal <&>, Review"],
        ),
        ({"document type": "Changed matrix"}, ["Changed matrix"]),
        ({"confidentiality": "Only right <&>"}, ["Only right <&>"]),
        ({"product": {}, "document type": "", "confidentiality": ""}, []),
    ],
    ids=["both", "left-only", "right-only", "empty"],
)
def test_opening_reuses_centered_running_header_before_decode(
    tmp_path: Path, opening_browser, width, metadata, expected,
) -> None:
    from playwright.sync_api import expect

    metadata = {"title": "Browser title, not a loading fallback"} | metadata
    (tmp_path / "one.md").write_text("---\nstatus: draft\n---\n# One\n\nContent.\n", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text(
        "---\n" + yaml.safe_dump(metadata, allow_unicode=True) + "---\n- [[one]]\n",
        encoding="utf-8",
    )
    report = tmp_path / "report.html"
    report.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    context = opening_browser.new_context(viewport={"width": width, "height": 900})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        _hold_opening(page, report)
        opening = page.locator(".reader-opening")
        expect(opening).to_be_visible()
        assert opening.locator(".paper-header > span").all_text_contents() == expected
        assert opening.locator(".paper-header > span:empty").count() == 0
        assert page.locator("[data-chapter-body] h1").count() == 0
        assert page.evaluate("openingHeadings") == []
        assert page.evaluate("typeof obsReport") == "undefined"
        assert page.locator("[data-report-data]").get_attribute("data-encoding") == "gzip"
        assert page.locator(".app-shell").get_attribute("inert") is not None
        assert page.locator("[data-menu-button]").is_disabled()
        status = opening.locator('[role="status"]')
        expect(status).to_have_text("Opening HTML…")
        expect(status).to_have_attribute("aria-busy", "true")
        geometry = opening.evaluate("""el => {
            const scroll = document.querySelector("[data-chapter-scroll]");
            const reader = scroll.getBoundingClientRect();
            return [...el.querySelectorAll(".paper-header > span, [role=status]")].map(node => {
                const range = document.createRange();
                range.selectNodeContents(node);
                const rect = range.getBoundingClientRect();
                return {center: rect.x + rect.width / 2, top: rect.top, bottom: rect.bottom,
                    readerCenter: reader.x + scroll.clientWidth / 2};
            });
        }""")
        assert all(abs(item["center"] - item["readerCenter"]) <= 1 for item in geometry)
        assert all(left["bottom"] <= right["top"] for left, right in zip(geometry, geometry[1:]))
        (tmp_path / f"opening-{width}.json").write_text(
            json.dumps({"header": expected, "geometry": geometry}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        page.screenshot(path=str(tmp_path / f"opening-{width}.png"))
        page.evaluate("releaseOpening()")
        page.wait_for_function("document.documentElement.dataset.reportStatus === 'ready'")
        assert page.title() == metadata["title"]
        header = page.locator('.paged-reader [data-page-chapter="home"] .paper-header').first
        assert [text for text in header.locator("span").all_text_contents() if text] == expected
        assert header.evaluate("el => getComputedStyle(el).position") == "absolute"
        assert header.evaluate("el => getComputedStyle(el).flexDirection") == "row"
        assert page.locator(".reader-opening").count() == 0
        assert not page.locator("[data-menu-button]").is_disabled()
        if width == 1440 and len(expected) == 2:
            metadata = metadata | {"document type": "Revised matrix"}
            manifest.write_text(
                "---\n" + yaml.safe_dump(metadata, allow_unicode=True) + "---\n- [[one]]\n",
                encoding="utf-8",
            )
            updated = tmp_path / "updated.html"
            updated.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
            expected = ["Example <&> · Revised matrix", "Internal <&>, Review"]
            _hold_opening(page, updated, install=False)
            assert page.locator(".reader-opening .paper-header > span").all_text_contents() == expected
            page.evaluate("releaseOpening()")
            page.wait_for_function("document.documentElement.dataset.reportStatus === 'ready'")
            assert page.locator(
                '.paged-reader [data-page-chapter="home"] .paper-header',
            ).first.locator("span").all_text_contents() == expected
        page.evaluate("obsReport.commitCanonicalProjection([{slug:'one',fields:{status:'reviewed'}}])")
        page.evaluate("""() => {
            document.querySelector("#running-header-script").dataset.headerMetadata =
                JSON.stringify({product: {name: "Stale product"}});
        }""")
        saved = tmp_path / "reviewed.html"
        saved.write_text(page.evaluate("obsComments.reviewedHtml()"), encoding="utf-8")
        _hold_opening(page, saved, install=False)
        assert page.locator(".reader-opening .paper-header > span").all_text_contents() == expected
        expect(page.locator(".reader-opening [role=status]")).to_be_visible()
        page.evaluate("releaseOpening()")
        page.wait_for_function("document.documentElement.dataset.reportStatus === 'ready'")
        assert next(note for note in decode_report_data(saved.read_text(encoding="utf-8"))["notes"]
                    if note["slug"] == "one")["frontmatter"]["status"] == "reviewed"
        assert errors == []
    finally:
        context.close()


@pytest.mark.parametrize("removed", [{"theme": "dark"}, {"paged": False}])
def test_removed_reading_startup_settings_are_rejected(tmp_path: Path, removed) -> None:
    (tmp_path / "one.md").write_text("# One\n\nContent.\n", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n", encoding="utf-8")
    reading = json.loads(files("obs_html").joinpath("cfg.json").read_text(encoding="utf-8"))[
        "report"
    ]["reading"] | removed

    with pytest.raises(ValueError, match=rf"report\.reading\.{next(iter(removed))} was removed"):
        render_report(manifest, parse_manifest(manifest), reading=reading)


@pytest.mark.parametrize(("profile", "paged"), [("", True), ("layout: paged", True),
                                                ("layout: scrolling", False)])
def test_manifest_layout_declares_the_opening_view(tmp_path: Path, profile, paged) -> None:
    (tmp_path / "one.md").write_text("# One\n\nContent.\n", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    frontmatter = f"---\nobsHtml: {{{profile}}}\n---\n" if profile else ""
    manifest.write_text(f"{frontmatter}- [[one]]\n", encoding="utf-8")
    report = render_report(manifest, parse_manifest(manifest))
    data = decode_report_data(report)

    assert data["reading"]["theme"] == "light"
    assert data["reading"]["paged"] is paged
    assert f'classList.toggle("paged-mode", {str(paged).lower()})' in report
    assert "obsHtml" not in data["document"]["metadata"]


@pytest.mark.skipif(
    not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"),
    reason="Set OBS_HTML_TEST_NATIVE_BROWSER for native opening-state checks.",
)
def test_dark_os_saved_dark_and_reviewed_copy_start_light_and_paged(tmp_path: Path) -> None:
    from playwright.sync_api import expect, sync_playwright

    (tmp_path / "one.md").write_text("# One\n\nReviewable content.\n", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n", encoding="utf-8")
    report = tmp_path / "report.html"
    report.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"],
        )
        context = browser.new_context(color_scheme="dark", viewport={"width": 1600, "height": 1000})
        context.add_init_script("""(() => {
            localStorage.setItem("obs-html.appearance", "dark");
            localStorage.setItem("obs-html-reviewer", "Remembered Reviewer");
            requestAnimationFrame(() => {
                window.firstPaintTheme = document.documentElement.dataset.theme;
            });
        })();""")
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(report.as_uri() + "#one")
            expect(page.locator("html")).to_have_attribute("data-theme", "light")
            expect(page.locator("html")).to_have_class(re.compile(r"\bpaged-mode\b"))
            expect(page.locator("[data-chapter-body]")).to_contain_text("Reviewable content.")
            page.wait_for_function("typeof window.firstPaintTheme === 'string'")
            assert page.evaluate("firstPaintTheme") == "light"
            assert page.evaluate("matchMedia('(prefers-color-scheme: dark)').matches")
            assert page.evaluate("localStorage.getItem('obs-html.appearance')") == "dark"
            light_color = page.locator("body").evaluate("el => getComputedStyle(el).color")
            page.screenshot(path=str(tmp_path / "startup-light-pages.png"))
            page.evaluate("obsReport.openBar('settings', 'right')")
            page.locator("[data-theme-select]").select_option("dark")
            expect(page.locator("html")).to_have_attribute("data-theme", "dark")
            dark_color = page.locator("body").evaluate("el => getComputedStyle(el).color")
            assert dark_color != light_color
            page.locator("[data-pages-toggle]").uncheck()
            expect(page.locator("html")).not_to_have_class(re.compile(r"\bpaged-mode\b"))
            page.locator("[data-theme-select]").select_option("system")
            expect(page.locator("html")).to_have_attribute("data-theme", "system")
            assert page.locator("body").evaluate("el => getComputedStyle(el).color") == dark_color
            page.locator("[data-theme-select]").select_option("light")
            expect(page.locator("html")).to_have_attribute("data-theme", "light")
            page.locator("[data-theme-select]").select_option("dark")
            assert page.evaluate("localStorage.getItem('obs-html.appearance')") == "dark"
            page.evaluate("obsReport.openBar('comments', 'right')")
            expect(page.locator("[data-comment-author]")).to_have_value("Remembered Reviewer")
            page.locator("[data-chapter-body] .review-action--accept").first.click()
            saved = tmp_path / "reviewed.html"
            reviewed_html = page.evaluate("obsComments.reviewedHtml()")
            assert 'data-theme="dark"' in reviewed_html
            saved.write_text(reviewed_html, encoding="utf-8")
            page.goto(saved.as_uri() + "#one")
            expect(page.locator("html")).to_have_attribute("data-theme", "light")
            expect(page.locator("html")).to_have_class(re.compile(r"\bpaged-mode\b"))
            page.wait_for_function("typeof window.firstPaintTheme === 'string'")
            assert page.evaluate("firstPaintTheme") == "light"
            assert page.locator("body").evaluate("el => getComputedStyle(el).color") == light_color
            assert page.evaluate("obsComments.data.reviews.length") == 1
            page.evaluate("obsReport.openBar('comments', 'right')")
            expect(page.locator("[data-comment-author]")).to_have_value("Remembered Reviewer")
            assert errors == []
        finally:
            browser.close()


@pytest.mark.parametrize("fail", [False, True])
def test_native_progressive_pending_readiness_and_latest_filter(tmp_path, reader_browser, fail):
    manifest = _write_reader_fixture(tmp_path)
    report = tmp_path / "progressive.html"
    html = render_report(manifest, parse_manifest(manifest))
    html = html.replace('<script id="cards-script"', '''<script type="application/x-obs-html-script" data-obs-runtime>
        obsStartup.defer("Controlled calculation", () => new Promise((resolve,reject) => {
            window.finishCalculation = () => ''' + (
                'reject(new Error("Controlled startup failure"))' if fail else "resolve()"
            ) + ''';
        }));
        </script><script id="cards-script"''', 1)
    html = html.replace("</body>", '''<script type="application/x-obs-html-script" data-obs-runtime>
        window.lateRegistrationWasGated = document.querySelector(".app-shell").inert;
        </script></body>''')
    report.write_text(html, encoding="utf-8")
    page = reader_browser.new_page(viewport={"width": 1500, "height": 1000})
    try:
        page.main_frame.goto(report.as_uri(), wait_until="domcontentloaded")
        page.wait_for_function("!!window.finishCalculation")
        assert page.evaluate("lateRegistrationWasGated") is True
        assert page.locator("[data-chapter-body]").inner_text().strip()
        pending = page.locator("[data-record-metric][aria-busy='true']").first
        assert pending.inner_text() == "Calculating…"
        page.evaluate("obsFilter.setExpression('title:does-not-exist')")
        page.evaluate("""() => {
            window.saved = false;
            window.printCalls = 0;
            window.print = () => printCalls++;
            const printKey = new KeyboardEvent('keydown', {
                key:'p',ctrlKey:true,bubbles:true,cancelable:true});
            document.dispatchEvent(printKey);
            window.printKeyPrevented = printKey.defaultPrevented;
            const repeatedPrint = obsPages.exportPDF();
            window.printPromiseShared = repeatedPrint === obsPages.exportPDF();
            window.repeatedPrint = repeatedPrint.catch(error => ({error: error.message}));
            obsComments.reviewedHtml().then(() => saved=true).catch(()=>{});
        }""")
        assert page.evaluate("saved") is False
        assert page.evaluate("printKeyPrevented") is True
        assert page.evaluate("printPromiseShared") is True
        assert page.evaluate("printCalls") == 0
        page.evaluate("finishCalculation()")
        if fail:
            page.wait_for_function("document.documentElement.dataset.reportStatus === 'error'")
            assert "Controlled startup failure" in page.locator("[role='alert']").inner_text()
            assert page.evaluate("saved") is False
        else:
            page.wait_for_function("document.documentElement.dataset.reportStatus === 'ready'")
            assert page.evaluate("obsReport.filterSummary().expression") == "title:does-not-exist"
            page.wait_for_function("saved")
            page.wait_for_function("printCalls >= 1")
            page.evaluate("repeatedPrint")
            assert page.evaluate("printCalls") == 1
            assert page.locator("[data-record-metric][aria-busy='true']").count() == 0
        page.screenshot(path=str(tmp_path / f"progressive-{fail}.png"))
    finally:
        page.close()


def test_native_pending_destination_paints_and_repeated_intent_cannot_skip(tmp_path, reader_browser):
    manifest = _write_reader_fixture(tmp_path)
    manifest.write_text(manifest.read_text(encoding="utf-8").replace(
        "- [[chapter]]", "- [[chapter]]\n- [[peer]]"), encoding="utf-8")
    (tmp_path / "peer.md").write_text("# Deliberate different destination\n\nStatic peer.", encoding="utf-8")
    _declare_query(manifest, {"scope": "records", "where": [{"field": "kind", "equals": "relation"}]})
    report = tmp_path / "navigation.html"
    report.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    page = reader_browser.new_page(viewport={"width":1500,"height":1000})
    try:
        page.goto(report.as_uri())
        page.evaluate("""() => {
            window.originalStartup = obsStartup;
            window.releaseNavigation = [];
            window.obsStartup = {...obsStartup, yield: () => new Promise(resolve =>
                releaseNavigation.push(resolve))};
            document.querySelector('[data-step="1"]').click();
            document.querySelector('[data-step="1"]').click();
        }""")
        assert page.locator("[data-active-chapter]").get_attribute("data-chapter") == "chapter"
        page.keyboard.press("ArrowRight")
        assert page.locator("[data-active-chapter]").get_attribute("data-chapter") == "chapter"
        assert "Reader controls" in page.locator("[data-active-chapter]").inner_text()
        assert page.locator("[data-active-chapter] [aria-busy='true']").count()
        page.emulate_media(reduced_motion="reduce")
        assert page.locator(".reader-pending").first.evaluate(
            "node => getComputedStyle(node,'::before').animationName") == "none"
        page.screenshot(path=str(tmp_path / "pending-destination.png"))
        page.keyboard.press("ArrowLeft")
        assert page.locator("[data-active-chapter]").get_attribute("data-chapter") == "home"
        page.evaluate("obsFilter.setExpression('title:no-match'); obsReport.activateChapter('peer')")
        assert "Static peer." in page.locator("[data-active-chapter]").inner_text()
        page.evaluate("""() => {
            window.obsStartup = originalStartup;
            releaseNavigation.forEach(resolve => resolve());
        }""")
        page.wait_for_timeout(100)
        assert page.locator("[data-active-chapter]").get_attribute("data-chapter") == "peer"
        assert page.locator("[data-active-chapter] [data-data-table]").count() == 0
        assert page.evaluate("obsReport.filterSummary().expression") == "title:no-match"
        page.evaluate("obsFilter.setExpression(''); obsReport.activateChapter('chapter')")
        page.evaluate("obsReport.whenChapterReady()")
        assert page.locator("[data-active-chapter] [data-data-table]").count() == 1
        page.screenshot(path=str(tmp_path / "destination.png"))
    finally:
        page.close()
