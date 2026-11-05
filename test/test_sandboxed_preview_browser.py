import html
import os
import re
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
    ), load_config())


def open_page(reader_browser, path: Path, errors: list[str]):
    page = reader_browser.new_page(viewport={"width": 1200, "height": 800})
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.goto(path.as_uri())
    return page


def open_sandboxed(tmp_path: Path, reader_browser, errors: list[str]):
    """Claude's preview: the HTML as srcdoc of a frame sandboxed to scripts only."""
    from playwright.sync_api import expect

    wrapper = tmp_path / "preview.html"
    wrapper.write_text(
        '<!doctype html><iframe id="report" sandbox="allow-scripts" style="width:1100px;height:700px" '
        f'srcdoc="{html.escape(preview_report(), quote=True)}"></iframe>',
        encoding="utf-8",
    )
    page = open_page(reader_browser, wrapper, errors)
    frame = page.frame_locator("#report")
    expect(frame.locator("html")).to_have_attribute("data-report-status", "ready")
    return page, frame


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

