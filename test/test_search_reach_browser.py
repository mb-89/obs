"""Search and filters reach the complete content, independent of pagination and expansion."""
import json
import os
import re

import pytest
import yaml

from obs_html.cli import main


ROWS = 45


@pytest.fixture(scope="module")
def reach_page(tmp_path_factory):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native search reach checks.")
    root = tmp_path_factory.mktemp("reach")
    vault = root / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("---\n" + json.dumps({"obsHtml": {"query": {
        "scope": "records", "where": [{"field": "kind", "equals": "item"}],
        "fields": [{"field": "route", "label": "Route"}],
    }}}) + "\n---\n- [[results]]\n", encoding="utf-8")
    for index in range(1, ROWS + 1):
        route = "Zebra late cell" if index == 38 else f"Route {index:02d}"
        body = "Okapi detail phrase.\n" if index == 3 else f"Detail body {index}.\n"
        (vault / f"item-{index:02d}.md").write_text(
            yaml.safe_dump({"kind": "item", "route": route, "group": "G" if index % 2 else "H",
                            "obsHtml": {"document": index == 3}})
            .join(["---\n", "---\n"]) + body, encoding="utf-8",
        )
    (vault / "results.md").write_text(
        "# Results\n\nResults prose.\n\n"
        "```base\nfilters: 'kind == \"item\"'\nviews:\n"
        "  - type: table\n    order: [route, group]\n```\n", encoding="utf-8",
    )
    report = root / "report.html"
    main(["--source", str(vault), "--output", str(report)])
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.set_default_timeout(5000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(report.as_uri())
        page.wait_for_function("document.documentElement.dataset.reportStatus === 'ready'"
                               " && globalThis.obsPages")
        try:
            yield page
            assert errors == []
        finally:
            browser.close()


def _table(page):
    return page.locator("[data-chapter-body] [data-data-table]:not([data-page-continuation])").first


def _search(page, text):
    page.evaluate("obsReport.openBar('search')")
    page.locator("[data-search-input]").fill(text)


@pytest.mark.parametrize("paged", [False, True])
def test_search_finds_and_reveals_a_cell_on_a_later_table_page(reach_page, paged):
    from playwright.sync_api import expect
    page = reach_page
    page.evaluate("paged=>{obsPages.setPaged(paged); obsReport.activateChapter('home')}", paged)
    _search(page, '"Zebra late cell"')
    expect(page.locator("[data-search-status]")).to_have_text("1 result.")
    page.locator("[data-search-results] a").first.click()
    expect(page.locator("[data-active-chapter]")).to_have_attribute("data-chapter", "results")
    expect(_table(page).locator(".data-table-page")).to_have_text("Page 2 of 3")
    mark = page.locator("[data-chapter-body] tr[data-row-key] mark.search-highlight")
    expect(mark).to_have_text("Zebra late cell")
    expect(mark).to_be_in_viewport()


def test_search_finds_and_expands_collapsed_row_details(reach_page):
    from playwright.sync_api import expect
    page = reach_page
    page.evaluate("obsPages.setPaged(false)")
    _search(page, '"Okapi detail phrase"')
    # The row's owner note is itself a navigable document, so it is a second hit.
    expect(page.locator("[data-search-status]")).to_have_text("2 results.")
    page.locator("[data-search-results] a", has_text="Results \u203a Table \u203a Route 03").click()
    expect(page.locator("[data-chapter-body] tr[data-detail-owner]")).to_have_count(1)
    mark = page.locator("[data-chapter-body] mark.search-highlight")
    expect(mark).to_have_text("Okapi detail phrase")
    expect(mark).to_be_in_viewport()


def test_table_filter_matches_all_pages_and_reachable_through_the_pager(reach_page):
    from playwright.sync_api import expect
    page = reach_page
    page.evaluate("obsPages.setPaged(false); obsReport.activateChapter('results')")
    table = _table(page)
    set_filter = ("expression=>document.querySelector('[data-chapter-body] [data-data-table]')"
                  ".dispatchEvent(new CustomEvent('obs-table-set-filter',{detail:{expression}}))")
    page.evaluate(set_filter, '"Zebra late cell"')
    expect(table.locator(".data-table-count")).to_have_text(f"1 of {ROWS} items")
    expect(table.locator("tr[data-row-key]")).to_have_count(1)
    page.evaluate(set_filter, '"Okapi detail phrase"')
    expect(table.locator(".data-table-count")).to_have_text(f"1 of {ROWS} items")
    page.evaluate(set_filter, "group: G")
    expect(table.locator(".data-table-count")).to_have_text(f"23 of {ROWS} items")
    expect(table.locator(".data-table-page")).to_have_text("Page 1 of 2")
    table.get_by_role("button", name="Last table page").click()
    expect(table.locator(".data-table-page")).to_have_text("Page 2 of 2")
    expect(table.locator("tr[data-row-key]")).to_have_count(3)
    page.evaluate(set_filter, "")


def test_global_filter_counts_and_search_respect_the_full_row_population(reach_page):
    from playwright.sync_api import expect
    page = reach_page
    page.evaluate("obsPages.setPaged(false); obsReport.activateChapter('results')")
    page.evaluate("obsReport.setFilter(obsQuery.compile('route: /Zebra|Route 4/'))")
    table = _table(page)
    expect(table.locator(".data-table-count")).to_have_text(re.compile(r"^7 of "))
    expect(table.locator(".data-table-page")).to_have_text("Page 1 of 1")
    _search(page, '"Zebra late cell"')
    expect(page.locator("[data-search-status]")).to_have_text("1 result.")
    page.evaluate("obsReport.setFilter(obsQuery.compile('route: /Route 4/'))")
    _search(page, '"Zebra late cell"')
    expect(page.locator("[data-search-status]")).to_have_text("0 results.")
    page.evaluate("obsReport.setFilter(obsQuery.compile(''))")


def test_keyboard_shortcuts_open_step_and_close_search(reach_page):
    from playwright.sync_api import expect
    page = reach_page
    page.evaluate("obsPages.setPaged(true); obsReport.closeBar('search'); obsReport.activateChapter('home')")
    search = page.locator("[data-search-input]")
    page.locator("body").press("Control+f")
    expect(search).to_be_focused()
    search.fill("Route 4")
    page.keyboard.press("Control+f")
    expect(page.locator("[data-bar='search']")).to_be_hidden()
    page.keyboard.press("Control+f")
    expect(search).to_be_focused()
    assert page.evaluate("(() => { const i = document.querySelector('[data-search-input]');"
                         " return [i.selectionStart, i.selectionEnd, i.value.length]; })()") == [0, 7, 7]
    status = page.locator("[data-search-status]")
    search.fill('"Zebra late cell" OR "Route 01"')
    expect(status).to_have_text("2 results.")
    page.keyboard.press("F3")
    expect(status).to_have_text("1 of 2 results.")
    table = _table(page)
    expect(table.locator(".data-table-page")).to_have_text("Page 1 of 3")
    expect(page.locator("[data-chapter-body] mark.search-highlight")).to_have_text("Route 01")
    page.keyboard.press("F3")
    expect(status).to_have_text("2 of 2 results.")
    expect(table.locator(".data-table-page")).to_have_text("Page 2 of 3")
    mark = page.locator("[data-chapter-body] mark.search-highlight")
    expect(mark).to_have_text("Zebra late cell")
    expect(mark).to_be_in_viewport()
    page.keyboard.press("F3")
    expect(status).to_have_text("1 of 2 results.")
    expect(table.locator(".data-table-page")).to_have_text("Page 1 of 3")
    page.keyboard.press("Shift+F3")
    expect(status).to_have_text("2 of 2 results.")
    expect(table.locator(".data-table-page")).to_have_text("Page 2 of 3")
    expect(search).to_be_focused()
    page.keyboard.press("Escape")
    expect(page.locator("[data-bar='search']")).to_be_hidden()
    page.keyboard.press("Control+f")
    expect(search).to_have_value('"Zebra late cell" OR "Route 01"')
    page.keyboard.press("Escape")
    expect(page.locator("[data-bar='search']")).to_be_hidden()
