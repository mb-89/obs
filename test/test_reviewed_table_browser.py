import os
import re

import pytest

from obs_html.cli import main
from obs_html.report_data import decode_report_data, encode_report_data


@pytest.fixture
def reviewed_table_page(tmp_path):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for reviewed-table checks.")
    from playwright.sync_api import sync_playwright

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[one]]\n- [[two]]\n", encoding="utf-8")
    base = (
        '```base\nobsHtml: {records: note}\nviews:\n'
        "  - type: table\n    order: [title, status, explanation]\n```\n"
    )
    for slug, status in [("one", "finding-at-eit"), ("two", "covered")]:
        (vault / f"{slug}.md").write_text(
            f"---\nstatus: {status}\nexplanation: Original\n---\n# {slug.title()}\n\n"
            "Reviewable text.\n\n```property-editor\nversion: 1\nfield: explanation\nlabel: Explanation\n```\n\n"
            + base + ("\n" + base if slug == "one" else ""),
            encoding="utf-8",
        )
    report = tmp_path / "report.html"
    args = ["--source", str(vault), "--output", str(report)]
    assert main([*args, "--check"]) == 0
    assert main(args) == 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        context = browser.new_context(accept_downloads=True, viewport={"width": 1440, "height": 900})
        context.add_init_script("delete window.showSaveFilePicker")
        page = context.new_page()
        page.set_default_timeout(5000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            yield page, report
            assert errors == []
        finally:
            browser.close()


def _columns(table):
    return table.locator("thead th").evaluate_all("(nodes) => nodes.map(node => node.dataset.columnKey)")


def _save(page, path):
    page.evaluate("obsReport.openBar('comments')")
    with page.expect_download() as download:
        page.locator("[data-comment-save]").click()
    download.value.save_as(path)


def test_native_reviewed_table_columns_survive_without_leaking_or_dirtying(
    reviewed_table_page, tmp_path,
):
    from playwright.sync_api import expect

    page, report = reviewed_table_page
    page.goto(report.as_uri() + "#one")
    page.evaluate("obsPages.setPaged(false)")
    table = page.locator('.chapter-scroll [data-data-table="one-base-1"]')
    other = page.locator('.chapter-scroll [data-data-table="one-base-2"]')
    defaults = ["title", "status", "explanation"]
    assert _columns(table) == _columns(other) == defaults
    table.locator(".data-table-options-toggle").scroll_into_view_if_needed()
    table.locator(".data-table-options-toggle").click()
    table.get_by_role("button", name="Properties", exact=True).click()
    table.locator('button[title="Hide status"]').click()
    page.keyboard.press("Escape")
    table.locator('th[data-column-key="explanation"]').press("Alt+ArrowLeft")
    resize = table.locator('th[data-column-key="explanation"] .data-table-column-resize')
    resize.press("ArrowRight")
    resize.press("ArrowRight")
    width = table.locator("colgroup col").first.evaluate("node => parseInt(node.style.width)")
    assert width >= 96
    assert _columns(table) == ["explanation", "title"]
    assert _columns(other) == defaults
    page.evaluate("obsReport.openBar('filter')")
    page.locator("[data-filter-input]").fill("status:finding-at-eit")
    guidance = page.locator("[data-review-save-guidance]")
    expect(guidance).to_have_attribute("data-dirty", "false")
    assert not page.evaluate("""() => {
        const event = new Event('beforeunload', {cancelable:true});
        return window.dispatchEvent(event) && !event.defaultPrevented;
    }""")
    saved = tmp_path / "reviewed.html"
    _save(page, saved)
    page.goto(saved.as_uri() + "#one")
    assert _columns(table) == ["explanation", "title"]
    # Resized widths are session-only: the saved copy starts from content-sized widths again.
    assert table.locator("colgroup col").first.evaluate("node => parseInt(node.style.width)") != width
    assert _columns(other) == defaults
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    expect(page.locator("html")).to_have_class("paged-mode")
    expect(page.locator("[data-filter-input]")).to_have_value("status:finding-at-eit")
    expect(guidance).to_have_attribute("data-dirty", "false")
    model = page.evaluate("JSON.parse(obsReport.serializeModel())")
    assert len(model["notes"]) == 3
    assert model["readerState"]["tables"]["one-base-1"] == {
        "columns": ["explanation", "title"],
    }
    page.evaluate("obsReport.activateChapter('two')")
    expect(page.locator("[data-active-chapter]")).to_have_attribute("data-chapter", "home")
    page.evaluate("obsFilter.setExpression(''); obsReport.activateChapter('two')")
    other_chapter = page.locator('.chapter-scroll [data-data-table="two-base-1"]')
    expect(other_chapter.locator("thead th")).to_have_count(len(defaults))
    assert _columns(other_chapter) == defaults
    page.evaluate("obsReport.activateChapter('one')")
    assert _columns(table) == ["explanation", "title"]
    editor = page.locator(".paged-reader [data-property-editor]")
    editor.fill("Edited after restoring columns")
    editor.press("Tab")
    expect(guidance).to_have_attribute("data-dirty", "true")
    page.evaluate("""() => {
        obsComments.data.reviewers.push('Reader');
        obsComments.data.annotations.push({id:'table-comment', author:'Reader', text:'Keep table review',
          status:'open', replies:[], target:{chapter:'one',quote:'Reviewable text.',start:0,end:16}});
        obsComments.data.reviews.push({chapter:'one',item:'item-1',reviewer:'Reader',state:'accepted'});
    }""")
    second = tmp_path / "reviewed-twice.html"
    _save(page, second)
    page.goto(second.as_uri() + "#one")
    assert _columns(table) == ["explanation", "title"]
    assert table.locator("colgroup col").first.evaluate("node => parseInt(node.style.width)") != width
    assert page.evaluate("obsComments.data.annotations[0].text") == "Keep table review"
    assert page.evaluate("obsComments.data.reviews[0].state") == "accepted"
    assert page.evaluate(
        "obsReport.records.find(record => record.slug === 'one').frontmatter.explanation",
    ) == "Edited after restoring columns"
    expect(guidance).to_have_attribute("data-dirty", "false")
    page.goto(report.as_uri() + "#one")
    assert _columns(table) == defaults
    expect(page.locator("[data-filter-input]")).to_have_value("")
    expect(guidance).to_have_attribute("data-dirty", "false")


@pytest.mark.parametrize("state", [
    None,
    [],
    {"columns": [], "widths": {}},
    {"columns": ["title", "title"], "widths": {}},
    {"columns": ["missing"], "widths": {}},
    {"columns": ["title"], "widths": []},
    {"columns": ["title"], "widths": {}, "rows": []},
])
def test_native_invalid_saved_table_columns_show_atomic_diagnostic(
    reviewed_table_page, tmp_path, state,
):
    from playwright.sync_api import expect

    page, report = reviewed_table_page
    html = report.read_text(encoding="utf-8")
    pattern = r'(<script[^>]*data-report-data[^>]*>)(.*?)(</script>)'
    model = decode_report_data(html)
    model["readerState"] = {"tables": {"one-base-1": state}}
    invalid = tmp_path / "invalid-table-state.html"
    invalid.write_text(
        re.sub(pattern, lambda match: encode_report_data(model), html, count=1, flags=re.S),
        encoding="utf-8",
    )
    page.goto(invalid.as_uri() + "#one")
    table = page.locator('.chapter-scroll [data-data-table="one-base-1"]')
    expect(table.locator("[data-table-presentation-error]")).to_contain_text("Saved table presentation")
    expect(table.locator("[data-table-presentation-error]")).to_be_visible()
    assert _columns(table) == ["title", "status", "explanation"]
    other = page.locator('.chapter-scroll [data-data-table="one-base-2"]')
    assert _columns(other) == ["title", "status", "explanation"]
    expect(page.locator("[data-review-save-guidance]")).to_have_attribute("data-dirty", "false")


def test_native_hidden_column_and_unvisited_table_state_survive(reviewed_table_page, tmp_path):
    from playwright.sync_api import expect

    page, report = reviewed_table_page
    page.goto(report.as_uri() + "#one")
    page.evaluate("obsPages.setPaged(false)")
    one = page.locator('.chapter-scroll [data-data-table="one-base-1"]')
    one.locator(".data-table-options-toggle").scroll_into_view_if_needed()
    one.locator(".data-table-options-toggle").click()
    one.get_by_role("button", name="Properties", exact=True).click()
    one.locator('button[title="Hide title"]').click()
    page.keyboard.press("Escape")
    assert _columns(one) == ["status", "explanation"]
    page.evaluate("obsReport.activateChapter('two')")
    two = page.locator('.chapter-scroll [data-data-table="two-base-1"]')
    two.locator('th[data-column-key="title"]').press("Alt+ArrowRight")
    saved = tmp_path / "two-tables.html"
    _save(page, saved)
    page.goto(saved.as_uri() + "#two")
    second = tmp_path / "resaved-without-visiting-one.html"
    _save(page, second)
    page.goto(second.as_uri() + "#one")
    assert _columns(one) == ["status", "explanation"]
    one.locator(".data-table-options-toggle").scroll_into_view_if_needed()
    one.locator(".data-table-options-toggle").click()
    one.get_by_role("button", name="Properties", exact=True).click()
    one.locator('button[title="Show title"]').click()
    page.keyboard.press("Escape")
    one.locator('th[data-column-key="title"]').press("Alt+ArrowLeft")
    one.locator('th[data-column-key="title"]').press("Alt+ArrowLeft")
    expect(page.locator("[data-review-save-guidance]")).to_have_attribute("data-dirty", "false")
    assert set(page.evaluate("JSON.parse(obsReport.serializeModel()).readerState.tables")) == {
        "one-base-1", "two-base-1",
    }


@pytest.mark.parametrize("tables", [
    {"missing-table": {"columns": ["title"], "widths": {}}},
    {"columns": ["title"], "widths": {}},
])
def test_native_invalid_saved_table_presentation_can_be_corrected(reviewed_table_page, tmp_path, tables):
    from playwright.sync_api import expect

    page, report = reviewed_table_page
    html = report.read_text(encoding="utf-8")
    pattern = r'(<script[^>]*data-report-data[^>]*>)(.*?)(</script>)'
    model = decode_report_data(html)
    model["readerState"] = {"tables": tables}
    invalid = tmp_path / "unknown-table.html"
    invalid.write_text(
        re.sub(pattern, lambda match: encode_report_data(model), html, count=1, flags=re.S),
        encoding="utf-8",
    )
    page.goto(invalid.as_uri() + "#one")
    table = page.locator('.chapter-scroll [data-data-table="one-base-1"]')
    expect(table.locator("[data-table-presentation-error]")).to_be_visible()
    table.locator('th[data-column-key="title"] .data-table-column-resize').press("ArrowRight")
    expect(table.locator("[data-table-presentation-error]")).to_be_visible()
    table.locator('th[data-column-key="title"]').press("Alt+ArrowRight")
    expect(table.locator("[data-table-presentation-error]")).to_be_hidden()
    state = page.evaluate("JSON.parse(obsReport.serializeModel()).readerState.tables['one-base-1']")
    assert state == {"columns": ["status", "title", "explanation"]}
    expect(page.locator("[data-review-save-guidance]")).to_have_attribute("data-dirty", "false")

def test_native_columns_size_from_content_and_resize_is_session_only(reviewed_table_page):
    from playwright.sync_api import expect

    page, report = reviewed_table_page
    page.goto(report.as_uri() + "#one")
    page.evaluate("obsPages.setPaged(false)")
    result = page.evaluate("""async () => {
        const host = document.createElement('div');
        host.style.width = '520px';
        document.querySelector('[data-chapter-body]').prepend(host);
        const prose = 'Long prose that must wrap inside the remaining width of this narrow table. '.repeat(4);
        const rows = ['AB-1', 'ABCDEF-123456', 'XY-77'].map(id => ({key: id, values: {id, text: prose}}));
        const {element} = obsDataTable.render({
            key: 'sizing', columns: [{key: 'id', label: 'ID'}, {key: 'text', label: 'Text'}],
            rows, pagination: false, initialPageSize: 2,
        });
        host.append(element);
        await new Promise(resolve => setTimeout(resolve, 300));
        const cells = [...element.querySelectorAll('tbody tr[data-row-key]')].map(row => row.children);
        const lines = cell => {
            const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
            const bottoms = new Set();
            while (walker.nextNode()) {
                const range = document.createRange();
                range.selectNodeContents(walker.currentNode);
                [...range.getClientRects()].filter(rect => rect.width)
                    .forEach(rect => bottoms.add(Math.round(rect.bottom)));
            }
            return bottoms.size;
        };
        return {
            idLines: cells.map(cell => lines(cell[0])),
            textLines: lines(cells[0][1]),
            idOverflow: cells.some(cell => cell[0].scrollWidth > cell[0].clientWidth),
            tableWidth: element.querySelector('table').getBoundingClientRect().width,
            scroller: element.querySelector('.data-table-scroll').scrollWidth <=
                element.querySelector('.data-table-scroll').clientWidth,
        };
    }""")
    # Every row is measured, including the page-two row with the longest id.
    assert result["idLines"] == [1, 1, 1]
    assert not result["idOverflow"]
    assert result["textLines"] > 1
    assert result["scroller"]
    table = page.locator('.chapter-scroll [data-data-table="one-base-1"]')
    table.locator('th[data-column-key="title"] .data-table-column-resize').press("ArrowRight")
    expect(page.locator("[data-document-warning]")).to_be_hidden()
    expect(page.locator("[data-review-save-guidance]")).to_have_attribute("data-dirty", "false")
    assert page.evaluate("obsReport.readerState().tables") == {}
