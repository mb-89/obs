import contextlib
import functools
import html
import http.server
import os
import re
import threading
from pathlib import Path

import pytest

from documents import chapter, document, heading, paragraph
from obs_html.config import load_config
from obs_html.render import render


def keep_screenshot(page, name: str) -> None:
    """Save a screenshot to $OBS_HTML_SCREENSHOTS, when set, for a field report to show."""
    folder = os.environ.get("OBS_HTML_SCREENSHOTS")
    if folder:
        page.screenshot(path=str(Path(folder) / f"{name}.png"))


def preview_report() -> str:
    return render(document(
        "Preview",
        chapter("one", "One", heading(1, "One"), paragraph("First chapter text.")),
        chapter("two", "Two", heading(1, "Two"), paragraph("Second chapter text.")),
        chapter("three", "Three", heading(1, "Three"), paragraph("Third chapter text.")),
    ), load_config())


def open_page(reader_browser, path: Path, errors: list[str]):
    page = reader_browser.new_page(viewport={"width": 1200, "height": 800})
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.goto(path.as_uri())
    return page


# The two preview-like frames: Claude's preview as srcdoc of a frame sandboxed to scripts only
# (null origin), and as srcdoc of a same-origin frame with the flags a preview host grants,
# served from an http origin as Claude's preview is.
SANDBOXES = {
    "null-origin": "allow-scripts",
    "same-origin": "allow-scripts allow-same-origin allow-popups allow-forms allow-downloads",
}


def preview_wrapper(report: str, sandbox: str, width: int = 1100, height: int = 700) -> str:
    return (
        '<!doctype html><meta charset="utf-8"><link rel="icon" href="data:,"><body style="margin:0">'
        f'<iframe id="report" sandbox="{sandbox}" style="width:{width}px;height:{height}px;border:0" '
        f'srcdoc="{html.escape(report, quote=True)}"></iframe>'
    )


@contextlib.contextmanager
def http_origin(folder: Path):
    """Serve a folder from an http origin for as long as the block runs."""
    handler = functools.partial(QuietHandler, directory=str(folder))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join()


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        pass


def open_preview(tmp_path: Path, reader_browser, errors: list[str], report: str, frame_kind: str,
                 origin: str | None = None):
    """Open a report in one of the preview-like frames; same-origin frames need an http origin."""
    from playwright.sync_api import expect

    wrapper = tmp_path / f"preview-{frame_kind}.html"
    wrapper.write_text(preview_wrapper(report, SANDBOXES[frame_kind]), encoding="utf-8")
    page = reader_browser.new_page(viewport={"width": 1200, "height": 800})
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.goto(f"{origin}/{wrapper.name}" if origin else wrapper.as_uri())
    frame = page.frame_locator("#report")
    expect(frame.locator("html")).to_have_attribute("data-report-status", "ready")
    return page, frame


def open_sandboxed(tmp_path: Path, reader_browser, errors: list[str]):
    """Claude's preview: the HTML as srcdoc of a frame sandboxed to scripts only."""
    return open_preview(tmp_path, reader_browser, errors, preview_report(), "null-origin")


def click_where_visible(page, frame, selector: str) -> None:
    """Click by pointer at the element's visible centre, failing if something else covers it."""
    element = frame.locator(selector).first
    element.scroll_into_view_if_needed()
    covering = element.evaluate("""(element) => {
        const box = element.getBoundingClientRect();
        const top = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
        if (!top || element.contains(top)) return "";
        const owner = top.closest("[data-step], [data-bar], button, a") || top;
        return owner.outerHTML.slice(0, 120);
    }""")
    assert covering == "", f"{selector} is covered at its visible position by {covering}"
    box = element.bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


