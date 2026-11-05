"""Native proofs of text layout across reader and print: code-span breaks, heading keep, callouts."""
import os

import pytest

from obs_html.content import parse_manifest
from obs_html.renderer import render_report

CODES = ["content.py:1444", "src/obs_html/report.js", "alpha-beta-gamma-delta", "one_two_three_four"]
SEPARATORS = "/\\._:- "

# Character offsets at which a code span continues on a new line.
LINE_STARTS = r"""
(root) => [...root.querySelectorAll('.markdown-column code')].map((code) => {
    const range = document.createRange();
    const starts = [];
    let offset = 0;
    let top = null;
    const walker = document.createTreeWalker(code, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
        const node = walker.currentNode;
        for (let index = 0; index < node.length; index += 1) {
            range.setStart(node, index);
            range.setEnd(node, index + 1);
            const rect = range.getClientRects()[0];
            if (!rect) continue;
            if (top !== null && rect.top > top + 2) starts.push(offset + index);
            top = rect.top;
        }
        offset += node.length;
    }
    const column = code.closest('.markdown-column').getBoundingClientRect();
    const bounds = code.getBoundingClientRect();
    return {text: code.textContent, starts, inside: bounds.right <= column.right + 1};
})
"""

# Sheets, other than the cover, whose last laid-out block is a heading.
STRANDED = r"""
(root) => [...root.querySelectorAll('.paper-sheet')].flatMap((sheet) => {
    const content = sheet.querySelector('.paper-content') || sheet;
    if (content.querySelector('.document-heading')) return [];
    let last = null;
    for (const node of content.querySelectorAll('h1,h2,h3,h4,h5,h6,p,li,tr,figure,pre,aside,table,blockquote')) {
        const rect = node.getBoundingClientRect();
        if (!rect.height || node.closest('[hidden]')) continue;
        if (!last || rect.bottom > last.rect.bottom + 0.5) last = {node, rect};
    }
    return last && /^H[1-6]$/.test(last.node.tagName) ? [sheet.dataset.pageChapter] : [];
})
"""


@pytest.fixture(scope="module")
def text_browser():
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native text layout checks.")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        try:
            yield browser
        finally:
            browser.close()


def _open(browser, tmp_path, manifest_body, chapter_body="# Chapter\n\nChapter prose.\n"):
    manifest = tmp_path / "manifest.md"
    manifest.write_text(manifest_body, encoding="utf-8")
    (tmp_path / "chapter.md").write_text(chapter_body, encoding="utf-8")
    output = tmp_path / "document.html"
    output.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(output.as_uri())
    page.wait_for_function("document.documentElement.dataset.reportStatus === 'ready' && globalThis.obsPages")
    return page, errors


def _views(page):
    """Yield the paged reader, then the print book (print media hides the reader)."""
    yield page.locator(".paged-reader")
    yield _print_book(page)


def _print_book(page):
    page.evaluate("window.print = () => {}; obsPages.exportPDF()")
    page.wait_for_function("document.querySelector('.print-book .paper-sheet')")
    page.emulate_media(media="print")
    return page.locator(".print-book")


def test_native_code_spans_break_only_after_separators_in_a_narrow_column(tmp_path, text_browser):
    prose = " ".join(f"Path `{code}` here." for code in CODES)
    page, errors = _open(text_browser, tmp_path, "- [[chapter]]\n", (
        f"# Chapter\n\n||| 1:4\n{prose}\n|||\nWide neighbouring column prose.\n|||\n"
    ))
    try:
        page.evaluate("obsReport.activateChapter('chapter')")
        for root in _views(page):
            spans = root.evaluate(LINE_STARTS)
            assert [span["text"] for span in spans] == CODES
            assert any(span["starts"] for span in spans), "the column must be narrow enough to wrap code"
            for span in spans:
                assert span["inside"], span
                for start in span["starts"]:
                    assert span["text"][start - 1] in SEPARATORS, (span["text"], start)
        assert errors == []
    finally:
        page.close()


def test_native_search_highlights_a_code_span_across_break_opportunities(tmp_path, text_browser):
    page, errors = _open(text_browser, tmp_path, "- [[chapter]]\n",
                         "# Chapter\n\nSee `content.py:1444` for the owner.\n")
    try:
        from playwright.sync_api import expect

        page.evaluate("obsPages.setPaged(false); obsReport.openBar('search')")
        page.locator("[data-search-input]").fill('"content.py:1444"')
        expect(page.locator("[data-search-status]")).to_have_text("1 result.")
        page.locator("[data-search-results] a").first.click()
        marks = page.locator("[data-chapter-body] code mark.search-highlight")
        expect(marks.first).to_be_visible()
        assert "".join(marks.all_text_contents()) == "content.py:1444"
        assert errors == []
    finally:
        page.close()


def test_native_abstract_title_opens_the_first_section_instead_of_a_lone_sheet(tmp_path, text_browser):
    page, errors = _open(text_browser, tmp_path, (
        "- [[chapter]]\n\n## Executive summary\n\nSummary prose.\n\n## Decisions\n\nDecision prose.\n"
    ))
    try:
        sheets = page.locator(".paged-reader .paper-sheet")
        assert sheets.evaluate_all("nodes => nodes.map(node => node.dataset.pageChapter)") == [
            "home", "@executive-summary", "@decisions", "@contents",
        ]
        summary = page.locator(".paged-reader [data-page-chapter='@executive-summary']")
        assert summary.locator("h1").inner_text() == "Abstract"
        assert "Summary prose." in summary.inner_text()
        assert page.locator(".paged-reader").evaluate(STRANDED) == []
        book = _print_book(page)
        assert book.locator(".paper-sheet").evaluate_all(
            "nodes => nodes.map(node => node.dataset.pageChapter)",
        )[:4] == ["home", "@executive-summary", "@decisions", "@contents"]
        assert book.evaluate(STRANDED) == []
        assert errors == []
    finally:
        page.close()


def test_native_callout_tones_are_distinct_titled_cards(tmp_path, text_browser):
    kinds = ["note", "success", "warning", "danger", "quote"]
    body = "".join(f"> [!{kind}]\n> {kind} body.\n\n" for kind in kinds)
    page, errors = _open(text_browser, tmp_path, "- [[chapter]]\n", f"# Chapter\n\n{body}")
    try:
        page.evaluate("obsReport.activateChapter('chapter')")
        for root in _views(page):
            cards = root.locator("aside.content-callout").evaluate_all("""nodes => nodes.map(node => {
                const style = getComputedStyle(node);
                const title = node.querySelector(':scope > .content-card-title');
                return {kind: node.dataset.callout, border: style.borderTopColor,
                        fill: style.backgroundColor, title: title.textContent,
                        titleColor: getComputedStyle(title).color};
            })""")
            assert [card["kind"] for card in cards] == kinds
            assert [card["title"] for card in cards] == [kind.capitalize() for kind in kinds]
            assert len({card["border"] for card in cards}) == len(kinds)
            assert len({card["fill"] for card in cards}) == len(kinds)
            assert all(card["titleColor"] == card["border"] for card in cards)
        assert errors == []
    finally:
        page.close()
