"""Fitted tables never scroll horizontally; small tables hide their pagination controls.

Owner: adapters/html/spec/generic-tables.md (column sizing, pagination).
"""
import os

import pytest

from obs_html_interim.cli import main
from test_reader_controls import _write_reader_artifact, reader_browser  # noqa: F401


@pytest.fixture(scope="module")
def table_document(tmp_path_factory):
    vault = tmp_path_factory.mktemp("table-fit") / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[one]]\n", encoding="utf-8")
    (vault / "one.md").write_text("# One\n\nHost chapter for injected tables.\n", encoding="utf-8")
    output = vault.parent / "document.html"
    assert main(["--source", str(vault), "--output", str(output)]) == 0
    return output


@pytest.fixture
def open_table_page(table_document):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for table layout checks.")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        errors = []

        def open_page(scale=1.0, zoom=1.0):
            context = browser.new_context(viewport={"width": 1400, "height": 900}, device_scale_factor=scale)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(table_document.as_uri() + "#one")
            page.evaluate("obsPages.setPaged(false)")
            # CSS zoom snaps borders to device pixels like browser zoom and display scaling do
            # (1px becomes 0.8px at 125%); device_scale_factor alone does not in headless Chrome.
            page.evaluate("zoom => { document.documentElement.style.zoom = String(zoom); }", zoom)
            page.evaluate(HELPERS)
            return page

        try:
            yield open_page
            assert errors == []
        finally:
            browser.close()


HELPERS = """() => {
    const settle = () => new Promise(resolve => requestAnimationFrame(() =>
        requestAnimationFrame(() => setTimeout(resolve, 20))));
    const prose = 'Long prose that must wrap inside the remaining width of the table. '.repeat(3);
    const variants = {
        keyValue: {
            columns: [{key: 'k', label: 'Metric'}, {key: 'v', label: 'Value'}],
            rows: ['Number of open points', 'Chapters', 'Figures', 'Tables']
                .map((k, i) => ({key: k, values: {k, v: String(i + 2)}})),
        },
        keyProse: {
            columns: [{key: 'k', label: 'Chapter'}, {key: 'v', label: 'Bottom line'}],
            rows: ['Product', 'Architecture', 'Quality'].map(k => ({key: k, values: {k, v: prose}})),
        },
        multi: {
            columns: ['Version', 'Date', 'Author', 'Change'].map(label => ({key: label, label})),
            rows: [1, 2].map(i => ({key: 'r' + i, values: {
                Version: '0.2.' + i, Date: '2026-10-29', Author: 'Some Author', Change: prose}})),
        },
        sharedProse: {
            columns: ['First', 'Second', 'Third'].map(label => ({key: label, label})),
            rows: [1, 2].map(i => ({key: 'r' + i, values: {First: prose, Second: prose, Third: prose}})),
        },
    };
    // Exact sub-pixel comparison: any table box past the scroller edge is scrollable overflow.
    const fit = (shell) => {
        const scroller = shell.querySelector('.data-table-scroll');
        const table = scroller.querySelector('table');
        const excess = table.getBoundingClientRect().right - scroller.getBoundingClientRect().right;
        return {excess, scrollWidth: scroller.scrollWidth, clientWidth: scroller.clientWidth,
            fits: excess <= 1 / 64 && scroller.scrollWidth <= scroller.clientWidth};
    };
    const mount = (name, width, options = {}) => {
        const host = document.createElement('div');
        host.style.width = typeof width === 'number' ? `${width}px` : width;
        document.querySelector('[data-chapter-body]').prepend(host);
        const {element} = obsDataTable.render({key: `fit-${name}-${Math.random()}`, ...variants[name],
            ...options});
        host.append(element);
        return {host, element};
    };
    globalThis.tableFit = {settle, variants, fit, mount};
}"""

FITTING_WIDTHS = [600.5, 601.6875, 601.25, 433.75, 377.9]


