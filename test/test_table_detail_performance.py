import json

import yaml

from obs_html.content import parse_manifest
from obs_html.renderer import render_report
from test_reader_controls import _write_reader_fixture, reader_browser


def instrument_detail_passes(html):
    replacements = {
        "const tableDefinition = (table, staticView = false) => {":
            "const tableDefinition = (table, staticView = false) => {"
            " window.detailPasses.tableQueries++;",
        "const refreshQueryFields = () => records.forEach":
            "const refreshQueryFields = () => "
            "(window.detailPasses.canonicalPasses++, records).forEach",
        "const syncReviewFields = () => {":
            "const syncReviewFields = () => { window.detailPasses.allReviewPasses++;",
        "const updateReviewMode = () => {":
            "const updateReviewMode = () => { window.detailPasses.reviewModePasses++;",
        "renderDetails: (row, container, columnKey) => {":
            "renderDetails: (row, container, columnKey) => {"
            " window.detailPasses.detailPreparations++;",
    }
    for before, after in replacements.items():
        assert html.count(before) == 1, before
        html = html.replace(before, after)
    return html


COUNTERS = """window.detailPasses = {
    tableQueries: 0, canonicalPasses: 0, allReviewPasses: 0,
    reviewModePasses: 0, detailPreparations: 0, staticRenders: 0
};"""


