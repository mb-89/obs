import html
import os
from pathlib import Path

import pytest

from obs_html_interim.content import parse_manifest
from obs_html_interim.renderer import render_artifact


@pytest.mark.skipif(
    not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"),
    reason="Set OBS_HTML_TEST_NATIVE_BROWSER for sandboxed srcdoc preview checks.",
)
def test_artifact_runs_as_srcdoc_of_a_scripts_only_sandbox(tmp_path: Path) -> None:
    """Claude's preview shows HTML as srcdoc of a sandboxed frame that cannot change its URL."""
    from playwright.sync_api import expect, sync_playwright

    (tmp_path / "one.md").write_text("# One\n\nFirst chapter text.\n", encoding="utf-8")
    (tmp_path / "two.md").write_text("# Two\n\nSecond chapter text.\n", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n- [[two]]\n", encoding="utf-8")
    artifact = render_artifact(manifest, parse_manifest(manifest))
    wrapper = tmp_path / "preview.html"
    wrapper.write_text(
        '<!doctype html><iframe id="artifact" sandbox="allow-scripts" '
        f'srcdoc="{html.escape(artifact, quote=True)}"></iframe>',
        encoding="utf-8",
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"],
        )
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: errors.append(message.text) if message.type == "error" else None,
        )
        try:
            page.goto(wrapper.as_uri())
            frame = page.frame_locator("#artifact")
            expect(frame.locator("html")).to_have_attribute("data-artifact-status", "ready")
            chapter = frame.locator("[data-active-chapter]")
            expect(chapter).to_have_attribute("data-chapter", "home")

            frame.locator('[data-step="1"]').first.click()
            expect(chapter).to_have_attribute("data-chapter", "one")
            expect(frame.locator("[data-chapter-body]")).to_contain_text("First chapter text.")
            frame.locator('[data-step="1"]').first.click()
            expect(chapter).to_have_attribute("data-chapter", "two")
            frame.locator('[data-step="-1"]').first.click()
            expect(chapter).to_have_attribute("data-chapter", "one")
            assert errors == []
        finally:
            browser.close()
