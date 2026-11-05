"""Native acceptance boundary for an actual freshly built report, not a synthetic vault."""
import os
from pathlib import Path

import pytest


def test_authored_report_all_chapters_modes_and_pdf(tmp_path):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    authored = os.environ.get("OBS_HTML_TEST_AUTHORED_REPORT")
    if not executable or not authored:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER and OBS_HTML_TEST_AUTHORED_REPORT.")
    from playwright.sync_api import sync_playwright
    from pypdf import PdfReader

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text)
                if message.type == "error" and "Page layout failed" in message.text else None)
        page.goto(Path(authored).resolve().as_uri())
        slugs = page.evaluate("JSON.parse(document.querySelector('[data-report-data]').textContent).toc")
        assert slugs
        for width, height in [(1440, 900), (1920, 1440), (2560, 2160), (390, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            for slug in slugs:
                for paged in [False, True]:
                    page.evaluate("""({slug,paged}) => {
                        obsPages.setPaged(paged);
                        obsReport.activateChapter(slug);
                    }""", {"slug": slug, "paged": paged})
                    assert "Page layout failed" not in page.locator("[data-export-status]").inner_text(), (
                        width, height, slug, paged)
                    assert page.evaluate("document.documentElement.classList.contains('paged-mode')") == paged
                    projection = ".paged-reader" if paged else "[data-chapter-body]"
                    if paged:
                        assert page.locator(".paged-reader .paper-sheet").count()
                    assert page.locator(projection + " figure > img").evaluate_all("""images =>
                        images.every(image => {
                            if (getComputedStyle(image).display === 'none') {
                                return image.closest('figure').querySelector('.figure-live')
                                    ?.getBoundingClientRect().height > 0;
                            }
                            const bounds = image.getBoundingClientRect();
                            const frame = image.closest('figure').getBoundingClientRect();
                            return image.complete && image.naturalWidth > 0 && bounds.height > 0 &&
                                bounds.width > 0 && bounds.right <= frame.right + 1 &&
                                bounds.left >= frame.left - 1 && bounds.bottom <= frame.bottom + 1 &&
                                Math.abs(bounds.width / bounds.height -
                                    image.naturalWidth / image.naturalHeight) < .03;
                        })"""), (width, height, slug, paged)
        page.evaluate("window.print = () => {}; obsPages.exportPDF()")
        page.emulate_media(media="print")
        assert page.locator(".print-book .paper-content").evaluate_all("""areas =>
            areas.every(area => area.scrollHeight <= area.clientHeight + 1 &&
                area.closest('.paper-sheet').scrollWidth <=
                    area.closest('.paper-sheet').clientWidth + 1)""")
        output = tmp_path / "authored-report.pdf"
        page.pdf(path=str(output), prefer_css_page_size=True, print_background=True)
        assert PdfReader(output).pages
        assert errors == []
        browser.close()
