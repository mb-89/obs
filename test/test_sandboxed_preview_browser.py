import html
from pathlib import Path

import pytest

from documents import chapter, document, heading, paragraph
from obs_html.config import load_config
from obs_html.render import render


@pytest.mark.browser
def test_report_runs_as_srcdoc_of_a_scripts_only_sandbox(tmp_path: Path, reader_browser) -> None:
    """Claude's preview shows HTML as srcdoc of a sandboxed frame that cannot change its URL."""
    from playwright.sync_api import expect

    report = render(document(
        "Preview",
        chapter("one", "One", heading(1, "One"), paragraph("First chapter text.")),
        chapter("two", "Two", heading(1, "Two"), paragraph("Second chapter text.")),
    ), load_config())
    wrapper = tmp_path / "preview.html"
    wrapper.write_text(
        '<!doctype html><iframe id="report" sandbox="allow-scripts" '
        f'srcdoc="{html.escape(report, quote=True)}"></iframe>',
        encoding="utf-8",
    )
    page = reader_browser.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.goto(wrapper.as_uri())
    frame = page.frame_locator("#report")
    expect(frame.locator("html")).to_have_attribute("data-report-status", "ready")
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
