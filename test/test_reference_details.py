import copy
import base64
import json
import os
from pathlib import Path

import pytest
import yaml

from obs_html.content import ContentError, parse_manifest, validate_base_definition
from obs_html.config import load_config
from obs_html.cli import main
from obs_html.renderer import render_report
from test_browser import run_browser_script


def reference_definition():
    return {
        "filters": 'kind == "relation"',
        "properties": {
            "roles.left": {
                "displayName": "Requirement",
                "obsHtml": {"reference": {"label": ["item.id", "item.name"], "metadata": ["item"]}, "detail": True},
            },
            "roles.right": {
                "displayName": "Evidence",
                "obsHtml": {"reference": {"label": ["item.id", "item.name"], "metadata": ["item"]}, "detail": True},
            },
            "statusGroup": {"displayName": "Status"},
            "snapshot": {"displayName": "Snapshot", "obsHtml": {"icon": {
                "name": "download", "label": "Download snapshot",
                "linkProperty": "document", "unavailable": "No snapshot available",
            }}},
            "upload": {"displayName": "Recalculate", "obsHtml": {"icon": {
                "name": "upload", "label": "Recalculate evidence",
                "unavailable": "Recalculation is unavailable in this report",
            }}},
            "help": {"displayName": "Help", "obsHtml": {"icon": {
                "name": "help", "label": "Evidence help", "helpProperty": "reproduce",
                "help": "Upload is unavailable.",
            }}},
            "source": {"displayName": "Source", "obsHtml": {"icon": {
                "name": "source", "label": "Download original source", "action": "sourceArchive",
            }}},
        },
        "views": [{
            "type": "table",
            "order": ["roles.left", "roles.right", "snapshot", "upload", "help", "source"],
            "groupBy": {"property": "statusGroup"},
            "obsHtml": {"details": "columns", "wide": True},
        }],
    }


def test_reference_detail_and_icon_schema_matches_browser():
    valid = reference_definition()
    validate_base_definition(valid, Path("example.md"))
    trusted_action = copy.deepcopy(valid)
    trusted_action["properties"]["upload"]["obsHtml"]["icon"] = {
        "name": "evidence.replace", "label": "Replace evidence", "action": "replaceEvidence",
    }
    validate_base_definition(trusted_action, Path("example.md"))
    invalid = []
    for field, declaration in [
        ("roles.left", {"reference": {"label": []}}),
        ("roles.left", {"reference": {"label": ["item.id", "item.id"]}}),
        ("roles.left", {"reference": {"label": ["item.id"], "metadata": []}}),
        ("roles.left", {"reference": {"label": ["item.id"]}, "detail": "yes"}),
        ("snapshot", {"icon": {"name": "download", "label": "Download"}}),
        ("snapshot", {"icon": {"name": "download", "label": "Download",
                               "linkProperty": "document"}}),
        ("upload", {"icon": {"name": "upload", "label": "Upload", "action": "upload()"}}),
        ("help", {"icon": {"name": "help", "label": "Help", "help": "x",
                           "unavailable": "missing"}}),
    ]:
        definition = copy.deepcopy(valid)
        definition["properties"][field]["obsHtml"] = declaration
        invalid.append(definition)
    for option in [{"wide": "true"}, {"details": "notes"}, {"unknown": True}]:
        definition = copy.deepcopy(valid)
        definition["views"][0]["obsHtml"] = option
        invalid.append(definition)
    for definition in invalid:
        with pytest.raises(ContentError, match="Invalid base definition"):
            validate_base_definition(definition, Path("example.md"))
    run_browser_script("""
        context.obsBases.validate(payload.valid);
        context.obsBases.validate(payload.trustedAction);
        for (const definition of payload.invalid) {
            assert.throws(() => context.obsBases.validate(definition));
        }
        assert.deepEqual(JSON.parse(JSON.stringify(context.obsBases.parse(
            context.obsBases.dump(payload.valid)))), payload.valid);
    """, {"valid": valid, "trustedAction": trusted_action, "invalid": invalid})


