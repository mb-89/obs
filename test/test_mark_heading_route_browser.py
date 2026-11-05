import os
from pathlib import Path

import pytest

from obs_html.content import parse_manifest
from obs_html.renderer import render_report


@pytest.mark.skipif(not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"),
                    reason="Set OBS_HTML_TEST_NATIVE_BROWSER for native heading navigation.")
def test_mark_prefixed_heading_and_real_mark_share_one_fragment_namespace(tmp_path: Path) -> None:
    from playwright.sync_api import sync_playwright

    filler = "".join(f"Filler paragraph {index}.\n\n" for index in range(80))
    (tmp_path / "owner.md").write_text(
        f"# Owner\n\n{filler}## Mark tags\n\nHeading body.\n\n{filler}"
        "Does the datum continue? #mark/risk/datum\n\n"
        f"{filler}## Mark-up rules\n\nRules body.\n\n{filler}",
        encoding="utf-8",
    )
    (tmp_path / "links.md").write_text(
        "# Links\n\n[[owner#Mark tags|heading]] [[owner#mark-owner-risk-datum|mark]] "
        "[[owner#Mark-up rules|rules]]\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[links]]\n- [[owner]]\n", encoding="utf-8")
    report = tmp_path / "report.html"
    report.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    targets = {
        "heading": ("#owner/mark-tags", "owner--mark-tags"),
        "mark": ("#owner/mark-owner-risk-datum", "mark-owner-risk-datum"),
        "rules": ("#owner/mark-up-rules", "owner--mark-up-rules"),
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            for name, (href, element_id) in targets.items():
                page.goto(report.as_uri() + "#links")
                link = page.locator(f'[data-chapter-body] a[href="{href}"]')
                assert link.inner_text() == name
                link.click()
                page.wait_for_function("(id) => document.getElementById(id)", arg=element_id)
                offset = page.evaluate("""(id) => {
                    const scroller = document.querySelector("[data-chapter-scroll]");
                    const target = document.getElementById(id).getBoundingClientRect().top;
                    return target - scroller.getBoundingClientRect().top;
                }""", element_id)
                assert page.evaluate("document.querySelector('[data-chapter-scroll]').scrollTop") > 0
                assert -2 <= offset < 1000, (name, offset)
            assert errors == []
        finally:
            browser.close()
