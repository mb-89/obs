"""Native-browser tier: the fixture report's presentation runs in Chromium."""
import base64

import pytest

from conftest import FIXTURE
from obs_html import cli


pytestmark = pytest.mark.browser
PIXEL = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="


@pytest.fixture
def report_page(tmp_path, reader_browser):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "logo.png").write_bytes(base64.b64decode(PIXEL))
    report = tmp_path / "report.html"
    cli.main([str(FIXTURE), str(report), "--execute-commands", "--command-root", str(tmp_path)])
    page = reader_browser.new_page(viewport={"width": 1200, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: message.type == "error" and errors.append(message.text))
    page.goto(report.as_uri())
    page.wait_for_function("document.documentElement.dataset.reportStatus === 'ready'")
    yield page
    page.close()
    assert errors == []


def test_figures_draw_their_plot_and_sankey(report_page) -> None:
    report_page.evaluate("obsReport.activateChapter('appendix')")
    report_page.wait_for_selector("#appendix--figure-response.figure-plot-ready")
    assert report_page.locator("#appendix--figure-response .scatterlayer .trace").count() == 2
    assert report_page.locator("#appendix--figure-flow .sankey-node").count() == 3


def test_base_tables_evaluate_document_records_and_marks_show_their_icon(report_page) -> None:
    report_page.evaluate("obsReport.activateChapter('intro')")
    rows = report_page.locator('[data-data-table="intro-base-1"] tbody tr[data-row-key]')
    rows.first.wait_for()
    assert [row.locator("td").first.inner_text() for row in rows.all()] == ["beta", "alpha"]
    assert report_page.locator(".semantic-mark-icon--risk .resource-icon").inner_text() == "!"


def test_the_print_book_holds_every_front_page_and_chapter(report_page) -> None:
    report_page.evaluate("window.print = () => {}; globalThis.obsPages.exportPDF()")
    text = report_page.locator(".print-book").inner_text()
    for expected in ("Fixture document", "Contents", "Abstract", "Intro", "Usage", "Appendix"):
        assert expected in text


def test_everything_on_the_title_page_is_centered(tmp_path, reader_browser) -> None:
    import json
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["manifest"]["metadata"]["subtitle"] = f"Bridge ![A](data:image/png;base64,{PIXEL})"
    source = tmp_path / "document.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "logo.png").write_bytes(base64.b64decode(PIXEL))
    report = tmp_path / "report.html"
    cli.main([str(source), str(report), "--execute-commands", "--command-root", str(tmp_path)])
    page = reader_browser.new_page(viewport={"width": 1200, "height": 1000})
    page.goto(report.as_uri())
    page.wait_for_function("document.documentElement.dataset.reportStatus === 'ready'")
    offsets = page.evaluate("""() => {
        const heading = document.querySelector('[data-chapter-body] .document-heading');
        const sheet = heading.getBoundingClientRect();
        const middle = sheet.left + sheet.width / 2;
        const boxes = [];
        const walker = document.createTreeWalker(heading, NodeFilter.SHOW_TEXT);
        for (let node = walker.nextNode(); node; node = walker.nextNode()) {
            if (!node.textContent.trim()) continue;
            const range = document.createRange();
            range.selectNodeContents(node);
            const box = range.getBoundingClientRect();
            if (box.width) boxes.push([node.textContent.trim(), box.left + box.width / 2 - middle]);
        }
        heading.querySelectorAll('img').forEach(image => {
            const box = image.getBoundingClientRect();
            boxes.push(['img', box.left + box.width / 2 - middle]);
        });
        return boxes;
    }""")
    page.close()
    texts = [text for text, _offset in offsets]
    for expected in ("Example org", "Fixture document", "Specification", "Bridge", "img", "Ada, Lin"):
        assert any(expected in text for text in texts), (expected, texts)
    off_center = [(text, round(offset)) for text, offset in offsets
                  if abs(offset) > 2 and text not in {"Bridge", "img"}]
    assert off_center == []
    # The subtitle's text and badges are centered together as one line.
    line = [offset for text, offset in offsets if text in {"Bridge", "img"}]
    assert abs(sum(line) / len(line)) < 40
