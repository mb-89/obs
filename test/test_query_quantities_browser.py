import json
import os

import pytest

from obs_html.content import parse_manifest
from obs_html.renderer import render_report


def test_native_quantity_selection_chain_cache_edit_print_and_reopen(tmp_path):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native checks.")
    from playwright.sync_api import sync_playwright, expect

    (tmp_path / "counts").mkdir()
    for name, alias, query in [
        ("total", "serviceCount", {"where": [{"field": "kind", "equals": "service"}], "distinct": "identity"}),
        ("subset", "activeCount", {"from": "counts/total",
                                  "where": [{"field": "active", "equals": "yes"}], "distinct": "identity"}),
    ]:
        (tmp_path / "counts" / f"{name}.md").write_text("---\n" + json.dumps({
            "kind": "quantity", "aliases": [alias], "query": query, "source": "[[chapter]]",
        }) + "\n---\n# Quantity\n", encoding="utf-8")
    (tmp_path / "limit.md").write_text(
        '---\nkind: quantity\nvalue: 20\nunit: mm\naliases: [staticLimit]\n'
        'source: "[[chapter]]"\n---\n# Limit\n', encoding="utf-8")
    card = {"version": 1, "cards": [{
        "title": "Operations", "body": "Items [[serviceCount]] ([[activeCount]] active).",
        "metrics": [
            {"label": "Same selection", "from": "counts/total", "where": [], "distinct": "identity"},
            {"label": "Active share", "from": "counts/total",
             "where": [{"field": "active", "equals": "yes"}], "distinct": "identity", "denominator": []},
        ],
    }]}
    (tmp_path / "manifest.md").write_text("---\n" + json.dumps({"obsHtml": {"query": {
        "scope": "records", "where": [{"field": "kind", "equals": "service"}],
    }}}) + "\n---\n- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "chapter.md").write_text(
        "# Operations\n\n```cards\n" + json.dumps(card) + "\n```\n\n"
        "Limit [[staticLimit]], explicit [[serviceCount|services]].\n"
        "```base\nfilters: 'kind == \"service\"'\nviews:\n - type: table\n   order: [identity, active]\n```\n",
        encoding="utf-8")
    for name, identity, active in [("one", "a", "yes"), ("two", "b", "no"), ("three", "a", "yes")]:
        (tmp_path / f"{name}.md").write_text("---\n" + json.dumps({
            "kind": "service", "identity": identity, "active": active,
        }) + "\n---\n", encoding="utf-8")
    (tmp_path / "other.md").write_text(
        '---\nkind: operator\nidentity: z\n---\n', encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    output = tmp_path / "reader.html"
    output.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(output.as_uri())
        page.evaluate("obsPages.setPaged(false); obsReport.activateChapter('chapter')")
        summary = page.locator("[data-active-chapter] .record-card p")
        expect(summary).to_have_text("Items 2 (1 active).")
        expect(page.locator("[data-active-chapter] .record-metric strong")).to_have_text(["2", "50.0%"])
        expect(page.locator("[data-active-chapter] a").filter(has_text="20 mm")).to_have_count(1)
        expect(page.locator("[data-active-chapter] a").filter(has_text="services")).to_have_count(1)
        assert page.evaluate("""() => obsRecordMetrics.select({from:'counts/total', where:[]})
            .every(record => obsReport.records.includes(record))""")
        page.evaluate("""() => {
            window.aggregatePopulationPasses = 0;
            const previous = obsReport.matchesFilter;
            obsReport.matchesFilter = record => {aggregatePopulationPasses++; return previous(record);};
            const clone = document.querySelector('[data-quantity-reference]').cloneNode(true);
            clone.dataset.transientView = '';
            clone.id = 'cached-quantity-clone';
            document.body.append(clone);
            document.dispatchEvent(new CustomEvent('obs-chapter-change'));
        }""")
        expect(page.locator("#cached-quantity-clone")).to_have_text("2")
        assert page.evaluate("aggregatePopulationPasses") == 0
        before_filter = page.evaluate("JSON.stringify(obsReport.canonicalNotes())")
        before_revision = page.evaluate("obsReport.revision")
        page.evaluate("obsReport.setFilter(obsQuery.compile('identity:b'))")
        expect(summary).to_have_text("Items 1 (0 active).")
        assert page.evaluate("JSON.stringify(obsReport.canonicalNotes())") == before_filter
        assert page.evaluate("obsReport.revision") == before_revision
        page.evaluate("obsReport.commitCanonicalProjection([{slug:'two', fields:{active:'yes'}}])")
        expect(summary).to_have_text("Items 1 (1 active).")
        page.evaluate("obsReport.setFilter(obsQuery.compile('identity:missing'))")
        expect(summary).to_have_text("Items 0 (0 active).")
        page.evaluate("obsReport.setFilter(obsQuery.compile('identity:b')); obsPages.setPaged(true)")
        page.wait_for_function("""() => [...document.querySelectorAll('.paged-reader [data-quantity-reference]')]
            .length > 0 && [...document.querySelectorAll('.paged-reader [data-quantity-reference]')]
            .every(link => link.textContent === '1')""")
        saved = tmp_path / "reviewed.html"
        saved.write_text(page.evaluate("obsComments.reviewedHtml()"), encoding="utf-8")
        page.goto(saved.as_uri())
        page.evaluate("obsPages.setPaged(false); obsReport.activateChapter('chapter')")
        expect(page.locator("[data-active-chapter] .record-card p")).to_have_text("Items 1 (1 active).")
        assert page.evaluate("""() => obsReport.canonicalNotes().filter(note =>
            note.frontmatter.kind === 'quantity' && note.frontmatter.query)
            .every(note => !Object.hasOwn(note.frontmatter, 'value'))""")
        assert errors == []
        browser.close()
