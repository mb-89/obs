import os
from importlib.resources import files
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from obs_html.cli import DEFAULT_OUTPUT, build_parser, main
from obs_html.reproduction import embedded_archive
from test_browser import run_report_dom_contract


@pytest.fixture
def document_html(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "manifest.md").write_text("---\ntitle: Design notes\n---\n- [[one]]\n- [[two]]\n", encoding="utf-8")
    (source / "sample.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="240" height="100" viewBox="0 0 240 100">'
        '<rect width="240" height="100" fill="#ddd"/>'
        '<path d="M20 80L80 50L140 65L220 20" fill="none" stroke="#135" stroke-width="4"/>'
        '</svg>', encoding="utf-8",
    )
    for slug in ("one", "two"):
        (source / f"{slug}.md").write_text(
            "---\nexplanation: Original\nstatus: draft\n---\n"
            f"# {slug.title()}\n\nReviewable text.\n\n![Sample](sample.svg)\n\n"
            "```property-editor\nversion: 1\nfield: explanation\nlabel: Explanation\n```\n\n"
            "```base\nobsHtml: {records: note}\nviews:\n"
            "  - type: table\n    order: [title, status, explanation]\n```\n", encoding="utf-8",
        )
    output = tmp_path / "document.html"
    assert main(["--source", str(source), "--output", str(output)]) == 0
    return output


def test_document_default_filename_and_explicit_output(tmp_path):
    assert DEFAULT_OUTPUT.name == "document.html"
    assert build_parser().parse_args(["--output", "My-explicit-report.html"]).output == [Path("My-explicit-report.html")]
    assert "report.html" not in build_parser().format_help()


def test_document_change_owner_controlled_save_boundaries(document_html):
    package = files("obs_html")
    runtimes = [package / "bars" / "filter.js", package / "bars" / "comments.js", package / "storage.js"]
    run_report_dom_contract(document_html, "--document-change-only", *runtimes)


