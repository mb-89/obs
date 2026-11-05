import pytest

from obs_html_interim.content import parse_manifest
from obs_html_interim.renderer import render_artifact
from obs_html_interim.reproduction import embed_payload_runtime
from test_reader_controls import reader_browser


@pytest.fixture
def review_projection_page(tmp_path, reader_browser, request):
    manifest = tmp_path / "manifest.md"
    manifest.write_text(
        "- [[chapter]]\n- [[register]]\n- [[other]]\n\n"
        "Authored Home preface.\n\nAuthored Home review guidance.\n",
        encoding="utf-8",
    )
    (tmp_path / "chapter.md").write_text(
        "# Chapter\n\nIntroduction.\n\n## Section\n\nOne.\n\n"
        "### Nested\n\nTwo.\n\n## Next\n\nThree.\n", encoding="utf-8",
    )
    base = (
        '```base\nfilters:\n  and:\n    - \'kind == "finding"\'\n'
        '    - \'status == "open"\'\nviews:\n'
        "  - type: table\n    order: [title, status]\n```\n"
    )
    for slug in ("register", "other"):
        (tmp_path / f"{slug}.md").write_text(f"# {slug.title()}\n\n" + base, encoding="utf-8")
    for slug in ("a", "b"):
        (tmp_path / f"{slug}.md").write_text(
            f"---\ntitle: {slug.upper()}\nkind: finding\nstatus: open\n---\n", encoding="utf-8",
        )
    artifact = tmp_path / "review-projections.html"
    artifact.write_text(
        embed_payload_runtime(render_artifact(
            manifest, parse_manifest(manifest), table_page_size=getattr(request, "param", None),
        )), encoding="utf-8",
    )
    page = reader_browser.new_page(viewport={"width": 1440, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script("""(() => {
        window.reviewProjections = [];
        Object.defineProperty(window, 'obsArtifact', {configurable: true, set(artifact) {
            const render = artifact.renderStatic;
            artifact.renderStatic = (slug, root, respectFilter = true, ...rest) => {
                if (!respectFilter) reviewProjections.push(slug);
                return render(slug, root, respectFilter, ...rest);
            };
            Object.defineProperty(window, 'obsArtifact', {value: artifact, configurable: true});
        }});
    })();""")
    page.goto(artifact.as_uri() + "#chapter")
    page.evaluate("""() => {
        obsArtifact.openBar('comments');
        const author = document.querySelector('[data-comment-author]');
        author.value = 'Ada';
        author.dispatchEvent(new Event('change'));
    }""")
    assert _counts(page) == [0, 0, 10]
    assert sorted(_projections(page)) == ["chapter", "home", "other", "register"]
    try:
        yield page
        assert errors == []
    finally:
        page.close()


def _counts(page):
    return page.locator("[data-review-summary-count]").evaluate_all(
        "nodes => nodes.map(node => Number(node.textContent))",
    )


def _projections(page):
    return page.evaluate("reviewProjections.splice(0)")


@pytest.mark.parametrize("paged", [False, True])
def test_review_identities_follow_canonical_rows_and_replacement(review_projection_page, paged):
    page = review_projection_page
    page.evaluate("paged => obsPages.setPaged(paged)", paged)
    page.evaluate("obsArtifact.activateChapter('register')")
    row = page.locator('[data-chapter-body] tr[data-row-key="note:a"]')
    row.locator(".review-action--accept").click()
    assert _counts(page) == [1, 0, 9]
    assert _projections(page) == []

    assert page.evaluate("""obsArtifact.commitCanonicalProjection([{
        slug: 'a', fields: {status: 'excluded'}
    }])""")
    assert _counts(page) == [0, 0, 8]
    assert sorted(_projections(page)) == ["other", "register"]
    assert page.evaluate("obsComments.data.reviews[0].item") == "row-register-base-1:note%3Aa"
    assert page.evaluate("obsArtifact.records.find(record => record.slug === 'register').fields.review") == [
        "waiting",
    ]

    page.evaluate("""async () => {
        const notes = obsArtifact.canonicalNotes();
        const replacement = structuredClone(notes.find(note => note.sourcePath === 'b.md'));
        replacement.sourcePath = 'c.md';
        replacement.title = 'Replacement';
        replacement.slug = 'c';
        const transaction = await obsArtifact.stageCanonicalTransaction({
            expectedRevision: obsArtifact.revision,
            notes: [...notes.filter(note => note.sourcePath !== 'b.md'), replacement],
            assetChanges: []
        });
        transaction.commit();
    }""")
    assert _counts(page) == [0, 0, 8]
    assert sorted(_projections(page)) == ["other", "register"]
    assert page.locator('[data-chapter-body] tr[data-row-key="note:c"]').is_visible()
    assert page.locator('[data-chapter-body] tr[data-row-key="note:b"]').count() == 0
    assert page.evaluate("obsComments.data.reviews.length") == 1
    assert page.evaluate("""() => {
        try {
            obsArtifact.commitCanonicalProjection([{slug:'a', fields:{missing:'invalid'}}]);
            return false;
        } catch { return true; }
    }""")
    assert not page.evaluate("""obsArtifact.commitCanonicalProjection([{
        slug:'a', fields:{status:'excluded'}
    }])""")
    assert _projections(page) == []
    assert _counts(page) == [0, 0, 8]

    assert page.evaluate("""obsArtifact.commitCanonicalProjection([{
        slug: 'a', fields: {status: 'open'}
    }])""")
    assert _counts(page) == [1, 0, 9]
    assert sorted(_projections(page)) == ["other", "register"]
    assert row.get_attribute("data-review-state") == "accepted"


@pytest.mark.parametrize("paged", [False, True])
def test_review_canonical_content_keeps_section_and_document_batch_identities(
    review_projection_page, paged,
):
    page = review_projection_page
    page.evaluate("paged => obsPages.setPaged(paged)", paged)
    page.locator('[data-review-item="item-2"] .review-action--accept').click(modifiers=["Shift"])
    assert _counts(page) == [2, 0, 8]
    assert page.evaluate("obsComments.data.reviews.map(review => review.item)") == ["item-2", "item-3"]
    assert _projections(page) == []
    page.evaluate("""() => {
        // Simulate the canonical owner's content-change notification, not a new edit API.
        obsArtifact.records.find(record => record.slug === 'chapter').html += '<p>Appended.</p>';
        document.dispatchEvent(new CustomEvent('obs-canonical-property-change', {
            detail: {slug: 'chapter'}
        }));
        obsArtifact.activateChapter('register');
        obsArtifact.activateChapter('chapter');
    }""")
    assert _counts(page) == [2, 0, 9]
    assert sorted(_projections(page)) == ["chapter", "other", "register"]
    page.locator('[data-review-item="item-1"] .review-action--accept').click(
        modifiers=["Control", "Shift"],
    )
    assert _counts(page) == [11, 0, 0]
    assert page.evaluate("obsComments.data.reviews.filter(review => review.chapter === 'chapter').length") == 5
    assert _projections(page) == []


@pytest.mark.parametrize("paged", [False, True])
# A one-row page size makes the two-row table multi-page, so its pagination controls exist.
@pytest.mark.parametrize("review_projection_page", [1], indirect=True)
def test_review_definition_commit_is_local_and_view_changes_reuse_identities(review_projection_page, paged):
    page = review_projection_page
    page.evaluate("paged => obsPages.setPaged(paged)", paged)
    page.evaluate("obsArtifact.activateChapter('register')")
    shell = page.locator('[data-chapter-body] [data-data-table="register-base-1"]')
    row = shell.locator('tr[data-row-key="note:a"]')
    row.locator(".review-action--accept").click()
    page.evaluate("""() => {
        window.canonicalSerializations = 0;
        for (const record of obsArtifact.records) {
            Object.defineProperty(record.frontmatter, 'toJSON', {configurable: true, value() {
                canonicalSerializations++;
                return {...this};
            }});
        }
    }""")
    author = page.locator("[data-comment-author]")
    author.fill("Grace")
    author.blur()
    assert _counts(page) == [0, 0, 10]
    author.fill("Ada")
    author.blur()
    assert _counts(page) == [1, 0, 9]
    shell.locator("th").first.click()
    size = shell.get_by_role("spinbutton", name="Items per page")
    size.fill("1")
    size.blur()
    shell.get_by_role("button", name="Next table page").click()
    shell.get_by_role("button", name="Previous table page").click()
    shell.evaluate("""shell => shell.dispatchEvent(new CustomEvent(
        'obs-table-set-filter', {detail: {expression: 'status:open'}}
    ))""")
    assert _counts(page) == [1, 0, 9]
    assert _projections(page) == []
    assert page.evaluate("canonicalSerializations") == 0

    shell.locator(".data-table-options-toggle").click()
    shell.get_by_text("Query view", exact=True).click()
    editor = shell.locator(".data-table-query-editor")
    original = editor.input_value()
    editor.blur()
    assert _counts(page) == [1, 0, 9]
    assert _projections(page) == []
    shell.locator(".data-table-options-toggle").click()
    shell.get_by_text("Query view", exact=True).click()
    editor.fill("views: [")
    editor.blur()
    assert editor.get_attribute("aria-invalid") == "true"
    assert _counts(page) == [1, 0, 9]
    assert _projections(page) == []
    edited = page.evaluate("""text => {
        const definition = obsBases.parse(text);
        definition.filters = {and: ['kind == "finding"', 'title == "B"']};
        return obsBases.dump(definition);
    }""", original)
    editor.fill(edited)
    assert _counts(page) == [1, 0, 9]
    assert _projections(page) == []
    editor.blur()
    page.wait_for_function("""() =>
        document.querySelector('[data-review-summary-state="accepted"] [data-review-summary-count]')
            .textContent === '0'""")
    assert _counts(page) == [0, 0, 9]
    assert _projections(page) == ["register"]
    assert page.evaluate("canonicalSerializations") == 0
    assert page.evaluate("obsComments.data.reviews.length") == 1
    shell.locator(".data-table-options-toggle").click()
    shell.get_by_text("Query view", exact=True).click()
    shell.locator(".data-table-query-editor").fill(original)
    shell.locator(".data-table-query-editor").blur()
    page.wait_for_function("""() =>
        document.querySelector('[data-review-summary-state="accepted"] [data-review-summary-count]')
            .textContent === '1'""")
    assert _counts(page) == [1, 0, 9]
    assert _projections(page) == ["register"]
    assert row.get_attribute("data-review-state") == "accepted"