@pytest.mark.parametrize(("scale", "zoom"), [
    (1, 1), (1.25, 1), (1.5, 1), (1, 1.1), (1, 1.25), (1.5, 1.5),
])
def test_fitting_tables_never_overflow(open_table_page, scale, zoom):
    page = open_table_page(scale, zoom)
    failures = page.evaluate("""async (widths) => {
        const {settle, variants, fit, mount} = tableFit;
        const failures = [];
        for (const name of Object.keys(variants)) {
            for (const width of widths) {
                const {host, element} = mount(name, width);
                await settle();
                const result = fit(element);
                if (!result.fits) failures.push({name, width, ...result});
                host.remove();
            }
        }
        return failures;
    }""", FITTING_WIDTHS)
    assert failures == []


@pytest.mark.parametrize(("scale", "zoom"), [(1, 1), (1.25, 1), (1, 1.25)])
def test_fitted_table_still_fits_after_container_narrows(open_table_page, scale, zoom):
    page = open_table_page(scale, zoom)
    failures = page.evaluate("""async () => {
        const {settle, variants, fit, mount} = tableFit;
        const failures = [];
        for (const name of Object.keys(variants)) {
            const {host, element} = mount(name, 760);
            await settle();
            for (const width of [601.6875, 520.5, 433.75]) {
                host.style.width = `${width}px`;
                await settle();
                const settled = fit(element);
                if (!settled.fits) failures.push({name, width, ...settled});
            }
            host.remove();
        }
        return failures;
    }""")
    assert failures == []


def test_fitted_table_refits_when_fonts_finish_loading(open_table_page):
    page = open_table_page()
    result = page.evaluate("""async () => {
        const {settle, mount} = tableFit;
        const {element} = mount('keyValue', 601.6875);
        await settle();
        const before = [...element.querySelectorAll('col')].map(col => col.style.width);
        // A web font that finishes loading changes text metrics without resizing the container
        // or, for single-line cells with a fixed line height, the table.
        element.querySelector('table').style.fontFamily = '"Times New Roman", serif';
        document.fonts.dispatchEvent(new Event('loadingdone'));
        await settle();
        return {before, after: [...element.querySelectorAll('col')].map(col => col.style.width),
            fits: tableFit.fit(element).fits};
    }""")
    assert result["after"] != result["before"]
    assert result["fits"]


def test_genuinely_wide_table_still_scrolls(open_table_page):
    page = open_table_page()
    result = page.evaluate("""async () => {
        const {settle} = tableFit;
        const host = document.createElement('div');
        host.style.width = '320.5px';
        document.querySelector('[data-chapter-body]').prepend(host);
        const labels = ['Requirement identifier', 'Verification method', 'Responsible owner',
            'Acceptance evidence'];
        const {element} = obsDataTable.render({key: 'wide', columns: labels.map(label => ({key: label, label})),
            rows: [{key: 'one', values: Object.fromEntries(labels.map(label => [label, 'value']))}]});
        host.append(element);
        await settle();
        const scroller = element.querySelector('.data-table-scroll');
        scroller.scrollLeft = 100;
        return {scrollWidth: scroller.scrollWidth, clientWidth: scroller.clientWidth,
            scrollLeft: scroller.scrollLeft};
    }""")
    assert result["scrollWidth"] > result["clientWidth"] + 50
    assert result["scrollLeft"] > 0


def _footer(page, rows, filter_expression=""):
    return page.evaluate("""async ({rows, filterExpression}) => {
        const {settle} = tableFit;
        const host = document.createElement('div');
        document.querySelector('[data-chapter-body]').prepend(host);
        const table = obsDataTable.render({key: `pages-${rows}-${Math.random()}`,
            columns: [{key: 'name', label: 'Name'}],
            rows: Array.from({length: rows}, (_value, index) => ({key: `r${index}`, values: {name: `Row ${index}`},
                fields: {name: `Row ${index}`}, haystack: `Row ${index}`})),
        });
        host.append(table.element);
        if (filterExpression) table.setExpression(filterExpression);
        await settle();
        const visible = node => Boolean(node && node.getClientRects().length);
        const footer = table.element.querySelector('.data-table-footer');
        return {
            count: visible(footer.querySelector('.data-table-count')),
            countText: footer.querySelector('.data-table-count').textContent,
            pageSize: visible(footer.querySelector('.data-table-page-size')),
            page: visible(footer.querySelector('.data-table-page')),
            arrows: [...footer.querySelectorAll('.data-table-page-button')].map(visible),
        };
    }""", {"rows": rows, "filterExpression": filter_expression})