@pytest.mark.browser
def test_report_runs_as_srcdoc_of_a_scripts_only_sandbox(tmp_path: Path, reader_browser) -> None:
    """Claude's preview shows HTML as srcdoc of a sandboxed frame that cannot change its URL."""
    from playwright.sync_api import expect

    errors: list[str] = []
    _page, frame = open_sandboxed(tmp_path, reader_browser, errors)
    chapter_element = frame.locator("[data-active-chapter]")
    expect(chapter_element).to_have_attribute("data-chapter", "home")

    frame.locator('[data-step="1"]').first.click()
    expect(chapter_element).to_have_attribute("data-chapter", "one")
    expect(frame.locator("[data-chapter-body]")).to_contain_text("First chapter text.")
    frame.locator('[data-step="1"]').first.click()
    expect(chapter_element).to_have_attribute("data-chapter", "two")
    frame.locator('[data-step="-1"]').first.click()
    expect(chapter_element).to_have_attribute("data-chapter", "one")
    assert errors == []



@pytest.mark.browser
def test_canaries_find_what_a_scripts_only_sandbox_limits(tmp_path: Path, reader_browser) -> None:
    errors: list[str] = []
    _page, frame = open_sandboxed(tmp_path, reader_browser, errors)
    limits = frame.locator("html").evaluate("() => globalThis.obsCapabilities.limits")
    assert [entry["key"] for entry in limits] == [
        "history", "storage", "printing", "dialogs", "downloads", "clipboard", "popups"]
    assert all(entry["reason"] and entry["remedy"] for entry in limits)
    assert {entry["key"] for entry in limits if entry["refused"]} == {"history", "storage", "clipboard"}
    assert errors == []


@pytest.mark.browser
def test_a_sandboxed_frame_shows_one_limited_functionality_notice(tmp_path: Path, reader_browser) -> None:
    from playwright.sync_api import expect

    errors: list[str] = []
    page, frame = open_sandboxed(tmp_path, reader_browser, errors)
    notice = frame.locator("[data-header-notices] [data-capability-notice]")
    expect(notice).to_have_count(1)
    summary = notice.locator("summary")
    expect(summary).to_have_text(re.compile(r"^Limited functionality: \d+ features$"))
    items = notice.locator("li[data-capability]")
    expect(items.first).to_be_hidden()
    count = int(summary.inner_text().split(": ")[1].split()[0])
    assert items.count() == count
    keep_screenshot(page, "limited-functionality-collapsed")
    summary.click()
    printing = notice.locator('li[data-capability="printing"]')
    dialogs = notice.locator('li[data-capability="dialogs"]')
    expect(printing).to_be_visible()
    expect(printing).to_contain_text("Print to PDF")
    expect(printing).to_contain_text("print dialog")
    expect(printing).to_contain_text("Open the HTML file directly in a browser to print.")
    expect(dialogs).to_contain_text("Dialogs")
    expect(dialogs).to_contain_text("Open the HTML file directly in a browser")
    keep_screenshot(page, "limited-functionality-expanded")
    frame.locator("html").evaluate("() => globalThis.obsFilter.setExpression('file.name == \\'One\\'')")
    expect(frame.locator("[data-filter-warning]")).to_be_visible()
    expect(notice).to_be_visible()
    frame.locator(".filter-warning-clear").click()
    expect(notice).to_be_visible()
    page.emulate_media(media="print")
    expect(notice).to_be_hidden()
    assert errors == []


@pytest.mark.browser
def test_the_same_report_opened_normally_shows_no_notice(tmp_path: Path, reader_browser) -> None:
    from playwright.sync_api import expect

    path = tmp_path / "report.html"
    path.write_text(preview_report(), encoding="utf-8")
    errors: list[str] = []
    page = open_page(reader_browser, path, errors)
    expect(page.locator("html")).to_have_attribute("data-report-status", "ready")
    assert page.evaluate("globalThis.obsCapabilities.limits.length") == 0
    expect(page.locator("[data-capability-notice]")).to_have_count(0)
    assert errors == []

