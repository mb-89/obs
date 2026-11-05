import json
import os
import re

import pytest

from obs_html_interim.cli import main
from obs_html_interim.artifact_data import decode_artifact_data, encode_artifact_data


@pytest.fixture
def reviewed_filter_page(tmp_path):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for reviewed-filter checks.")
    from playwright.sync_api import sync_playwright

    vault = tmp_path / "vault"
    vault.mkdir()
    cards = {
        "version": 1,
        "cards": [{"title": "Paths", "body": "", "metrics": [{
            "label": "Paths", "where": [{"field": "kind", "equals": "path"}],
        }]}],
    }
    (vault / "manifest.md").write_text(
        "- [[one]]\n- [[two]]\n\n```cards\n" + json.dumps(cards) + "\n```\n",
        encoding="utf-8",
    )
    for slug, status in [("one", "finding-at-eit"), ("two", "covered")]:
        (vault / f"{slug}.md").write_text(
            "---\nkind: path\nstatus: " + status + "\nexplanation: Original\n---\n"
            f"# {slug.title()}\n\nReviewable text.\n\n"
            "```property-editor\nversion: 1\nfield: explanation\nlabel: Explanation\n```\n\n"
            "```base\nobsHtml: {records: note}\nviews:\n"
            "  - type: table\n    order: [title, status, explanation]\n```\n",
            encoding="utf-8",
        )
    artifact = tmp_path / "artifact.html"
    args = ["--source", str(vault), "--output", str(artifact)]
    assert main([*args, "--check"]) == 0
    assert not artifact.exists()
    assert main(args) == 0
    assert "readerState" not in decode_artifact_data(artifact.read_text(encoding="utf-8"))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        context = browser.new_context(accept_downloads=True, viewport={"width": 1440, "height": 900})
        context.add_init_script("delete window.showSaveFilePicker")
        page = context.new_page()
        page.set_default_timeout(5000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            yield page, artifact
            assert errors == []
        finally:
            browser.close()


@pytest.mark.parametrize(
    "mode", ["active", "invalid-draft", "cleared", "closed", "whitespace", "invalid-unfiltered"],
)
def test_native_reviewed_copy_restores_applied_filter_without_dirtying_review(
    tmp_path, reviewed_filter_page, mode,
):
    from playwright.sync_api import expect

    page, artifact = reviewed_filter_page
    page.goto(artifact.as_uri())
    query = "status:finding-at-eit"
    input_box = page.locator("[data-filter-input]")
    filter_bar = page.locator('[data-bar="filter"]')
    metric = page.locator("[data-record-card] .record-metric-value strong")
    guidance = page.locator("[data-review-save-guidance]")
    expect(input_box).to_have_value("")
    expect(filter_bar).to_be_hidden()
    expect(metric).to_have_text("2")
    page.evaluate("obsArtifact.openBar('filter')")
    input_box.fill(query)
    expect(metric).to_have_text("1")
    assert not page.evaluate("""() => {
        const event = new Event('beforeunload', {cancelable:true});
        return window.dispatchEvent(event) && !event.defaultPrevented;
    }""")
    expect(guidance).to_have_attribute("data-dirty", "false")
    if mode == "invalid-draft":
        input_box.fill("status: /[")
        expect(page.locator("[data-filter-status]")).to_have_text("still typing")
        expect(metric).to_have_text("1")
    elif mode == "invalid-unfiltered":
        input_box.fill("")
        input_box.fill("status: /[")
        expect(page.locator("[data-filter-status]")).to_have_text("still typing")
        expect(metric).to_have_text("2")
    elif mode == "cleared":
        input_box.fill("")
    elif mode == "whitespace":
        input_box.fill("   ")
    elif mode == "closed":
        page.locator("[data-menu-button]").click()
        page.locator('[data-dock-bar="filter"][data-dock-direction="right"]').click()
        expect(filter_bar).to_be_hidden()
        page.keyboard.press("Escape")
    expected = query if mode in {"active", "invalid-draft"} else ""
    expect(guidance).to_have_attribute("data-dirty", "false")
    page.evaluate("obsArtifact.openBar('settings')")
    page.locator("[data-theme-select]").select_option("dark")
    page.locator("[data-pages-toggle]").uncheck()
    page.evaluate("obsArtifact.openBar('comments')")
    with page.expect_download() as download:
        page.locator("[data-comment-save]").click()
    saved = tmp_path / "reviewed.html"
    download.value.save_as(saved)
    page.goto(saved.as_uri())
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    expect(page.locator("html")).to_have_class("paged-mode")
    expect(input_box).to_have_value(expected)
    expect(metric).to_have_text("1" if expected else "2")
    if expected:
        expect(filter_bar).to_be_visible()
        expect(page.locator("[data-filter-warning]")).to_be_visible()
        expect(page.locator("[data-filter-warning]")).to_contain_text("1/2 chapters")
        assert page.locator("[data-menu-button]").get_attribute("data-filter-active") is None
        expect(page.locator('[data-dock-bar="filter"][data-dock-direction="right"]')).to_have_attribute(
            "aria-pressed", "true",
        )
    else:
        expect(filter_bar).to_be_hidden()
    expect(guidance).to_have_attribute("data-dirty", "false")
    assert page.evaluate("""() => {
        const event = new Event('beforeunload', {cancelable:true});
        return window.dispatchEvent(event) && !event.defaultPrevented;
    }""")
    page.evaluate("obsArtifact.activateChapter('one')")
    assert page.evaluate(
        "obsArtifact.records.filter(record => record.frontmatter.kind === 'path')"
        ".filter(obsArtifact.matchesFilter).length",
    ) == (1 if expected else 2)
    table = page.locator('.paged-reader [data-data-table="one-base-1"]')
    expect(table.locator("tbody tr[data-row-key]")).to_have_count(2)
    editor = page.locator(".paged-reader [data-property-editor]")
    editor.fill("Edited after reopen")
    editor.press("Tab")
    expect(guidance).to_have_attribute("data-dirty", "true")
    page.evaluate("""() => {
        obsComments.data.reviewers.push('Reader');
        obsComments.data.annotations.push({id:'filter-comment', author:'Reader', text:'Keep filter review',
          status:'open', replies:[], target:{chapter:'one',quote:'Reviewable text.',start:0,end:16}});
        obsComments.data.reviews.push({chapter:'one',item:'item-1',reviewer:'Reader',state:'accepted'});
        obsArtifact.openBar('comments');
    }""")
    with page.expect_download() as download:
        page.locator("[data-comment-save]").click()
    second = tmp_path / "reviewed-twice.html"
    download.value.save_as(second)
    page.goto(second.as_uri())
    expect(input_box).to_have_value(expected)
    assert page.evaluate(
        "obsArtifact.records.find(record => record.slug === 'one').frontmatter.explanation",
    ) == "Edited after reopen"
    assert page.evaluate("obsComments.data.annotations[0].text") == "Keep filter review"
    assert page.evaluate("obsComments.data.reviews[0].state") == "accepted"
    expect(guidance).to_have_attribute("data-dirty", "false")
    page.evaluate("obsArtifact.activateChapter('home'); obsArtifact.openBar('filter')")
    input_box.fill("status:covered")
    expect(metric).to_have_text("1")
    expect(guidance).to_have_attribute("data-dirty", "false")
    assert not page.evaluate("""() => {
        const event = new Event('beforeunload', {cancelable:true});
        return window.dispatchEvent(event) && !event.defaultPrevented;
    }""")
    page.evaluate("obsArtifact.openBar('comments')")
    with page.expect_download() as download:
        page.locator("[data-comment-save]").click()
    third = tmp_path / "reviewed-new-query.html"
    download.value.save_as(third)
    page.goto(third.as_uri())
    expect(input_box).to_have_value("status:covered")
    expect(metric).to_have_text("1")
    expect(guidance).to_have_attribute("data-dirty", "false")
    input_box.fill("")
    expect(metric).to_have_text("2")
    expect(guidance).to_have_attribute("data-dirty", "false")


def test_native_review_filter_restores_after_review_fields_initialize(reviewed_filter_page, tmp_path):
    from playwright.sync_api import expect

    page, artifact = reviewed_filter_page
    page.goto(artifact.as_uri() + "#one")
    page.evaluate("obsArtifact.openBar('comments')")
    page.locator(".paged-reader .review-action--accept").first.click()
    page.evaluate("obsArtifact.openBar('filter')")
    page.locator("[data-filter-input]").fill("review: /^accepted$/")
    assert page.evaluate("obsArtifact.records.filter(obsArtifact.matchesFilter).map(record => record.slug)") == ["one"]
    page.evaluate("obsArtifact.openBar('comments')")
    with page.expect_download() as download:
        page.locator("[data-comment-save]").click()
    saved = tmp_path / "review-filter.html"
    download.value.save_as(saved)
    page.goto(saved.as_uri())
    expect(page.locator("[data-filter-input]")).to_have_value("review: /^accepted$/")
    expect(page.locator('[data-bar="filter"]')).to_be_visible()
    assert page.evaluate("obsArtifact.records.filter(obsArtifact.matchesFilter).map(record => record.slug)") == ["one"]
    expect(page.locator("[data-review-save-guidance]")).to_have_attribute("data-dirty", "false")


def test_native_invalid_stored_filter_is_visible_with_error(reviewed_filter_page, tmp_path):
    from playwright.sync_api import expect

    page, artifact = reviewed_filter_page
    html = artifact.read_text(encoding="utf-8")
    pattern = r'(<script[^>]*data-artifact-data[^>]*>)(.*?)(</script>)'
    data = decode_artifact_data(html)
    data["readerState"] = {"filterExpression": "status: /["}
    invalid = tmp_path / "invalid-saved-filter.html"
    invalid.write_text(
        re.sub(pattern, lambda match: encode_artifact_data(data), html, count=1, flags=re.S),
        encoding="utf-8",
    )
    page.goto(invalid.as_uri())
    expect(page.locator('[data-bar="filter"]')).to_be_visible()
    expect(page.locator("[data-filter-input]")).to_have_value("status: /[")
    expect(page.locator("[data-filter-status]")).to_have_text("still typing")
    expect(page.locator("[data-review-save-guidance]")).to_have_attribute("data-dirty", "false")


def test_native_saved_filter_controls_rebuild_once(reviewed_filter_page, tmp_path):
    from playwright.sync_api import expect

    page, artifact = reviewed_filter_page
    vault = artifact.parent / "vault"
    (vault / "cfg.json").write_text(
        json.dumps({"schemaVersion": 1, "artifact": {"facetDistinctRatio": 1}}), encoding="utf-8",
    )
    assert main(["--source", str(vault), "--output", str(artifact)]) == 0
    page.goto(artifact.as_uri())
    page.evaluate("obsArtifact.openBar('filter')")
    presets = page.locator("[data-filter-preset]")
    fields = page.locator("[data-filter-fields] .filter-field")
    preset_labels = presets.all_text_contents()
    field_labels = fields.locator(".filter-field-button").all_text_contents()
    assert preset_labels and field_labels
    page.locator("[data-filter-input]").fill("status:finding-at-eit")
    for index in range(2):
        page.evaluate("obsArtifact.openBar('comments')")
        with page.expect_download() as download:
            page.locator("[data-comment-save]").click()
        saved = tmp_path / f"controls-{index}.html"
        download.value.save_as(saved)
        page.goto(saved.as_uri())
        expect(page.locator('[data-bar="filter"]')).to_be_visible()
        expect(presets).to_have_count(len(preset_labels))
        expect(fields).to_have_count(len(field_labels))
        assert presets.all_text_contents() == preset_labels
        assert fields.locator(".filter-field-button").all_text_contents() == field_labels
    presets.first.click()
    expect(page.locator("[data-filter-input]")).to_have_value(
        page.evaluate("obsArtifact.filterPresets[0].expression"),
    )
    expect(page.locator("[data-review-save-guidance]")).to_have_attribute("data-dirty", "false")