def test_single_page_table_hides_pagination_controls(open_table_page):
    page = open_table_page()
    small = _footer(page, 3)
    assert small["count"] and small["countText"] == "3 of 3 items"
    assert not small["pageSize"] and not small["page"] and not any(small["arrows"])
    exact = _footer(page, 20)
    assert not exact["pageSize"] and not exact["page"] and not any(exact["arrows"])


def test_multi_page_and_filter_shrunk_tables_keep_pagination_controls(open_table_page):
    page = open_table_page()
    large = _footer(page, 50)
    assert large["count"] and large["pageSize"] and large["page"] and all(large["arrows"])
    filtered = _footer(page, 50, 'name: /^Row 7$/')
    assert filtered["countText"] == "1 of 50 items"
    assert filtered["pageSize"] and filtered["page"] and all(filtered["arrows"])


def test_enlarged_page_size_keeps_pagination_controls(open_table_page):
    page = open_table_page()
    result = page.evaluate("""async () => {
        const {settle} = tableFit;
        const host = document.createElement('div');
        document.querySelector('[data-chapter-body]').prepend(host);
        const table = obsDataTable.render({key: 'enlarged', columns: [{key: 'name', label: 'Name'}],
            rows: Array.from({length: 30}, (_value, index) => ({key: `r${index}`, values: {name: `Row ${index}`}}))});
        host.append(table.element);
        const size = table.element.querySelector('.data-table-page-size input');
        size.value = '100';
        size.dispatchEvent(new Event('change'));
        await settle();
        return Boolean(size.getClientRects().length);
    }""")
    assert result


@pytest.mark.parametrize("width", [1500, 390])
@pytest.mark.parametrize("paged", [False, True])
def test_native_compact_table_fits_and_resizes_without_masking(tmp_path, reader_browser, width, paged):
    from playwright.sync_api import expect

    def compact(spec):
        spec["views"][0]["obsHtml"]["compact"] = True
        spec["properties"]["subject"]["displayName"] = ""
        spec["properties"]["actions"]["obsHtml"]["icons"].append(
            {"name": "replace", "label": "Import replacement", "help": "Choose replacement evidence."})

    output = _write_reader_artifact(tmp_path, compact)
    page = reader_browser.new_page(viewport={"width": width, "height": 1000})
    try:
        page.goto(output.as_uri())
        page.evaluate("paged=>{obsPages.setPaged(paged);obsArtifact.activateChapter('chapter')}", paged)
        table = page.locator("[data-active-chapter] [data-data-table='chapter-base-1']")
        expect(table).to_have_attribute("data-compact", "true")
        # Match the user's narrow card, independently of the wider matrix fixture.
        table.evaluate("node=>{node.style.maxWidth='260px';node.style.width='100%'}")
        page.wait_for_timeout(100)
        def fits():
            return table.evaluate("""node => {
                const scroll=node.querySelector('.data-table-scroll'),bounds=scroll.getBoundingClientRect();
                return scroll.scrollWidth<=scroll.clientWidth &&
                    [...node.querySelectorAll('thead button,thead [role=separator],tbody tr:first-child .data-table-icon-action')]
                    .every(control=>{const r=control.getBoundingClientRect();
                        return r.left>=bounds.left-1 && r.right<=bounds.right+1;});
            }""")
        assert fits()
        handle = table.get_by_role("separator").first
        handle.press("ArrowLeft")
        assert fits()
        bounds = handle.bounding_box()
        page.mouse.move(bounds["x"] + bounds["width"]/2, bounds["y"] + bounds["height"]/2)
        page.mouse.down()
        page.mouse.move(bounds["x"] + bounds["width"]/2 + 10, bounds["y"] + bounds["height"]/2)
        page.mouse.up()
        assert fits()
        table.locator(".data-table-options-toggle").click()
        expect(table.locator(".data-table-options")).to_be_visible()
    finally:
        page.close()