@pytest.mark.browser
def test_print_to_pdf_in_a_sandboxed_frame_ends_in_an_inline_message(tmp_path: Path, reader_browser) -> None:
    from playwright.sync_api import expect

    errors: list[str] = []
    _page, frame = open_sandboxed(tmp_path, reader_browser, errors)
    frame.locator("[data-menu-button]").click()
    frame.locator('[data-dock-bar="settings"]').first.click()
    frame.locator("[data-export-pdf]").click()
    status = frame.locator("[data-export-status]")
    expect(status).to_be_visible()
    expect(status).to_contain_text("PDF export failed: Print to PDF is limited here")
    expect(status).to_contain_text("Open the HTML file directly in a browser to print.")
    expect(frame.locator("html")).not_to_have_class(re.compile("preparing-print"))
    # The browser reports the ignored print() call itself; the export logs its own inline failure.
    assert [error for error in errors if "print" not in error.lower()] == []


@pytest.mark.browser
def test_a_message_without_modal_dialogs_appears_beside_its_control(tmp_path: Path, reader_browser) -> None:
    from playwright.sync_api import expect

    errors: list[str] = []
    dialogs: list[str] = []
    page, frame = open_sandboxed(tmp_path, reader_browser, errors)
    page.on("dialog", lambda dialog: dialogs.append(dialog.message))
    frame.locator("[data-chapter-body]").evaluate("""(body) => {
        const link = document.createElement("a");
        link.href = "#tag";
        link.dataset.tagKind = "nothing";
        link.dataset.tagLabel = "nowhere";
        link.textContent = "untabled tag";
        body.append(link);
    }""")
    frame.get_by_text("untabled tag").dispatch_event("click")
    expect(frame.locator("[data-capability-message]")).to_have_text("No table in this document includes this tag.")
    assert dialogs == []
    assert errors == []



@pytest.mark.browser
@pytest.mark.parametrize("frame_kind", SANDBOXES)
@pytest.mark.parametrize("page_mode", ["pages", "continuous"])
def test_home_and_the_chapter_chooser_are_not_covered_by_the_previous_arrow(
        tmp_path: Path, reader_browser, frame_kind: str, page_mode: str) -> None:
    """Home opens Home from every chapter when clicked where it is shown, in both preview frames."""
    from playwright.sync_api import expect

    errors: list[str] = []
    with http_origin(tmp_path) as origin:
        page, frame = open_preview(tmp_path, reader_browser, errors, preview_report(), frame_kind,
                                   origin if frame_kind == "same-origin" else None)
        if page_mode == "continuous":
            frame.locator("html").evaluate("() => globalThis.obsPages.setPaged(false)")
        chapter_element = frame.locator("[data-active-chapter]")
        for steps in (1, 2, 3):
            for _ in range(steps):
                click_where_visible(page, frame, '[data-step="1"] .chapter-nav-icon')
            expect(chapter_element).not_to_have_attribute("data-chapter", "home")
            click_where_visible(page, frame, ".chapter-breadcrumb-toggle")
            expect(frame.locator(".chapter-breadcrumb-chooser[open]")).to_have_count(1)
            page.keyboard.press("Escape")
            click_where_visible(page, frame, ".chapter-home-link")
            expect(chapter_element).to_have_attribute("data-chapter", "home")
    assert errors == []


@pytest.mark.browser
@pytest.mark.parametrize("frame_kind", SANDBOXES)
def test_applying_or_clearing_a_filter_does_not_claim_the_html_changed(
        tmp_path: Path, reader_browser, frame_kind: str) -> None:
    """A filter is reader state, not a content change (obs report-ui.md, input-model.md)."""
    from playwright.sync_api import expect

    errors: list[str] = []
    with http_origin(tmp_path) as origin:
        page, frame = open_preview(tmp_path, reader_browser, errors, preview_report(), frame_kind,
                                   origin if frame_kind == "same-origin" else None)
        frame.locator("html").evaluate("() => globalThis.obsReport.openBar('filter')")
        frame.locator("[data-filter-input]").fill("file.name == 'nothing'")
        expect(frame.locator("[data-filter-warning]")).to_be_visible()
        expect(frame.locator("[data-document-warning]")).to_be_hidden()
        frame.locator(".filter-warning-clear").click()
        expect(frame.locator("[data-filter-warning]")).to_be_hidden()
        expect(frame.locator("[data-document-warning]")).to_be_hidden()
        keep_screenshot(page, f"filtered-without-changed-notice-{frame_kind}")
    assert errors == []