def test_native_detail_interactions_are_row_local_and_revision_bound(tmp_path, reader_browser):
    manifest = _write_reader_fixture(tmp_path)
    chapter = tmp_path / "chapter.md"
    text = chapter.read_text(encoding="utf-8")
    definition_text = text.split("```base\n", 1)[1].split("```", 1)[0]
    definition = yaml.safe_load(definition_text)
    definition["properties"]["subject"]["obsHtml"]["reference"]["metadata"].append("status")
    definition["properties"]["peer"] = {
        "displayName": "Peer",
        "obsHtml": {"detail": True, "reference": {
            "label": ["item.name"], "metadata": ["item.name"],
        }},
    }
    definition["views"][0]["order"].insert(1, "peer")
    chapter.write_text(text.replace(definition_text, yaml.safe_dump(definition)), encoding="utf-8")
    for note in tmp_path.glob("relation-*.md"):
        note.write_text(note.read_text(encoding="utf-8").replace(
            "kind: relation\n", "kind: relation\npeer: '[[peer]]'\n",
        ), encoding="utf-8")
    (tmp_path / "peer.md").write_text(
        "---\nitem:\n  name: Second subject\n---\n\n"
        + "\n\n".join(f"Peer paragraph {index}." for index in range(12)),
        encoding="utf-8",
    )
    subject = tmp_path / "subject.md"
    subject.write_text(subject.read_text(encoding="utf-8").replace(
        "kind: subject\n", "kind: subject\nstatus: initial\n",
    ), encoding="utf-8")
    report = tmp_path / "detail-interactions.html"
    report.write_text(instrument_detail_passes(render_report(
        manifest, parse_manifest(manifest),
    )), encoding="utf-8")
    page = reader_browser.new_page(viewport={"width": 1280, "height": 900})
    page.add_init_script(COUNTERS)
    page.goto(report.as_uri())
    page.evaluate("obsReport.activateChapter('chapter')")
    page.locator("[data-pages-toggle]").check()
    page.evaluate("""() => {
        obsReport.openBar('comments', 'right');
        document.querySelector('[data-comment-author]').value = 'Performance reviewer';
        document.querySelector('[data-row-key="note:relation-000"] .review-action--accept').click();
        document.querySelector('[data-data-table="chapter-base-1"]').dispatchEvent(
            new CustomEvent('obs-table-set-filter', {detail: {expression: 'status:Complete'}}),
        );
    }""")
    page.evaluate("""() => {
        const renderStatic = obsReport.renderStatic;
        obsReport.renderStatic = (...args) => {
            detailPasses.staticRenders++;
            return renderStatic(...args);
        };
        Object.keys(detailPasses).forEach(key => detailPasses[key] = 0);
        window.originalRow = document.querySelector('[data-row-key="note:relation-000"]');
        window.unrelatedRow = document.querySelector('[data-row-key="note:relation-002"]');
        window.originalGutter = originalRow.querySelector('[data-review-gutter]');
        originalRow.querySelector('.data-table-tree-toggle').click();
    }""")
    opening = page.evaluate("({...detailPasses})")
    result = page.evaluate("""() => {
        Object.keys(detailPasses).forEach(key => detailPasses[key] = 0);
        const content = document.querySelector('.data-table-detail-content');
        const panels = [...content.querySelectorAll(':scope > .data-table-detail-panels > section')];
        const buttons = [...content.querySelectorAll(':scope > [role=tablist] > button')];
        const editor = document.createElement('input');
        editor.value = 'unsaved editor draft';
        panels[0].append(editor);
        const heights = [];
        for (let index = 0; index < 12; index++) {
            buttons[index % buttons.length].click();
            heights.push(content.getBoundingClientRect().height);
        }
        window.savedPanel = panels[0];
        const row = document.querySelector('[data-row-key="note:relation-000"]');
        return {
            passes: {...detailPasses},
            sameOwner: originalRow === row,
            sameUnrelated: unrelatedRow === document.querySelector('[data-row-key="note:relation-002"]'),
            samePanel: panels[0].isConnected && panels[0].contains(editor),
            sameGutter: originalGutter.isConnected &&
                originalGutter === row.querySelector('[data-review-gutter]'),
            reviewState: row.dataset.reviewState,
            detailReviewState: row.nextElementSibling.dataset.reviewOwnerState,
            filter: row.closest('[data-data-table]').querySelector('.data-table-filter').value,
            draft: editor.value,
            heights
        };
    }""")
    (tmp_path / "detail-interactions.json").write_text(
        json.dumps({"opening": opening, "switching": result}, indent=2), encoding="utf-8",
    )
    for key in ("tableQueries", "canonicalPasses", "allReviewPasses", "staticRenders"):
        assert opening[key] == 0, (key, opening)
        assert result["passes"][key] == 0, (key, result)
    assert result["passes"]["reviewModePasses"] == 0
    assert opening["reviewModePasses"] == 0
    assert result["passes"]["detailPreparations"] == 0
    assert result["sameOwner"] and result["sameUnrelated"] and result["samePanel"]
    assert result["draft"] == "unsaved editor draft"
    assert result["sameGutter"]
    assert result["reviewState"] == result["detailReviewState"] == "accepted"
    assert result["filter"] == "status:Complete"
    assert max(result["heights"]) - min(result["heights"]) <= 1
    page.evaluate("""() => {
        const toggle = document.querySelector('[data-row-key="note:relation-000"] .data-table-tree-toggle');
        toggle.click();
        toggle.click();
    }""")
    assert page.evaluate("savedPanel.isConnected")
    page.evaluate("""obsReport.commitCanonicalProjection([{
        slug: 'subject', fields: {status: 'Changed canonical subject'}
    }])""")
    assert not page.evaluate("savedPanel.isConnected")
    assert page.get_by_role("tab", name="Peer", exact=True).get_attribute("aria-selected") == "true"
    page.get_by_role("tab", name="Subject", exact=True).click()
    assert "Changed canonical subject" in page.locator(
        '.data-table-detail-content [data-reference-note="subject"]',
    ).inner_text()
    page.close()


def test_native_pagination_renders_only_current_page_cells(tmp_path, reader_browser):
    manifest = _write_reader_fixture(tmp_path)
    report = tmp_path / "paged-cells.html"
    report.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    page = reader_browser.new_page()
    try:
        page.goto(report.as_uri())
        # Column sizing measures every base row once in detached probes (generic-tables.md);
        # only the current page's rows are rendered as table cells.
        assert page.evaluate("""() => {
            let measured = 0, placed = 0, details = 0;
            const rows = Array.from({length:60}, (_,index) => ({
                key:String(index), values:{id:String(index)}, fields:{id:String(index)}}));
            const table = obsDataTable.render({key:'lazy-cells', rows, initialPageSize:20,
                hasDetails:() => {details++; return false;},
                columns:[{key:'id', label:'ID', render:(item,cell) => {
                    if (cell.closest('td')) placed++; else measured++;
                    cell.textContent=item.key;
                }}]});
            window.lazyCellFixture = table;
            if(details > 60) throw new Error(`Repeated detail availability passes: ${details}`);
            return {measured, placed, bodyCells: table.element.querySelectorAll('tbody td').length};
        }""") == {"measured": 60, "placed": 20, "bodyCells": 20}
    finally:
        page.close()