def test_icon_width_has_one_configured_owner(tmp_path):
    from jsonschema import ValidationError

    config = Path(__file__).parents[1] / "src" / "obs_html" / "cfg.json"
    override = tmp_path / "cfg.json"
    override.write_text('{"report":{"tableIconWidthPixels":40}}', encoding="utf-8")
    assert load_config(config, override).table_icon_width_pixels == 40
    override.write_text('{"report":{"tableIconWidthPixels":0}}', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(config, override)


def test_canonical_record_values_traverse_nested_arrays_without_copies():
    run_browser_script("""
        const note = {sourcePath:'items/42.md',title:'Subject',frontmatter:{
            item:{id:42,links:[{target:{id:'A'}},{target:{id:'B'}}],flags:[false,true]},
        }};
        assert.equal(context.obsBases.recordValue(note,'file.name'),'42');
        assert.equal(context.obsBases.recordValue(note,'title'),undefined,
            'title is ordinary frontmatter, not a synthesized display title');
        assert.equal(context.obsBases.recordValue(note,'item.id'),42);
        assert.equal(context.obsBases.recordValue(note,'item.flags'),note.frontmatter.item.flags);
        assert.equal(JSON.stringify(context.obsBases.recordValue(note,'item.links.target.id')),
            JSON.stringify(['A','B']));
        assert.equal(context.obsBases.recordValue(note,'absent.field'),undefined);
    """)


def write_reference_fixture(root):
    root.mkdir(exist_ok=True, parents=True)
    (root / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (root / "chapter.md").write_text(
        "# Relations\n\n```base\n" + yaml.safe_dump(reference_definition(), sort_keys=False) +
        "```\n\n```base\nfilters: 'kind == \"subject\"'\nviews:\n"
        "  - type: table\n    order: [title]\n```\n", encoding="utf-8",
    )
    (root / "left.md").write_text(
        "---\ntitle: Canonical subject\nkind: subject\n"
        "item:\n  id: REQ-42\n  name: The full and meaningful subject title\n"
        "  description: 'A **rich** requirement with [[right|source evidence]].'\n"
        "explanation: Original review\n---\n"
        "# Subject body\n\nUnique canonical requirement text.\n\n"
        "```property-editor\nversion: 1\nfield: explanation\nlabel: Explanation\n```\n\n"
        "```base\nfilters: 'kind == \"support\"'\nviews:\n"
        "  - type: table\n    order: [title]\n```\n", encoding="utf-8",
    )
    (root / "right.md").write_text(
        "---\ntitle: Canonical evidence\nkind: support\n"
        "item:\n  id: EVD-7\n  name: Original evidence item\n---\n"
        "# Evidence body\n\nEvidence kept once.\n", encoding="utf-8",
    )
    for slug, right, document in [
        ("relation", "'[[right]]'", "'[Snapshot](https://example.org/evidence.pdf)'"),
        ("missing", "null", "null"),
    ]:
        (root / f"{slug}.md").write_text(
            "---\nkind: relation\nstatusGroup: Covered\nroles:\n"
            f"  left: '[[left]]'\n  right: {right}\ndocument: {document}\n"
            "reproduce: Keep the original evidence.\n"
            "pathHash: should-not-be-a-subject\nexplanation: Owner explanation\n---\n"
            "```property-editor\nversion: 1\nfield: explanation\nlabel: Relation explanation\n```\n",
            encoding="utf-8",
        )
    return root / "manifest.md"


@pytest.fixture(scope="module")
def reference_native_browser():
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native reference checks.")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        yield browser
        browser.close()


@pytest.mark.parametrize("paged", [False, True])
def test_native_comment_target_waits_for_lazy_table_mount(
    tmp_path, reference_native_browser, paged,
):
    from playwright.sync_api import expect

    manifest = write_reference_fixture(tmp_path)
    output = tmp_path / "report.html"
    output.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    page = reference_native_browser.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(output.as_uri())
        page.evaluate("""() => obsComments.data.annotations.push({
            id:'lazy-target',author:'Reader',text:'Keep canonical subject',status:'open',replies:[],
            target:{chapter:'chapter',table:'chapter-base-1',row:'note:relation',detail:true,
                    column:'roles.left',quote:'Unique canonical requirement text.',start:0,end:34}
        })""")
        saved = tmp_path / "reviewed.html"
        saved.write_text(page.evaluate("obsComments.reviewedHtml()"), encoding="utf-8")
        page.goto(saved.as_uri())
        page.evaluate("paged => obsPages.setPaged(paged)", paged)
        page.evaluate("obsReport.openBar('comments')")
        assert page.locator('[data-data-table="chapter-base-1"]').count() == 0
        page.locator(".comment-target").click()
        detail = page.locator(
            '[data-chapter-body] [data-data-table="chapter-base-1"] '
            '[data-detail-owner="note:relation"]')
        expect(detail.get_by_role("tab", name="Requirement", exact=True)).to_have_attribute(
            "aria-selected", "true")
        expect(detail).to_contain_text("Unique canonical requirement text.")
        assert errors == []
    finally:
        page.close()


def test_native_canonical_reference_tabs_icons_and_reviewed_reopen(tmp_path, reference_native_browser):
    from playwright.sync_api import expect

    manifest = write_reference_fixture(tmp_path)
    output = tmp_path / "report.html"
    output.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    context = reference_native_browser.new_context(accept_downloads=True)
    context.add_init_script("delete window.showSaveFilePicker")
    page = context.new_page()
    page.set_default_timeout(6000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(output.as_uri() + "#chapter")
    page.evaluate("obsPages.setPaged(false); obsReport.activateChapter('chapter')")
    table = page.locator('[data-active-chapter] [data-data-table="chapter-base-1"]')
    expect(table).to_have_attribute("data-table-wide", "true")
    expect(table.locator("thead th").first).to_contain_text("Requirement")
    expect(table.locator('thead th[data-column-key="source"] .data-table-options-toggle')).to_have_count(1)
    expect(table.locator(".data-table-footer")).to_be_visible()
    expect(table.locator(".data-table-group-row")).to_contain_text("Status: Covered")
    row = table.locator('[data-row-key="note:relation"]')
    reference = row.get_by_role("link", name="REQ-42 — The full and meaningful subject title", exact=True)
    expect(reference).to_have_attribute("href", "#left")
    reference.click()
    expect(page.locator("[data-active-chapter]")).to_have_attribute("data-chapter", "chapter")
    expect(table.locator('[data-detail-owner="note:relation"] [data-reference-note="left"]')).to_have_count(1)
    row.locator(".data-table-tree-toggle").click()
    expect(row.get_by_role("link", name="Download snapshot", exact=True)).to_have_attribute(
        "href", "https://example.org/evidence.pdf",
    )
    expect(table.locator('[data-row-key="note:missing"]').get_by_role(
        "button", name="Download snapshot: No snapshot available", exact=True,
    )).to_be_disabled()
    expect(table.locator('[data-row-key="note:missing"]').get_by_role(
        "button", name="Download snapshot: No snapshot available", exact=True,
    ).locator('[data-icon][data-icon-state="inactive"]')).to_have_text(
        row.get_by_role("link", name="Download snapshot", exact=True).locator("[data-icon]").inner_text(),
    )
    expect(row.get_by_role("button", name="Recalculate evidence: Recalculation is unavailable in this report",
                           exact=True)).to_be_disabled()
    row.get_by_role("button", name="Evidence help", exact=True).click()
    help_card = page.locator("#hover-card")
    expect(help_card).to_be_visible()
    expect(help_card).to_contain_text("Keep the original evidence.")
    expect(help_card).to_contain_text("Upload is unavailable.")
    row.locator(".data-table-tree-toggle").click()
    detail = table.locator('[data-detail-owner="note:relation"]')
    expect(detail.get_by_role("tab", name="Requirement", exact=True)).to_have_attribute("aria-selected", "true")
    expect(detail).to_contain_text("Unique canonical requirement text.")
    expect(detail.locator("strong")).to_have_text("rich")
    expect(detail.get_by_role("tabpanel").locator("dt")).to_have_text(["id", "name", "description"])
    expect(detail.locator('a[href="#right"]')).to_have_text("source evidence")
    expect(detail.locator('[data-data-table="left-base-1"]')).to_be_visible()
    expect(detail).not_to_contain_text("should-not-be-a-subject")
    detail.get_by_role("tab", name="Requirement", exact=True).focus()
    page.keyboard.press("ArrowRight")
    expect(detail.get_by_role("tab", name="Evidence", exact=True)).to_be_focused()
    expect(detail.get_by_role("tabpanel")).to_contain_text("Evidence kept once.")
    expect(detail.locator('.data-table-owner-content [data-property-editor]')).to_have_value("Owner explanation")
    page.keyboard.press("Home")
    editor = detail.locator('[data-property-editor][data-property-note="left"]')
    editor.fill("Reviewed canonical subject")
    editor.press("Tab")
    detail = table.locator('[data-detail-owner="note:relation"]')
    expect(detail.locator('[data-property-editor][data-property-note="left"]')).to_have_value(
        "Reviewed canonical subject",
    )
    owner_editor = detail.locator('.data-table-owner-content [data-property-editor]')
    owner_editor.fill("Reviewed relation explanation")
    owner_editor.press("Tab")
    missing = table.locator('[data-row-key="note:missing"]')
    missing.locator(".data-table-tree-toggle").click()
    empty_detail = table.locator('[data-detail-owner="note:missing"]')
    expect(empty_detail.get_by_role("tab")).to_have_text(["Requirement"])
    expect(empty_detail.get_by_role("tabpanel")).to_contain_text("Unique canonical requirement text.")
    model = json.loads(page.evaluate("obsReport.serializeModel()"))
    left = next(note for note in model["notes"] if note["slug"] == "left")
    assert left["frontmatter"]["explanation"] == "Reviewed canonical subject"
    assert "item" not in next(note for note in model["notes"] if note["slug"] == "relation")["frontmatter"]
    assert "tabCache" not in json.dumps(model)
    assert json.dumps(model).count("Unique canonical requirement text.") == 1
    page.evaluate("obsReport.openBar('comments')")
    page.locator("[data-comment-author]").fill("Reader")
    page.locator("[data-comment-author]").press("Tab")
    page.evaluate("""() => {
        const paragraph = [...document.querySelectorAll(
            '[data-detail-owner="note:relation"] [data-reference-note="left"] p')]
            .find(node=>node.textContent === 'Unique canonical requirement text.');
        const range = document.createRange();
        range.selectNodeContents(paragraph);
        const selection = getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        document.dispatchEvent(new Event('selectionchange'));
    }""")
    page.locator("[data-comment-add]").click()
    page.get_by_role("textbox", name="Comment text", exact=True).fill("Keep subject comment")
    assert page.evaluate("obsComments.data.annotations[0].target.column") == "roles.left"
    detail.get_by_role("tab", name="Evidence", exact=True).click()
    table.locator(":scope > .data-table-scroll > table > thead .data-table-options-toggle").click()
    table.locator('.data-table-options').get_by_role("button", name="Properties", exact=True).click()
    table.locator('.data-table-panel[aria-label="Properties"]').get_by_role(
        "button", name="Requirement", exact=True,
    ).click()
    page.keyboard.press("Escape")
    expect(detail.get_by_role("tab", name="Requirement", exact=True)).to_have_count(0)
    page.locator(".comment-target").first.click()
    expect(detail.get_by_role("tab", name="Requirement", exact=True)).to_have_attribute("aria-selected", "true")
    with page.expect_download() as download:
        page.locator("[data-comment-save]").click()
    reviewed = tmp_path / "reviewed.html"
    download.value.save_as(reviewed)
    page.goto(reviewed.as_uri() + "#chapter")
    page.evaluate("obsPages.setPaged(false); obsReport.activateChapter('chapter')")
    table = page.locator('[data-active-chapter] [data-data-table="chapter-base-1"]')
    page.evaluate("obsReport.openBar('comments')")
    page.locator(".comment-target").first.click()
    expect(table.locator('[data-detail-owner="note:relation"] [data-property-note="left"]')).to_have_value(
        "Reviewed canonical subject",
    )
    expect(table.locator('[data-detail-owner="note:relation"] .data-table-owner-content [data-property-editor]')).to_have_value(
        "Reviewed relation explanation",
    )
    assert page.evaluate("obsComments.data.annotations[0].text") == "Keep subject comment"
    assert page.evaluate("obsComments.data.annotations[0].target.column") == "roles.left"
    ordinary = page.locator('[data-active-chapter] [data-data-table="chapter-base-2"]')
    ordinary.locator('[data-row-key="note:left"] .data-table-tree-toggle').click()
    expect(ordinary.locator('[data-detail-owner="note:left"] [role="tablist"]')).to_have_count(0)
    expect(ordinary.locator('[data-detail-owner="note:left"]')).to_contain_text(
        "Unique canonical requirement text.",
    )
    assert errors == []
    context.close()


def test_native_reference_tabs_follow_columns_pagination_and_row_review(tmp_path, reference_native_browser):
    from playwright.sync_api import expect

    manifest = write_reference_fixture(tmp_path)
    output = tmp_path / "report.html"
    # A one-row page size makes the two-row table multi-page, so its pagination controls exist.
    output.write_text(render_report(manifest, parse_manifest(manifest), table_page_size=1), encoding="utf-8")
    page = reference_native_browser.new_page(viewport={"width": 1440, "height": 1000})
    page.set_default_timeout(6000)
    page.goto(output.as_uri() + "#chapter")
    page.evaluate("obsPages.setPaged(false); obsReport.activateChapter('chapter')")
    table = page.locator('[data-active-chapter] [data-data-table="chapter-base-1"]')
    expect(table.locator(".data-table-count")).to_have_text("2 of 2 items")
    expect(table.locator(".data-table-page")).to_have_text("Page 1 of 2")
    table.get_by_role("button", name="Next table page", exact=True).click()
    table.locator('[data-row-key="note:relation"] .data-table-tree-toggle').click()
    detail = table.locator('[data-detail-owner="note:relation"]')
    detail.get_by_role("tab", name="Evidence", exact=True).click()
    header = table.locator('thead th[data-column-key="roles.right"]')
    header.focus()
    page.keyboard.press("Alt+ArrowLeft")
    expect(detail.get_by_role("tab")).to_have_text(["Evidence", "Requirement"])
    expect(detail.get_by_role("tab", name="Evidence", exact=True)).to_have_attribute("aria-selected", "true")
    table.get_by_role("button", name="Previous table page", exact=True).click()
    expect(detail).to_have_count(0)
    table.get_by_role("button", name="Next table page", exact=True).click()
    expect(detail.get_by_role("tab", name="Evidence", exact=True)).to_have_attribute("aria-selected", "true")
    table.get_by_role("spinbutton", name="Items per page").fill("20")
    table.get_by_role("spinbutton", name="Items per page").press("Tab")
    static_subjects = page.evaluate("""() => {
        const root = document.createElement('div');
        obsReport.renderStatic('chapter',root);
        return [...root.querySelectorAll('[data-detail-owner="note:relation"] [data-reference-note]')]
            .map(subject=>subject.dataset.referenceNote);
    }""")
    assert static_subjects == ["right"]
    table.locator(":scope > .data-table-scroll > table > thead .data-table-options-toggle").click()
    table.locator('.data-table-options').get_by_role("button", name="Properties", exact=True).click()
    table.locator('.data-table-panel[aria-label="Properties"]').get_by_role(
        "button", name="Evidence", exact=True,
    ).click()
    page.keyboard.press("Escape")
    expect(detail.get_by_role("tab")).to_have_text(["Requirement"])
    expect(detail.get_by_role("tabpanel")).to_contain_text("Unique canonical requirement text.")
    table.locator(".data-table-group-toggle").click()
    expect(detail).to_have_count(0)
    table.locator(".data-table-group-toggle").click()
    expect(detail.get_by_role("tab")).to_have_text(["Requirement"])
    page.evaluate("obsReport.openBar('comments')")
    page.locator("[data-comment-author]").fill("Reader")
    page.locator("[data-comment-author]").press("Tab")
    row = table.locator('[data-row-key="note:relation"]')
    row.get_by_role("button", name="Accept item", exact=False).click()
    expect(row).to_have_attribute("data-review-state", "accepted")
    expect(detail).to_have_attribute("data-review-owner-state", "accepted")
    expect(detail.locator("[data-review-gutter]")).to_have_count(0)
    assert page.evaluate("obsComments.data.reviews.filter(r => r.state === 'accepted').length") == 1
    widths = table.locator('td.data-table-icon-cell').evaluate_all(
        "cells => cells.map(cell => cell.getBoundingClientRect().width)",
    )
    assert widths and all(abs(width - 44) < 1 for width in widths)
    static = page.evaluate("""() => {
        const root = document.createElement('div');
        obsReport.renderStatic('chapter',root);
        const table = root.querySelector('table');
        return {wide:table.dataset.tableWide, links:table.querySelectorAll('a[href="#left"]').length};
    }""")
    assert static["wide"] == "true"
    assert static["links"] > 0
    page.close()


def test_native_source_icon_download_reuses_original_archive(tmp_path, reference_native_browser, capsys):
    from playwright.sync_api import expect

    manifest = write_reference_fixture(tmp_path / "vault")
    (manifest.parent / "cfg.json").write_text(
        '{"report":{"tableIconWidthPixels":40}}', encoding="utf-8",
    )
    output = tmp_path / "report.html"
    assert main(["--source", str(manifest), "--check", "--embed-source"]) == 0
    assert not output.exists()
    assert main(["--source", str(manifest), "--output", str(output), "--embed-source"]) == 0
    # The snapshot icon links straight to an external URL: the reference-note lint warns, nothing else.
    warnings = capsys.readouterr().err.splitlines()
    assert len(warnings) == 2 and all(
        "properties.snapshot.obsHtml.icon.linkProperty document resolves to an external URL" in line
        for line in warnings)
    page = reference_native_browser.new_page(accept_downloads=True)
    page.goto(output.as_uri() + "#chapter")
    page.evaluate("obsPages.setPaged(false); obsReport.activateChapter('chapter')")
    table = page.locator('[data-active-chapter] [data-data-table="chapter-base-1"]')
    source = table.locator('[data-row-key="note:relation"]').get_by_role(
        "link", name="Download original source", exact=True,
    )
    expect(source).to_have_attribute("data-source-download", "")
    assert page.locator("#obs-source-archive").count() == 1
    original = base64.b64decode(page.locator("#obs-source-archive").text_content())
    with page.expect_download() as downloaded:
        source.click()
    destination = tmp_path / "downloaded-source.zip"
    downloaded.value.save_as(destination)
    assert destination.read_bytes() == original
    assert page.evaluate("JSON.parse(document.querySelector('[data-report-data]').textContent).tableIconWidthPixels") == 40
    widths = table.locator('td.data-table-icon-cell').evaluate_all(
        "cells => cells.map(cell => cell.getBoundingClientRect().width)",
    )
    assert widths and all(abs(width - 40) < 1 for width in widths)
    all_icons = page.evaluate("""() => {
        const rendered = obsDataTable.render({
            key:'only-icons',columns:['a','b'].map(key=>({key,label:key,fixed:true,width:40})),
            rows:[{key:'one',values:{a:'x',b:'y'}}],
        });
        document.querySelector('[data-chapter-body]').append(rendered.element);
        return [...rendered.element.querySelectorAll('td')].map(cell=>cell.getBoundingClientRect().width);
    }""")
    assert all_icons and all(abs(width - 40) < 1 for width in all_icons)
    page.close()
