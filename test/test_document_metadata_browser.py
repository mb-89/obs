import os
from pathlib import Path

import pytest

from obs_html.content import parse_manifest
from obs_html.renderer import render_report


@pytest.mark.skipif(not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"),
                    reason="Set OBS_HTML_TEST_NATIVE_BROWSER for native metadata table checks.")
def test_document_metadata_rows_are_plain_keys_with_aligned_text_values(tmp_path: Path) -> None:
    from playwright.sync_api import sync_playwright

    (tmp_path / "one.md").write_text("# One\n\nContent.\n", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    # Home has no implicit tables: the metadata section and its table are authored.
    manifest.write_text(
        "---\nowners: [Ada, Lin]\nsettings: {review: true, depth: {max: 2}}\n---\n- [[one]]\n"
        "\n## Metadata\n\n```base\nviews:\n  - type: table\n    name: Document metadata\n"
        "    order: [key, value]\nobsHtml: {records: documentMetadata}\n```\n",
        encoding="utf-8",
    )
    report = tmp_path / "report.html"
    report.write_text(render_report(
        manifest, parse_manifest(manifest),
        generator_provenance={"name": "obs_html", "version": "e95e452-dirty", "commit": "e95e452"},
        target_provenance={"name": "reference", "version": "ddde511", "commit": "ddde511"},
    ), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(report.as_uri())
            table = page.locator('[data-page-chapter="@metadata"] table').first
            table.wait_for()
            rows = table.evaluate("""(table) => Object.fromEntries([...table.querySelectorAll("tbody tr")]
                .map((row) => [...row.querySelectorAll("td")].map((cell) => cell.innerText))
                .filter((cells) => cells.length >= 2).map((cells) => cells.slice(-2)))""")
            assert {"timestamp", "generator", "target", "owners", "settings"} <= set(rows)
            assert not any("generation" in key or "(generated)" in key or key == "generatorVersion"
                           for key in rows)
            assert rows["generator"] == "name:    obs_html\nversion: e95e452-dirty\ncommit:  e95e452"
            assert rows["target"] == "name:    reference\nversion: ddde511\ncommit:  ddde511"
            assert rows["owners"] == "Ada, Lin"
            assert rows["settings"] == "review:    true\ndepth.max: 2"
            assert not any(value.lstrip().startswith(("{", "[")) for value in rows.values())
            style = table.locator(".data-table-preformatted").first.evaluate(
                "(node) => [getComputedStyle(node).whiteSpace, getComputedStyle(node).fontFamily]")
            assert style[0] == "pre-wrap" and "monospace" in style[1]
            assert errors == []
        finally:
            browser.close()
