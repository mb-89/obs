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
def test_a_sandboxed_frame_lists_its_limits_as_warning_notices(tmp_path: Path, reader_browser) -> None:
    from playwright.sync_api import expect

    errors: list[str] = []
    page, frame = open_sandboxed(tmp_path, reader_browser, errors)
    keys = frame.locator("html").evaluate("() => globalThis.obsCapabilities.limits.map(({key}) => key)")
    icon = frame.locator('[data-header-notices] [data-notice-icon="warning"]')
    expect(icon.locator("[data-notice-count]")).to_have_text(str(len(keys)))
    expect(frame.locator("[data-header-notices] [data-notice-icon]:visible")).to_have_count(1)
    warnings = frame.locator('[data-notice-list="warning"]')
    entries = warnings.locator('[data-notice^="capability-"]')
    expect(entries).to_have_count(len(keys))
    expect(warnings).to_be_hidden()
    keep_screenshot(page, "limited-functionality-collapsed")
    icon.click()
    printing = warnings.locator('[data-notice="capability-printing"]')
    expect(printing.locator("[data-notice-title]")).to_have_text("Limited functionality: Print to PDF")
    printing.locator("[data-notice-title]").click()
    details = printing.locator("[data-notice-details]")
    expect(details).to_be_visible()
    expect(details).to_contain_text("Print to PDF")
    expect(details).to_contain_text("print dialog")
    expect(details).to_contain_text("Open the HTML file directly in a browser to print.")
    expect(warnings.locator('[data-notice="capability-dialogs"] [data-notice-title]')).to_contain_text("Dialogs")
    keep_screenshot(page, "limited-functionality-expanded")
    frame.locator("html").evaluate("() => globalThis.obsFilter.setExpression('file.name == \\'One\\'')")
    information = frame.locator('[data-notice-icon="information"]')
    expect(information).to_be_visible()
    information.click()
    frame.locator('[data-notice="applied-filter"] [data-notice-title]').click()
    frame.locator('[data-notice="applied-filter"] [data-filter-clear]').click()
    expect(information).to_be_hidden()
    expect(icon).to_be_visible()
    page.emulate_media(media="print")
    expect(icon).to_be_hidden()
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
    expect(page.locator('[data-notice^="capability-"]')).to_have_count(0)
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
    # Ctrl+P has no visible control, so its failure reveals the printing entry.
    revealed = frame.locator('[data-notice="capability-printing"] [data-notice-details]')
    expect(revealed).to_be_hidden()
    frame.locator("html").evaluate(
        "() => document.dispatchEvent(new KeyboardEvent('keydown', {key: 'p', ctrlKey: true}))")
    expect(revealed).to_be_visible()
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