@pytest.fixture
def native_document(document_html):
    if not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"):
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native document checks.")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"])
        context = browser.new_context(accept_downloads=True)
        context.add_init_script("delete window.showSaveFilePicker")
        page = context.new_page()
        page.set_default_timeout(5000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(document_html.as_uri() + "#one")
        try:
            yield page, document_html
            assert errors == []
        finally:
            browser.close()


@pytest.mark.parametrize("width", [320, 390, 1440])
def test_native_shared_document_notices_geometry_print_and_toplayer(native_document, width, tmp_path):
    from playwright.sync_api import expect

    page, _ = native_document
    page.set_viewport_size({"width": width, "height": 900})
    page.evaluate("obsFilter.setExpression('status:draft')")
    notice = page.locator("[data-document-warning]")
    expect(notice).to_be_visible()
    expect(page.locator("[data-review-save-guidance]")).to_have_attribute("data-dirty", "false")
    warning = page.locator("[data-filter-warning]")
    expect(warning).to_be_visible()

    def check_geometry():
        bounds = page.locator("[data-document-warning], [data-filter-warning]").evaluate_all(
            "nodes => nodes.map(n => {const r=n.getBoundingClientRect(); "
            "return {left:r.left,right:r.right,top:r.top,bottom:r.bottom}})",
        )
        controls = page.locator(
            "[data-menu-button], [data-step], [data-filter-input], .chapter-breadcrumbs, .figure-overlay-close",
        ).evaluate_all(
            "nodes => nodes.filter(n => n.getClientRects().length).map(n => {const r=n.getBoundingClientRect(); "
            "return {left:r.left,right:r.right,top:r.top,bottom:r.bottom}})",
        )
        for index, box in enumerate(bounds):
            assert 0 <= box["left"] < box["right"] <= width
            for other in [*bounds[index + 1:], *controls]:
                assert (box["right"] <= other["left"] or box["left"] >= other["right"] or
                        box["bottom"] <= other["top"] or box["top"] >= other["bottom"]), (box, other)
        return bounds

    check_geometry()
    page.screenshot(path=str(tmp_path / f"notices-{width}.png"))
    page.locator("[data-menu-button]").click()
    bounds = check_geometry()
    assert page.locator("[data-bars-menu]").bounding_box()["y"] >= max(b["bottom"] for b in bounds)
    page.keyboard.press("Escape")
    page.evaluate("obsPages.setPaged(false)")
    page.locator(".figure-expand").first.click()
    dialog = page.locator("dialog[open]")
    expect(dialog.locator("[data-document-warning]")).to_be_visible()
    expect(dialog.locator("[data-filter-warning]")).to_be_visible()
    check_geometry()
    page.screenshot(path=str(tmp_path / f"notices-expanded-{width}.png"))
    page.locator("[data-document-download]").focus()
    with page.expect_download() as downloaded:
        page.keyboard.press("Enter")
    saved = tmp_path / f"expanded-save-{width}.html"
    downloaded.value.save_as(saved)
    assert page.evaluate(
        "html => new DOMParser().parseFromString(html, 'text/html')"
        ".querySelectorAll('dialog[open], [data-header-notices]').length",
        saved.read_text(encoding="utf-8"),
    ) == 0
    page.keyboard.press("Escape")
    expect(page.locator("body > [data-header-notices] [data-document-warning]")).to_be_visible()
    page.emulate_media(media="print")
    expect(notice).to_be_hidden()
    expect(warning).to_be_hidden()
    if width == 1440:
        from pypdf import PdfReader

        pdf = tmp_path / "notices-excluded.pdf"
        page.pdf(path=str(pdf))
        text = "\n".join(p.extract_text() for p in PdfReader(pdf).pages)
        assert "Reviewable text." in text
        assert "This HTML has changed" not in text
        assert "Filtered view" not in text
    page.emulate_media(media="screen")
    page.locator("[data-filter-warning] button").click()
    expect(warning).to_be_hidden()
    expect(notice).to_be_hidden()
    page.evaluate("obsReport.commitProperty('one', 'explanation', 'Changed')")
    page.evaluate("obsFilter.setExpression('status:draft')")
    page.locator("[data-filter-warning] button").click()
    expect(notice).to_be_visible()


def test_native_empty_view_initialization_and_saved_selection_baselines(native_document, tmp_path):
    from playwright.sync_api import expect

    page, _ = native_document
    page.wait_for_function("document.documentElement.dataset.reportStatus === 'ready'")
    notice = page.locator("[data-document-warning]")
    guidance = page.locator("[data-review-save-guidance]")
    page.evaluate("obsReport.setViewSelection('levels', [], ['one', 'two'])")
    expect(notice).to_be_hidden()
    assert page.evaluate("obsReport.readerState().views") == {}
    page.evaluate("obsReport.setViewSelection('levels', ['one'], ['one', 'two'])")
    expect(notice).to_be_visible()
    expect(guidance).to_have_attribute("data-dirty", "false")
    page.evaluate("obsReport.setViewSelection('other-view', [], ['one'])")
    expect(notice).to_be_visible()
    page.evaluate("obsReport.setViewSelection('levels', [], ['one', 'two'])")
    expect(notice).to_be_hidden()
    page.evaluate("obsFilter.setExpression('status:draft')")
    page.evaluate("obsReport.setViewSelection('other-view', [], ['one'])")
    expect(notice).to_be_visible()
    page.evaluate("obsFilter.setExpression('')")
    expect(notice).to_be_hidden()
    page.evaluate("obsReport.commitProperty('one', 'explanation', 'Changed')")
    page.evaluate("obsReport.setViewSelection('other-view', [], ['one'])")
    expect(notice).to_be_visible()
    expect(guidance).to_have_attribute("data-dirty", "true")
    page.evaluate("obsReport.commitProperty('one', 'explanation', 'Original')")
    expect(notice).to_be_hidden()
    page.evaluate("obsReport.setViewSelection('levels', ['one'], ['one', 'two'])")
    with page.expect_download() as downloaded:
        page.locator("[data-document-download]").click()
    saved = tmp_path / "saved-view-selection.html"
    downloaded.value.save_as(saved)
    page.goto(saved.as_uri())
    page.wait_for_function("document.documentElement.dataset.reportStatus === 'ready'")
    expect(notice).to_be_hidden()
    assert page.evaluate("obsReport.viewSelection('levels')") == ["one"]
    page.evaluate("obsReport.setViewSelection('levels', [], ['one', 'two'])")
    expect(notice).to_be_visible()
    assert page.evaluate("obsReport.readerState().views") == {"levels": []}
    expect(guidance).to_have_attribute("data-dirty", "false")
    page.evaluate("obsReport.setViewSelection('levels', ['one'], ['one', 'two'])")
    expect(notice).to_be_hidden()


def test_native_timestamp_is_last_content_change_and_survives_save(native_document, tmp_path):
    page, _ = native_document
    page.wait_for_function("document.documentElement.dataset.reportStatus === 'ready'")
    timestamp = "JSON.parse(obsReport.serializeModel()).document.generation.timestamp"
    built = page.evaluate(timestamp)
    page.clock.set_fixed_time("2031-02-03T04:05:06Z")
    page.evaluate("obsFilter.setExpression('status:draft')")
    assert page.evaluate(timestamp) == built, "reader state is not a content change"
    page.evaluate("obsReport.commitProperty('one', 'explanation', 'Changed')")
    changed = "2031-02-03T04:05:06.000+00:00"
    assert page.evaluate(timestamp) == changed
    page.evaluate("obsReport.commitProperty('one', 'explanation', 'Original')")
    assert page.evaluate(timestamp) == built, "returning to the opened content restores its timestamp"
    page.clock.set_fixed_time("2032-03-04T05:06:07Z")
    page.evaluate("obsReport.commitProperty('one', 'explanation', 'Changed again')")
    saved = tmp_path / "saved-timestamp.html"
    saved.write_text(page.evaluate("obsComments.reviewedHtml()"), encoding="utf-8")
    page.goto(saved.as_uri())
    page.wait_for_function("document.documentElement.dataset.reportStatus === 'ready'")
    assert page.evaluate(timestamp) == "2032-03-04T05:06:07.000+00:00"
    page.evaluate("obsReport.commitProperty('one', 'explanation', 'Original')")
    assert page.evaluate(timestamp) != built, "the saved document is the new opened baseline"


def test_native_column_revert_and_transient_state_are_not_semantic_edits(native_document):
    from playwright.sync_api import expect

    page, _ = native_document
    notice = page.locator("[data-document-warning]")
    assert page.locator("[aria-label], [title], [placeholder]").evaluate_all("""nodes => nodes.flatMap(
        node => ['aria-label', 'title', 'placeholder'].map(key => node.getAttribute(key) || '')
    ).filter(label => /\\breport\\b/i.test(label))""") == []
    page.evaluate("obsPages.setPaged(false); obsReport.activateChapter('two'); obsReport.activateChapter('one')")
    expect(notice).to_be_hidden()
    page.evaluate("obsReport.commitProperty('one', 'explanation', 'Original')")
    expect(notice).to_be_hidden()
    table = page.locator('[data-chapter-body] [data-data-table="one-base-1"]')
    table.locator(".data-table-options-toggle").click()
    table.get_by_role("button", name="Properties", exact=True).click()
    table.locator('button[title="Hide status"]').click()
    expect(notice).to_be_visible()
    expect(page.locator("[data-review-save-guidance]")).to_have_attribute("data-dirty", "false")
    table.locator('button[title="Show status"]').click()
    page.keyboard.press("Escape")
    table.locator('th[data-column-key="status"]').press("Alt+ArrowLeft")
    expect(notice).to_be_hidden()
    table.locator('th[data-column-key="status"] .data-table-column-resize').press("ArrowRight")
    expect(notice).to_be_hidden()
    expect(page.locator("[data-review-save-guidance]")).to_have_attribute("data-dirty", "false")
    assert all("widths" not in state for state in page.evaluate("obsReport.readerState().tables").values())


def test_native_application_column_projection_is_not_a_document_change(native_document, tmp_path):
    from playwright.sync_api import expect

    page, _ = native_document
    page.wait_for_function("document.documentElement.dataset.reportStatus === 'ready'")
    page.evaluate("obsPages.setPaged(false); obsReport.activateChapter('one')")
    notice = page.locator("[data-document-warning]")
    guidance = page.locator("[data-review-save-guidance]")
    # A trusted runtime (e.g. Reference levels) derives visible columns from its saved view selection.
    project = """hidden => {
        obsReport.setViewSelection('levels', hidden, ['status']);
        const columns = ['title', 'status', 'explanation'].filter(key => !hidden.includes(key));
        document.querySelectorAll('[data-chapter-body] [data-data-table="one-base-1"]').forEach(
            shell => shell.dispatchEvent(new CustomEvent('obs-table-set-columns', {detail: {columns}})));
    }"""
    reproject = f"({project})(obsReport.viewSelection('levels') || [])"
    page.evaluate(reproject)
    expect(notice).to_be_hidden()
    page.evaluate(project, ["status"])
    expect(notice).to_be_visible()
    expect(guidance).to_have_attribute("data-dirty", "false")
    assert page.evaluate("obsReport.readerState()") == {
        "views": {"levels": ["status"]}, "filterExpression": "", "tables": {},
    }
    page.evaluate(project, [])
    expect(notice).to_be_hidden()

    # Save while the projected table is not rendered, as when a reader changes levels elsewhere.
    page.evaluate("obsReport.activateChapter('two')")
    page.evaluate(project, ["status"])
    with page.expect_download() as downloaded:
        page.locator("[data-document-download]").click()
    saved = tmp_path / "projected-levels.html"
    downloaded.value.save_as(saved)
    for fragment in ("#one", "#two"):
        page.goto(saved.as_uri() + fragment)
        page.wait_for_function("document.documentElement.dataset.reportStatus === 'ready'")
        page.evaluate("obsPages.setPaged(false); obsReport.activateChapter('one')")
        page.evaluate(reproject)
        expect(notice).to_be_hidden()
        expect(guidance).to_have_attribute("data-dirty", "false")
        assert page.locator(
            '[data-chapter-body] [data-data-table="one-base-1"] th[data-column-key="status"]',
        ).count() == 0

    page.evaluate("obsReport.commitProperty('one', 'explanation', 'Changed')")
    expect(notice).to_be_visible()
    expect(guidance).to_have_attribute("data-dirty", "true")
    page.evaluate("obsReport.commitProperty('one', 'explanation', 'Original')")
    expect(notice).to_be_hidden()
    expect(guidance).to_have_attribute("data-dirty", "false")
    table = page.locator('[data-chapter-body] [data-data-table="one-base-1"]')
    table.locator('th[data-column-key="title"] .data-table-column-resize').press("ArrowRight")
    expect(notice).to_be_hidden()
    expect(guidance).to_have_attribute("data-dirty", "false")
    assert "widths" not in page.evaluate("obsReport.readerState().tables").get("one-base-1", {})


def test_native_header_download_reopen_review_and_real_unload(native_document, tmp_path):
    from playwright.sync_api import expect

    page, initial = native_document
    notice = page.locator("[data-document-warning]")
    expect(notice).to_be_hidden()
    page.evaluate("obsFilter.setExpression('status:draft')")
    page.evaluate("obsReport.openBar('comments')")
    page.locator(".review-action--accept").first.click()
    expect(page.locator("[data-review-save-guidance]")).to_have_attribute("data-dirty", "true")
    page.locator("[data-document-download]").focus()
    with page.expect_download() as downloaded:
        page.keyboard.press("Enter")
    saved = tmp_path / "saved-document.html"
    downloaded.value.save_as(saved)
    expect(notice).to_be_visible()
    expect(page.locator("[data-comment-announcer]")).to_contain_text("cannot confirm")
    assert "data-document-warning" not in saved.read_text(encoding="utf-8").split('<script id="report-data"')[0]
    page.goto(saved.as_uri() + "#one")
    expect(notice).to_be_hidden()
    expect(page.locator("[data-filter-warning]")).to_be_visible()
    expect(page.locator("[data-review-save-guidance]")).to_have_attribute("data-dirty", "false")
    assert page.evaluate("obsComments.data.reviews.length") > 0
    page.evaluate("obsFilter.setExpression('')")
    expect(notice).to_be_visible()
    page.locator("[data-menu-button]").click()
    page.keyboard.press("Escape")
    dialogs = []
    page.on("dialog", lambda dialog: (dialogs.append(dialog.type), dialog.dismiss()))
    try:
        page.goto(initial.as_uri())
    except Exception:
        pass
    assert dialogs == ["beforeunload"]
    expect(notice).to_be_visible()


def test_native_evidence_transaction_download_retains_current_source(native_document, tmp_path):
    from playwright.sync_api import expect

    page, output = native_document
    source = output.parent / "source"
    evidence = source / "assets" / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "source.txt").write_text("Original evidence", encoding="utf-8")
    (source / "evidence.md").write_text(
        "---\ntitle: Evidence\n---\n![Evidence](assets/evidence/source.txt)\n", encoding="utf-8",
    )
    assert main(["--source", str(source), "--output", str(output), "--embed-source",
                 "--embed-attachments"]) == 0
    page.reload()
    page.wait_for_function("document.documentElement.dataset.reportStatus === 'ready'")
    notice = page.locator("[data-document-warning]")
    expect(notice).to_be_hidden()
    page.evaluate("""async () => {
        const bytes = new TextEncoder().encode('Replacement evidence');
        const descriptor = await obsPayload.describeAsset('assets/evidence/source.txt', bytes, 'text/plain');
        const notes = obsReport.canonicalNotes();
        const evidence = notes.find(n => n.sourcePath === 'evidence.md');
        const oldKey = /obs-asset:([a-f0-9]+)/.exec(evidence.html)[1];
        evidence.safeContent = [{type:'paragraph',children:[{
            type:'link',label:'Evidence',assetKey:descriptor.key,downloadName:'source.txt',
        }]}];
        window.evidenceStage = await obsReport.stageCanonicalTransaction({
            expectedRevision:obsReport.revision, notes,
            assetChanges:[{...descriptor,bytes,removeKeys:[oldKey]}],
            sourceChanges:[{path:'vault/evidence.md',bytes:new TextEncoder().encode(
                '---\\ntitle: Evidence\\n---\\n![Evidence](assets/evidence/source.txt)\\n')}],
        });
    }""")
    expect(notice).to_be_hidden()
    page.evaluate("evidenceStage.commit()")
    expect(notice).to_be_visible()
    expect(page.locator("[data-review-save-guidance]")).to_have_attribute("data-dirty", "true")
    with page.expect_download() as downloaded:
        page.locator("[data-document-download]").click()
    saved = tmp_path / "replacement.html"
    downloaded.value.save_as(saved)
    expect(notice).to_be_visible()
    with ZipFile(BytesIO(embedded_archive(saved.read_text(encoding="utf-8")))) as archive:
        assert archive.read("vault/assets/evidence/source.txt") == b"Replacement evidence"
        assert len([name for name in archive.namelist() if name == "vault/assets/evidence/source.txt"]) == 1
    page.goto(saved.as_uri())
    expect(notice).to_be_hidden()
    assert page.evaluate(
        "async () => new TextDecoder().decode(await obsPayload.readMember('vault/assets/evidence/source.txt'))",
    ) == "Replacement evidence"
    page.evaluate("""async () => {
        const staged = await obsReport.stageCanonicalTransaction({
            expectedRevision:obsReport.revision, notes:obsReport.canonicalNotes(), assetChanges:[],
            sourceChanges:[{path:'vault/evidence.md',bytes:new TextEncoder().encode(
                '---\\ntitle: Evidence\\n---\\n![Evidence](assets/evidence/source.txt)\\n\\n<!-- New source annotation -->\\n')}],
        });
        staged.commit();
    }""")
    expect(notice).to_be_visible()
    expect(page.locator("[data-review-save-guidance]")).to_have_attribute("data-dirty", "false")
