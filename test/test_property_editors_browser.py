import json
import os

import pytest
import yaml

from obs_html_interim.content import parse_manifest
from obs_html_interim.renderer import render_artifact
from test_reader_controls import reader_browser  # noqa: F401


def test_native_canonical_projection_rejects_protected_fields_and_home_atomically(tmp_path):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native projection checks.")
    from playwright.sync_api import sync_playwright

    protected = [
        "title", "kind", "aliases", "term", "definition",
        "__proto__", "constructor", "prototype", "Title", "KiNd",
    ]
    (tmp_path / "manifest.md").write_text("- [[one]]\n- [[two]]\n", encoding="utf-8")
    for slug in ("one", "two"):
        frontmatter = {field: "Original" for field in protected}
        frontmatter.update({"aliases": ["Original"], "status": "Initial", "explanation": "Original"})
        (tmp_path / f"{slug}.md").write_text(
            "---\n" + json.dumps(frontmatter) + "\n---\n# Note\n\n"
            "```property-editor\nversion: 1\nfield: explanation\nlabel: Review\n```\n",
            encoding="utf-8",
        )
    manifest = tmp_path / "manifest.md"
    artifact = tmp_path / "artifact.html"
    artifact.write_text(render_artifact(manifest, parse_manifest(manifest)), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        try:
            page = browser.new_page()
            page.goto(artifact.as_uri())
            page.evaluate("""() => {
                obsArtifact.records.find(record => record.slug === 'home').frontmatter.status = 'Initial';
                window.projectionEvents = 0;
                document.addEventListener('obs-canonical-property-change', () => projectionEvents++);
                document.addEventListener('obs-artifact-filter', () => projectionEvents++);
            }""")
            original = page.evaluate("obsArtifact.serializeModel()")
            for slug, field in [("two", field) for field in protected] + [("home", "status")]:
                rejected = page.evaluate("""({slug, field}) => {
                    try {
                        obsArtifact.commitCanonicalProjection([
                            {slug: 'one', fields: {status: 'Changed before invalid'}},
                            {slug, fields: {[field]: field === 'aliases' ? ['Changed'] : 'Changed'}},
                        ]);
                        return false;
                    } catch (_) { return true; }
                }""", {"slug": slug, "field": field})
                assert rejected, (slug, field)
                assert page.evaluate("obsArtifact.serializeModel()") == original
                assert page.evaluate("window.projectionEvents") == 0
        finally:
            browser.close()


def test_native_property_edits_survive_actual_reviewed_download_and_reopen(tmp_path):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native property-editor checks.")
    from playwright.sync_api import sync_playwright, expect

    (tmp_path / "manifest.md").write_text("- [[one]]\n- [[two]]\n", encoding="utf-8")
    for name in ("one", "two"):
        (tmp_path / f"{name}.md").write_text(
            "---\n" + json.dumps({"explanation": f"Original {name}", "identifier": name}) + "\n---\n"
            f"# {name.title()}\n\nSource text.\n\n"
            "```property-editor\nversion: 1\nfield: explanation\nlabel: Explanation\n```\n"
            "\n```base\nobsHtml: {records: note}\nviews:\n - type: table\n"
            "   order: [identifier, explanation]\n```\n", encoding="utf-8",
        )
    manifest = tmp_path / "manifest.md"
    artifact = tmp_path / "artifact.html"
    artifact.write_text(render_artifact(manifest, parse_manifest(manifest)), encoding="utf-8")
    malicious = 'Accepted \u03b1 \u4e2d </script><script>window.editExecuted=true</script> **literal**'
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        context = browser.new_context(accept_downloads=True)
        context.add_init_script("delete window.showSaveFilePicker")
        page = context.new_page()
        page.set_default_timeout(5000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(artifact.as_uri() + "#one")
        page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('one')")
        editor = page.locator("[data-active-chapter] [data-property-editor]")
        expect(editor).to_have_value("Original one")
        editor.fill(malicious)
        editor.press("Tab")
        assert page.evaluate("obsArtifact.records.find(note => note.slug === 'one').frontmatter.explanation") == malicious
        assert malicious in page.locator("[data-active-chapter] .data-table-shell table").inner_text()
        assert page.evaluate("obsArtifact.records.find(note => note.slug === 'two').frontmatter.explanation") == "Original two"
        assert page.evaluate("""() => {
            try { obsArtifact.commitProperty('one', 'identifier', 'changed'); return false; }
            catch (_) { return true; }
        }""")
        assert page.evaluate("""obsQuery.compile('explanation:"Accepted"').match(
            obsArtifact.records.find(note => note.slug === 'one'))""")
        assert not page.evaluate("Boolean(window.editExecuted)")
        page.evaluate("""() => {
            obsComments.data.reviewers.push('Reader');
            obsComments.data.annotations.push({id:'kept-comment', author:'Reader', text:'Keep this comment',
              status:'open', replies:[], target:{chapter:'one',quote:'Source text.',start:0,end:12}});
            obsComments.data.reviews.push({chapter:'one',item:'item-1',reviewer:'Reader',state:'accepted'});
            obsArtifact.openBar('comments');
        }""")
        with page.expect_download() as download:
            page.locator("[data-comment-save]").click()
        saved = tmp_path / "reviewed.html"
        download.value.save_as(saved)
        page.goto(saved.as_uri() + "#one")
        page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('one')")
        expect(page.locator("[data-active-chapter] [data-property-editor]")).to_have_value(malicious)
        assert page.evaluate("obsComments.data.annotations[0].text") == "Keep this comment"
        assert page.evaluate("obsComments.data.reviews[0].state") == "accepted"
        assert not page.evaluate("Boolean(window.editExecuted)")
        page.evaluate("obsArtifact.activateChapter('two')")
        editor = page.locator("[data-active-chapter] [data-property-editor]")
        expect(editor).to_have_value("Original two")
        editor.fill("")
        editor.press("Tab")
        page.evaluate("obsArtifact.openBar('comments')")
        with page.expect_download() as download:
            page.locator("[data-comment-save]").click()
        second = tmp_path / "reviewed-twice.html"
        download.value.save_as(second)
        page.goto(second.as_uri() + "#two")
        page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('two')")
        expect(page.locator("[data-active-chapter] [data-property-editor]")).to_have_value("")
        assert page.evaluate("obsArtifact.records.find(note => note.slug === 'one').frontmatter.explanation") == malicious
        assert page.evaluate("obsArtifact.records.find(note => note.slug === 'one').frontmatter.identifier") == "one"
        assert page.evaluate("obsComments.data.annotations.length") == 1
        page.evaluate("obsArtifact.openBar('comments')")
        with page.expect_download() as download:
            page.locator("[data-comment-save]").click()
        unchanged = tmp_path / "reviewed-no-new-edits.html"
        download.value.save_as(unchanged)
        page.goto(unchanged.as_uri() + "#two")
        page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('two')")
        expect(page.locator("[data-active-chapter] [data-property-editor]")).to_have_value("")
        assert page.evaluate("obsArtifact.records.find(note => note.slug === 'one').frontmatter.explanation") == malicious
        assert page.evaluate("obsComments.data.reviews[0].state") == "accepted"
        assert errors == []
        browser.close()


@pytest.mark.parametrize("deny_storage", [False, True], ids=["storage-available", "storage-denied"])
def test_native_unsaved_review_warning_tracks_changes_and_save_boundaries(tmp_path, deny_storage):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for unsaved-review checks.")
    from playwright.sync_api import sync_playwright, expect

    (tmp_path / "manifest.md").write_text("- [[one]]\n- [[two]]\n", encoding="utf-8")
    for name in ("one", "two"):
        (tmp_path / f"{name}.md").write_text(
            "---\nexplanation: Original\n---\n"
            f"# {name.title()}\n\nReviewable text.\n\n"
            "```property-editor\nversion: 1\nfield: explanation\nlabel: Explanation\n```\n",
            encoding="utf-8",
        )
    manifest = tmp_path / "manifest.md"
    artifact = tmp_path / "artifact.html"
    artifact.write_text(render_artifact(manifest, parse_manifest(manifest)), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        context = browser.new_context(accept_downloads=True)
        context.add_init_script("delete window.showSaveFilePicker")
        if deny_storage:
            context.add_init_script(
                "Object.defineProperty(window, 'localStorage', {get() { throw new Error('Storage denied'); }});"
            )
        page = context.new_page()
        page.set_default_timeout(5000)
        page.goto(artifact.as_uri() + "#one")
        status = page.locator("[data-review-save-guidance]")
        expect(status).to_contain_text("Download HTML")
        expect(status).to_contain_text("No unsaved review changes")
        assert page.evaluate("""() => {
            const event = new Event('beforeunload', {cancelable:true});
            return window.dispatchEvent(event) && !event.defaultPrevented;
        }""")

        page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('two'); obsArtifact.activateChapter('one')")
        page.evaluate("obsArtifact.openBar('comments')")
        expect(status).to_contain_text("No unsaved review changes")
        page.evaluate("obsFilter.setExpression('title: /One/')")
        expect(status).to_contain_text("No unsaved review changes")
        page.evaluate("obsFilter.setExpression('')")
        editor = page.locator("[data-active-chapter] [data-property-editor]")
        editor.fill("Edited")
        editor.press("Tab")
        assert page.evaluate(
            "obsArtifact.records.find(note => note.slug === 'one').frontmatter.explanation",
        ) == "Edited"
        expect(status).to_contain_text("Unsaved review changes")
        assert page.evaluate("""() => {
            const event = new Event('beforeunload', {cancelable:true});
            window.dispatchEvent(event);
            return event.defaultPrevented;
        }""")
        editor.fill("Original")
        editor.press("Tab")
        assert page.evaluate(
            "obsArtifact.records.find(note => note.slug === 'one').frontmatter.explanation",
        ) == "Original"
        expect(status).to_contain_text("No unsaved review changes")

        item = page.locator("[data-active-chapter] .review-action--reject").first
        item.click()
        expect(status).to_contain_text("Unsaved review changes")
        page.locator(".comment-text-editor").last.fill("Keep this review")
        with page.expect_download() as download:
            page.locator("[data-comment-save]").click()
        saved = tmp_path / "reviewed.html"
        download.value.save_as(saved)
        expect(status).to_contain_text("Unsaved review changes")
        expect(page.locator("[data-comment-announcer]")).to_contain_text(
            "browser cannot confirm it was saved",
        )
        page.goto(saved.as_uri() + "#one")
        expect(page.locator("[data-review-save-guidance]")).to_contain_text(
            "No unsaved review changes",
        )
        page.evaluate("obsArtifact.openBar('comments')")

        page.evaluate("""async () => {
            const incoming = {version:2, annotations:[{
                id:'imported', target:{chapter:'two'}, author:'Reviewer',
                text:'Imported', status:'open', replies:[],
            }]};
            const html = '<script id="obs-comments" data-comment-island type="application/json">' +
                JSON.stringify(incoming) + '</script>';
            await obsComments.importFiles([{text: async () => html}]);
        }""")
        expect(page.locator("[data-review-save-guidance]")).to_contain_text("Unsaved review changes")
        page.evaluate("""async () => {
            const html = await obsComments.reviewedHtml();
            await obsComments.importFiles([{text: async () => html}]);
        }""")
        expect(page.locator("[data-review-save-guidance]")).to_contain_text("Unsaved review changes")
        page.evaluate("""() => {
            window.showSaveFilePicker = async () => { throw new DOMException('Cancelled', 'AbortError'); };
        }""")
        page.locator("[data-comment-save]").click()
        expect(page.locator("[data-review-save-guidance]")).to_contain_text("Unsaved review changes")
        page.evaluate("""() => {
            window.showSaveFilePicker = async () => ({
                createWritable: async () => { throw new Error('write failed'); },
            });
        }""")
        with page.expect_download() as fallback:
            page.locator("[data-comment-save]").click()
        fallback_path = tmp_path / "fallback.html"
        fallback.value.save_as(fallback_path)
        expect(page.locator("[data-review-save-guidance]")).to_contain_text(
            "Unsaved review changes",
        )
        page.goto(fallback_path.as_uri() + "#one")
        expect(page.locator("[data-review-save-guidance]")).to_contain_text(
            "No unsaved review changes",
        )
        page.evaluate("obsArtifact.openBar('comments')")
        page.locator("[data-active-chapter] .review-action--accept").first.click()
        expect(page.locator("[data-review-save-guidance]")).to_contain_text("Unsaved review changes")
        page.evaluate("""() => {
            window.showSaveFilePicker = async () => ({
                createWritable: async () => ({
                    write: async contents => { window.pickerContents = contents; },
                    close: async () => { window.pickerClosed = true; },
                }),
            });
        }""")
        page.locator("[data-comment-save]").click()
        expect(page.locator("[data-review-save-guidance]")).to_contain_text(
            "No unsaved review changes",
        )
        assert page.evaluate("window.pickerClosed && window.pickerContents.includes('obs-comments')")

        page.evaluate("""() => {
            obsArtifact.openBar('comments');
            document.querySelector('.comment-text-editor').value = 'A newer unsaved edit';
            document.querySelector('.comment-text-editor').dispatchEvent(new Event('input', {bubbles:true}));
            delete window.showSaveFilePicker;
            URL.createObjectURL = () => { throw new Error('download failed'); };
        }""")
        page.locator("[data-comment-save]").click()
        expect(page.locator("[data-review-save-guidance]")).to_contain_text("Unsaved review changes")
        assert page.evaluate("""() => {
            const event = new Event('beforeunload', {cancelable:true});
            window.dispatchEvent(event);
            return event.defaultPrevented;
        }""")
        dialogs = []
        page.on("dialog", lambda dialog: (dialogs.append(dialog.type), dialog.dismiss()))
        try:
            page.goto("about:blank")
        except Exception:
            pass
        assert "beforeunload" in dialogs
        browser.close()


def test_native_canonical_projection_is_atomic_and_updates_existing_views(tmp_path):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for projection checks.")
    from playwright.sync_api import sync_playwright, expect

    card = {
        "version": 1,
        "cards": [{
            "title": "Findings",
            "body": "",
            "metrics": [{
                "label": "Explained findings",
                "where": [
                    {"field": "kind", "equals": "path"},
                    {"field": "status", "equals": "explained-finding-at-eit"},
                ],
            }],
        }],
    }
    (tmp_path / "manifest.md").write_text(
        "- [[one]]\n- [[two]]\n\n```cards\n" + json.dumps(card) + "\n```\n",
        encoding="utf-8",
    )
    fields = {
        "kind": "path",
        "status": "explained-finding-at-eit",
        "statusGroup": "finding-at-eit",
        "coverageAccepted": "yes",
        "sinkKey": "one-finding",
        "outputGroups": ["Exported to system"],
        "explanation": "Evidence explains the path.",
    }
    editor_spec = {
        "version": 1,
        "field": "explanation",
        "label": "Explanation",
        "projection": {
            "blank": {
                "status": "finding-at-eit",
                "coverageAccepted": "no",
                "sinkKey": "one-path",
            },
            "nonblank": {
                "status": "explained-finding-at-eit",
                "coverageAccepted": "yes",
                "sinkKey": "one-finding",
            },
        },
    }
    (tmp_path / "one.md").write_text(
        "---\n" + json.dumps({**fields, "identifier": "one"}) + "\n---\n"
        "# One\n\n"
        "```property-editor\n" + json.dumps(editor_spec) + "\n```\n\n"
        "```base\nfilters: 'kind == \"path\"'\nobsHtml: {records: note}\n"
        "views:\n  - type: table\n    order: [identifier, status, statusGroup, outputGroups]\n```\n\n"
        "```figure\nversion: 1\nkind: sankey\nsource: flow.json\ncaption: Dynamic paths\n```\n",
        encoding="utf-8",
    )
    (tmp_path / "two.md").write_text(
        "---\n" + json.dumps({**fields, "identifier": "two"}) + "\n---\n# Two\n",
        encoding="utf-8",
    )
    (tmp_path / "flow.json").write_text(json.dumps({
        "version": 1,
        "nodes": [
            {"id": "source", "label": "Source", "stage": 0},
            {"id": "target", "label": "Target", "stage": 1},
        ],
        "links": [{
            "source": "source",
            "target": "target",
            "value": 2,
            "where": [{"field": "status", "equals": "explained-finding-at-eit"}],
        }],
        "data": {"where": [{"field": "kind", "equals": "path"}]},
    }), encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    artifact = tmp_path / "artifact.html"
    artifact.write_text(render_artifact(manifest, parse_manifest(manifest)), encoding="utf-8")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        context = browser.new_context(accept_downloads=True)
        context.add_init_script("delete window.showSaveFilePicker")
        page = context.new_page()
        page.set_default_timeout(5000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(artifact.as_uri() + "#one")
        page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('one')")
        page.evaluate("obsArtifact.setFilter(obsQuery.compile('kind:path'))")
        table = page.locator('[data-active-chapter] [data-data-table="one-base-1"]')
        expect(table.locator("tbody tr[data-row-key]")).to_have_count(2)
        sankey_link = page.locator(
            "[data-active-chapter] .sankey-canvas [data-flow-value]",
        )
        expect(sankey_link).to_have_attribute("data-flow-value", "2")
        editor = page.locator("[data-active-chapter] [data-property-editor]")
        editor.fill("")
        editor.press("Tab")
        expect(sankey_link).to_have_attribute("data-flow-value", "1")
        assert page.evaluate(
            "obsArtifact.records.find(record => record.slug === 'one').fields.status[0]",
        ) == "finding-at-eit"
        assert page.evaluate(
            "obsArtifact.records.find(record => record.slug === 'one').fields.coverageaccepted[0]",
        ) == "no"
        assert page.evaluate(
            "obsArtifact.records.find(record => record.slug === 'one').fields.sinkkey[0]",
        ) == "one-path"
        assert page.evaluate(
            "obsArtifact.records.find(record => record.slug === 'one').fields.statusgroup[0]",
        ) == "finding-at-eit"
        editor.fill("Updated explanation")
        editor.press("Tab")
        expect(sankey_link).to_have_attribute("data-flow-value", "2")
        assert page.evaluate(
            "obsArtifact.records.find(record => record.slug === 'one').fields.status[0]",
        ) == "explained-finding-at-eit"
        editor.fill("")
        editor.press("Tab")
        expect(sankey_link).to_have_attribute("data-flow-value", "1")

        page.evaluate("""() => {
            let notifications = 0;
            let filterRefreshes = 0;
            document.addEventListener('obs-canonical-property-change', () => notifications++);
            document.addEventListener('obs-artifact-filter', () => filterRefreshes++);
            window.projectionCounts = () => ({notifications, filterRefreshes});
        }""")
        changed = page.evaluate("""() => obsArtifact.commitCanonicalProjection([
            {slug: 'one', fields: {
                coverageAccepted: 'yes',
                sinkKey: 'resolved-one',
                outputGroups: [],
            }},
            {slug: 'two', fields: {
                coverageAccepted: 'no',
                sinkKey: 'resolved-two',
                outputGroups: ['Exported to labels', 'Exported to system'],
            }},
        ])""")
        assert changed
        assert page.evaluate("window.projectionCounts()") == {
            "notifications": 1, "filterRefreshes": 1,
        }
        assert page.evaluate(
            "obsArtifact.records.filter(record => record.fields.kind?.includes('path'))"
            ".map(record => record.fields.status[0])",
        ) == ["finding-at-eit", "explained-finding-at-eit"]
        expect(sankey_link).to_have_attribute("data-flow-value", "1")
        expect(table).to_contain_text("finding-at-eit")
        assert page.evaluate(
            "obsArtifact.matchesFilter(obsArtifact.records.find(record => record.slug === 'one'))",
        )

        with pytest.raises(Exception):
            page.evaluate("""() => obsArtifact.commitCanonicalProjection([
                {slug: 'one', fields: {status: 'changed-before-invalid'}},
                {slug: 'two', fields: {missingField: 'not-declared'}},
            ])""")
        assert page.evaluate(
            "obsArtifact.records.find(record => record.slug === 'one').fields.status[0]",
        ) == "finding-at-eit"
        assert page.evaluate("window.projectionCounts()") == {
            "notifications": 1, "filterRefreshes": 1,
        }

        page.evaluate("obsArtifact.activateChapter('home')")
        expect(page.locator("[data-record-card] .record-metric-value strong")).to_have_text("1")
        serialized = json.loads(page.evaluate("obsArtifact.serializeModel()"))
        serialized_notes = {note["slug"]: note for note in serialized["notes"]}
        assert serialized_notes["one"]["frontmatter"]["status"] == "finding-at-eit"
        assert serialized_notes["two"]["frontmatter"]["outputGroups"] == [
            "Exported to labels", "Exported to system",
        ]
        page.evaluate("""() => {
            obsComments.data.reviewers.push('Reviewer');
            obsComments.data.annotations.push({id:'projection-comment', author:'Reviewer',
              text:'Keep projection review', status:'open', replies:[],
              target:{chapter:'one',quote:'One',start:0,end:3}});
            obsComments.data.reviews.push({chapter:'one',item:'item-1',reviewer:'Reviewer',state:'accepted'});
            obsArtifact.openBar('comments');
        }""")
        guidance = page.locator("[data-review-save-guidance]")
        expect(guidance).to_contain_text("Unsaved review changes")
        with page.expect_download() as download:
            page.locator("[data-comment-save]").click()
        saved = tmp_path / "projected.html"
        download.value.save_as(saved)
        page.goto(saved.as_uri() + "#one")
        page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('one')")
        assert page.evaluate(
            "obsArtifact.records.find(record => record.slug === 'one').fields.status[0]",
        ) == "finding-at-eit"
        assert page.evaluate(
            "obsArtifact.records.find(record => record.slug === 'two').fields.outputgroups",
        ) == ["Exported to labels", "Exported to system"]
        expect(
            page.locator("[data-active-chapter] .sankey-canvas [data-flow-value]"),
        ).to_have_attribute("data-flow-value", "1")
        expect(page.locator("[data-review-save-guidance]")).to_contain_text(
            "No unsaved review changes",
        )
        assert page.evaluate("obsComments.data.annotations[0].text") == "Keep projection review"
        assert page.evaluate("obsComments.data.reviews[0].state") == "accepted"
        assert errors == []
        browser.close()


def test_native_single_line_editor_preserves_untouched_multiline_and_saves(tmp_path, reader_browser):
    from playwright.sync_api import expect

    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[findings]]", encoding="utf-8")
    title = "A complete linked finding title that must stay on one line rather than becoming four rows."
    (tmp_path / "source.md").write_text("---\ntitle: " + title + "\n---\nSource item.", encoding="utf-8")
    original = "First accepted line.\nSecond accepted line."
    (tmp_path / "finding.md").write_text("---\n" + json.dumps({
        "kind": "finding", "subject": "[[source]]", "explanation": original,
    }) + "\n---\n```property-editor\nversion: 1\nfield: explanation\nlabel: Explanation\n```\n",
        encoding="utf-8")
    definition = {"filters": 'kind == "finding"', "properties": {
        "subject": {"obsHtml": {"reference": {"label": ["title"]}, "singleLine": True}},
        "explanation": {"obsHtml": {"editable": True, "editor": "singleLine"}},
    }, "views": [{"type": "table", "order": ["subject", "explanation"]}]}
    (tmp_path / "findings.md").write_text("# Findings\n\n```base\n" +
        yaml.safe_dump(definition) + "```\n", encoding="utf-8")
    output = tmp_path / "single-line.html"
    output.write_text(render_artifact(manifest, parse_manifest(manifest)), encoding="utf-8")
    page = reader_browser.new_page(viewport={"width": 1500, "height": 1000})
    page.add_init_script("delete window.showSaveFilePicker")
    downloads = []
    page.on("download", lambda download: downloads.append(download.suggested_filename))
    try:
        page.goto(output.as_uri() + "#findings")
        assert page.evaluate("""() => {
            try {obsBases.validate({properties:{explanation:{obsHtml:{editor:'singleLine'}}},
                views:[{type:'table',order:['explanation']}]});return false;}
            catch(error){return error.message.includes('requires editable');}
        }""")
        editor = page.locator("[data-active-chapter] input[data-property-single-line]")
        expect(editor).to_have_count(1)
        editor.focus()
        editor.press("Tab")
        assert page.evaluate("obsArtifact.records.find(r=>r.slug==='finding').frontmatter.explanation") == original
        label = page.locator(".data-table-cell--single-line a")
        expect(label).to_have_attribute("title", title)
        assert label.evaluate("node=>getComputedStyle(node).whiteSpace") == "nowrap"
        editor.fill("Actually edited and accepted.")
        editor.press("Enter")
        assert page.evaluate("obsArtifact.records.find(r=>r.slug==='finding').frontmatter.explanation") == \
            "Actually edited and accepted."
        assert downloads == []
        page.evaluate("obsArtifact.openBar('comments')")
        with page.expect_download() as downloaded:
            page.locator("[data-comment-save]").click()
        reviewed = tmp_path / "reviewed.html"
        downloaded.value.save_as(reviewed)
        page.goto(reviewed.as_uri() + "#findings")
        expect(page.locator("[data-active-chapter] input[data-property-single-line]")).to_have_value(
            "Actually edited and accepted.")
    finally:
        page.close()
