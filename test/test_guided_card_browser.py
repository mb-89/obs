import os
from pathlib import Path
import re

import pytest
import yaml

from obs_html_interim.content import parse_manifest
from obs_html_interim.renderer import render_artifact
from pickers import choose_files


INSTRUCTIONS = (
    "1. Open the **source document**.\n"
    "2. Export it as XML ([export help](https://example.org/help)).\n"
    "3. Drop the exported file into this card."
)
RUNTIME = """obsArtifact.registerApplication({id: 'guided-fixture', actions: [{
    id: 'collect', accept: '.txt', help: 'Collect a replacement file.',
    handle: async ({noteId, file, values, signal, artifact}) => {
        globalThis.guidedCalls = [...(globalThis.guidedCalls || []), {noteId, name: file.name, values}];
        const text = await file.text();
        if (globalThis.failNextApply) throw new Error('Synthetic validation failure');
        const notes = artifact.canonicalNotes();
        const note = notes.find(candidate => candidate.sourcePath === noteId + '.md');
        note.frontmatter = {...note.frontmatter, ...values, payload: text};
        for (const field of [...Object.keys(values), 'payload']) delete note.frontmatterHtml?.[field];
        const staged = await artifact.stageCanonicalTransaction({
            expectedRevision: artifact.revision, notes, assetChanges: [],
        });
        if (signal.aborted) throw new DOMException('Cancelled', 'AbortError');
        staged.commit();
        return true;
    },
}]});"""
CARD = {
    "title": "Collect evidence", "subject": "label", "content": ["instructions"],
    "link": "sourceLink", "input": {"property": "description", "label": "Evidence description"},
    "submit": "Apply evidence",
}
UNAVAILABLE = "No source link to collect this evidence from."


def _write_fixture(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    spec = {
        "filters": 'kind == "evidence"',
        "properties": {
            "description": {"displayName": "Description"},
            "collect": {"displayName": "Actions", "obsHtml": {"icon": {
                "name": "reload", "label": "Collect evidence", "action": "collect",
                "helpProperty": "instructions", "card": CARD, "unavailable": UNAVAILABLE,
            }}},
        },
        "views": [{"type": "table", "order": ["label", "description", "payload", "collect"]}],
    }
    (root / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (root / "chapter.md").write_text(
        "# Evidence\n\n```base\n" + yaml.safe_dump(spec, sort_keys=False) + "```\n", encoding="utf-8",
    )
    (root / "evidence.md").write_text("---\n" + yaml.safe_dump({
        "kind": "evidence", "label": "Requirements export", "description": "Old description",
        "payload": "old bytes", "instructions": INSTRUCTIONS,
        "sourceLink": "[Open source system](https://example.org/source)",
    }, sort_keys=False) + "---\n", encoding="utf-8")
    (root / "self.md").write_text("---\n" + yaml.safe_dump({
        "kind": "evidence", "label": "This HTML", "description": "this file",
        "payload": "self bytes", "instructions": "Never regenerated from a source.",
    }, sort_keys=False) + "---\n", encoding="utf-8")
    return root / "manifest.md"


@pytest.fixture(scope="module")
def guided_artifact(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("guided")
    manifest = _write_fixture(root / "vault")
    artifact = root / "guided.html"
    artifact.write_text(render_artifact(
        manifest, parse_manifest(manifest), trusted_runtime_bundle=("guided-fixture", RUNTIME),
    ), encoding="utf-8")
    return artifact


@pytest.fixture(scope="module")
def guided_browser():
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native guided-card checks.")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=executable,
            headless=os.environ.get("OBS_HTML_TEST_HEADED") != "1",
        )
        try:
            yield browser
        finally:
            browser.close()


def _open(browser, artifact: Path, *, pip: bool = True, helper: bool = True):
    context = browser.new_context(viewport={"width": 1200, "height": 800})
    context.set_default_timeout(10000)
    context.route("https://example.org/**", lambda route: route.fulfill(
        status=200, content_type="text/html", body="<title>Source</title>Source system",
    ))
    script = ""
    if not pip:
        script += "delete window.documentPictureInPicture;"
    if not helper:
        script += "window.open = () => null;"
    if script:
        context.add_init_script(script)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(artifact.as_uri() + "#chapter")
    page.evaluate("obsHtmlReady")
    page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('chapter')")
    page.evaluate("obsArtifact.whenChapterReady()")
    return context, page, errors


def _model_note(page) -> dict:
    return page.evaluate("""() => obsArtifact.canonicalNotes()
        .find(note => note.sourcePath === 'evidence.md').frontmatter""")


def _wait_closed(page, window) -> None:
    for _ in range(200):
        if window.is_closed():
            return
        page.wait_for_timeout(50)
    raise AssertionError("The paired window stayed open.")


def _action(page):
    return page.get_by_role("button", name="Collect evidence", exact=True)


@pytest.mark.e2e
def test_inline_fallback_stages_then_applies_atomically(guided_browser, guided_artifact, tmp_path):
    from playwright.sync_api import expect

    context, page, errors = _open(guided_browser, guided_artifact, pip=False, helper=False)
    try:
        revision = page.evaluate("obsArtifact.revision")
        _action(page).click()
        card = page.locator("[data-guided-card]")
        expect(card).to_be_visible()
        expect(card.locator("[data-guided-card-retry]")).to_be_visible()
        expect(card.locator("[data-guided-card-message]")).to_contain_text("shown in this page")
        assert card.locator("[data-guided-card-content] > *").evaluate_all(
            "nodes => nodes.map(node => Object.keys(node.dataset)[0] || node.className)",
        )[:3] == ["guidedCardSource", "guidedCardSubject", "guidedCardInstructions"], \
            "the source link comes first, above the subject and instructions"
        expect(card.locator("[data-guided-card-subject]")).to_have_text("Requirements export")
        instructions = card.locator("[data-guided-card-instructions]")
        expect(instructions.locator("strong")).to_have_text("source document")
        assert instructions.evaluate("node => node.innerText").splitlines()[1].startswith("2. Export")
        expect(instructions.locator("a")).to_have_attribute("href", "https://example.org/help")
        source = card.locator("[data-guided-card-source] a")
        expect(source).to_have_attribute("href", "https://example.org/source")
        expect(source).to_have_attribute("target", "_blank")
        expect(source).to_contain_text("opens in a new tab")
        text = card.locator("[data-guided-card-text]")
        expect(text).to_have_value("Old description")
        expect(card.get_by_label("Evidence description")).to_have_count(1)
        assert card.evaluate("node => node.contains(document.activeElement)")

        card.locator("[data-guided-card-submit]").click()
        expect(card.locator("[data-guided-card-error]")).to_contain_text("Choose or drop a file")
        assert page.evaluate("globalThis.guidedCalls") is None

        # Keyboard activation of Choose file opens the real chooser; selecting only stages it.
        choosers = []
        page.on("filechooser", lambda chooser: choosers.append(chooser))
        page.wait_for_timeout(100)
        card.locator("[data-guided-card-choose]").focus()
        page.keyboard.press("Enter")
        for _ in range(100):
            if choosers:
                break
            page.wait_for_timeout(50)
        assert choosers, "Enter on Choose file must open the file chooser"
        choosers[0].set_files({"name": "new.txt", "mimeType": "text/plain", "buffer": b"new bytes"})
        expect(card.locator("[data-guided-card-staged]")).to_contain_text("new.txt")
        assert page.evaluate("obsArtifact.revision") == revision
        assert _model_note(page)["payload"] == "old bytes"

        text.fill("   ")
        card.locator("[data-guided-card-submit]").click()
        expect(card.locator("[data-guided-card-error]")).to_contain_text("Evidence description is required")
        expect(text).to_be_focused()
        text.fill("New description")
        text.press("Tab")
        expect(card.locator("[data-guided-card-submit]")).to_be_focused()
        page.keyboard.press("Enter")
        expect(card).to_have_count(0)
        assert page.evaluate("obsArtifact.revision") == revision + 1
        note = _model_note(page)
        assert (note["description"], note["payload"]) == ("New description", "new bytes")
        assert page.evaluate("globalThis.guidedCalls") == [{
            "noteId": "evidence", "name": "new.txt", "values": {"description": "New description"},
        }]
        table = page.locator("[data-active-chapter] table")
        expect(table).to_contain_text("New description")
        expect(table).to_contain_text("new bytes")
        expect(page.locator("[data-artifact-warning]")).to_be_visible()
        expect(_action(page)).to_be_focused()
        assert errors == []
    finally:
        context.close()


def test_failure_keeps_previous_state_and_card_open(guided_browser, guided_artifact):
    from playwright.sync_api import expect

    context, page, errors = _open(guided_browser, guided_artifact, pip=False, helper=False)
    try:
        page.evaluate("globalThis.failNextApply = true")
        revision = page.evaluate("obsArtifact.revision")
        _action(page).click()
        card = page.locator("[data-guided-card]")
        choose_files(page, card.locator("[data-guided-card-choose]").click,
                     {"name": "bad.txt", "mimeType": "text/plain", "buffer": b"bad"})
        card.locator("[data-guided-card-text]").fill("Should not apply")
        card.locator("[data-guided-card-submit]").click()
        expect(card.locator("[data-guided-card-error]")).to_contain_text("Synthetic validation failure")
        expect(card.locator("[data-guided-card-error]")).to_contain_text("previous state is unchanged")
        assert page.evaluate("obsArtifact.revision") == revision
        assert _model_note(page)["description"] == "Old description"
        expect(card.locator("[data-guided-card-submit]")).to_be_enabled()
        # A retry after fixing the cause applies the still-staged file.
        page.evaluate("globalThis.failNextApply = false")
        card.locator("[data-guided-card-submit]").click()
        expect(card).to_have_count(0)
        assert _model_note(page)["description"] == "Should not apply"
        assert errors == []
    finally:
        context.close()


@pytest.mark.e2e
def test_helper_fallback_drop_close_and_source_tab(guided_browser, guided_artifact):
    from playwright.sync_api import expect

    context, page, errors = _open(guided_browser, guided_artifact, pip=False)
    try:
        with context.expect_page() as opened:
            _action(page).click()
        helper = opened.value
        helper.wait_for_selector("[data-guided-card-content]")
        card = page.locator("[data-guided-card]")
        # The helper holds the only card; the page shows none.
        expect(card).to_have_count(0)
        assert helper.title() == "Collect evidence"
        assert helper.evaluate("document.documentElement.dataset.theme") == page.evaluate(
            "document.documentElement.dataset.theme")

        with context.expect_page() as source_opened:
            helper.locator("[data-guided-card-source] a").click()
        source = source_opened.value
        source.wait_for_load_state()
        assert source.evaluate("window.opener") is None

        helper.evaluate("""() => {
            const transfer = new DataTransfer();
            transfer.items.add(new File(['dropped bytes'], 'dropped.txt', {type: 'text/plain'}));
            const drop = document.querySelector('[data-guided-card-drop]');
            for (const type of ['dragover', 'drop']) {
                drop.dispatchEvent(new DragEvent(type, {bubbles: true, cancelable: true, dataTransfer: transfer}));
            }
        }""")
        expect(helper.locator("[data-guided-card-staged]")).to_contain_text("dropped.txt")
        assert _model_note(page)["payload"] == "old bytes"

        # Closing the helper card closes its window (after the evaluation returns) but never the source tab.
        helper.evaluate("() => setTimeout(() => document.querySelector('[data-guided-card-close]').click())")
        _wait_closed(page, helper)
        assert not source.is_closed()
        assert _model_note(page)["payload"] == "old bytes"

        # A natively closed helper ends the session; the row action opens a fresh one.
        with context.expect_page() as reopened:
            _action(page).click()
        second = reopened.value
        second.wait_for_selector("[data-guided-card-content]")
        second.close()
        expect(card).to_have_count(0)

        # Applying from the helper commits and closes it.
        with context.expect_page() as third_opened:
            _action(page).click()
        third = third_opened.value
        third.wait_for_selector("[data-guided-card-content]")
        choose_files(third, third.locator("[data-guided-card-choose]").click,
                     {"name": "helper.txt", "mimeType": "text/plain", "buffer": b"helper bytes"})
        third.locator("[data-guided-card-text]").fill("From helper")
        third.locator("[data-guided-card-submit]").click()
        _wait_closed(page, third)
        expect(card).to_have_count(0)
        assert _model_note(page)["payload"] == "helper bytes"
        assert not source.is_closed()
        assert errors == []
    finally:
        context.close()


@pytest.mark.e2e
def test_picture_in_picture_preferred_as_the_only_card(guided_browser, guided_artifact):
    from playwright.sync_api import expect

    context, page, errors = _open(guided_browser, guided_artifact)
    try:
        if not page.evaluate("typeof window.documentPictureInPicture?.requestWindow === 'function'"):
            pytest.skip("This browser build exposes no Document Picture-in-Picture API.")
        _action(page).click()
        card = page.locator("[data-guided-card]")
        for _ in range(200):
            if page.evaluate("Boolean(documentPictureInPicture.window)"):
                break
            if card.count() or len(context.pages) > 1:
                pytest.skip("Document Picture-in-Picture was refused here; the card fell back.")
            page.wait_for_timeout(50)
        else:
            pytest.skip("Document Picture-in-Picture did not open here.")
        expect(card).to_have_count(0)
        pip = "documentPictureInPicture.window.document"
        assert page.evaluate(f"{pip}.querySelector('[data-guided-card-text]').value") == "Old description"
        assert page.evaluate(f"{pip}.querySelector('[data-guided-card-source] a').target") == "_blank"
        page.evaluate(f"""() => {{
            const document = {pip};
            const transfer = new DataTransfer();
            transfer.items.add(new File(['pip bytes'], 'pip.txt', {{type: 'text/plain'}}));
            document.querySelector('[data-guided-card-drop]').dispatchEvent(
                new DragEvent('drop', {{bubbles: true, cancelable: true, dataTransfer: transfer}}));
            document.querySelector('[data-guided-card-text]').value = 'From PiP';
            document.querySelector('[data-guided-card-submit]').click();
        }}""")
        expect(card).to_have_count(0)
        page.wait_for_function("!documentPictureInPicture.window")
        assert _model_note(page)["payload"] == "pip bytes"
        assert _model_note(page)["description"] == "From PiP"

        _action(page).click()
        page.wait_for_function("Boolean(documentPictureInPicture.window)")
        page.evaluate("documentPictureInPicture.window.close()")
        expect(card).to_have_count(0)
        _action(page).click()
        page.wait_for_function("Boolean(documentPictureInPicture.window)")
        expect(card).to_have_count(0)
        page.evaluate(f"{pip}.querySelector('[data-guided-card-close]').click()")
        page.wait_for_function("!documentPictureInPicture.window")
        assert errors == []
    finally:
        context.close()


def test_mocked_floating_window_is_the_only_card(guided_browser, guided_artifact):
    """A refused floating window falls back inline; once it opens, the page shows no card."""
    from playwright.sync_api import expect

    context, page, errors = _open(guided_browser, guided_artifact, pip=False)
    try:
        # Stand in for Document Picture-in-Picture with an ordinary popup the test can drive;
        # with no helper either, a refused request can only fall back inline.
        page.evaluate("""() => {
            globalThis.refusePip = true;
            const popup = window.open.bind(window);
            window.open = () => null;
            Object.defineProperty(window, 'documentPictureInPicture', {configurable: true, value: {
                requestWindow: ({width, height}) => globalThis.refusePip
                    ? Promise.reject(new DOMException('Refused', 'NotAllowedError'))
                    : Promise.resolve(popup('', '_blank', `popup,width=${width},height=${height}`)),
            }});
        }""")
        card = page.locator("[data-guided-card]")
        _action(page).click()
        expect(card).to_have_count(1)
        expect(card).to_be_visible()
        expect(card.locator("[data-guided-card-message]")).to_contain_text("shown in this page")
        expect(card.locator("[data-guided-card-content]")).to_have_count(1)

        page.evaluate("globalThis.refusePip = false")
        with context.expect_page() as opened:
            card.locator("[data-guided-card-retry]").click()
        floating = opened.value
        floating.wait_for_selector("[data-guided-card-content] [data-guided-card-text]")
        expect(card).to_have_count(0)
        assert floating.title() == "Collect evidence"
        assert floating.locator("[data-guided-card-close]").count() == 1

        floating.close()
        expect(card).to_have_count(0)
        with context.expect_page() as reopened:
            _action(page).click()
        again = reopened.value
        again.wait_for_selector("[data-guided-card-content] [data-guided-card-text]")
        expect(card).to_have_count(0)
        # Cancel closes the window itself, so click it after the evaluation returns.
        again.evaluate("() => setTimeout(() => document.querySelector('[data-guided-card-cancel]').click())")
        _wait_closed(page, again)
        expect(card).to_have_count(0)
        assert errors == []
    finally:
        context.close()


def test_card_is_transient_and_hidden_in_print(guided_browser, guided_artifact, tmp_path):
    from playwright.sync_api import expect

    context, page, errors = _open(guided_browser, guided_artifact, pip=False, helper=False)
    try:
        _action(page).click()
        card = page.locator("[data-guided-card]")
        expect(card).to_be_visible()
        saved = page.evaluate("obsComments.reviewedHtml()")
        assert not re.search(r"<section[^>]*data-guided-card", saved)
        page.emulate_media(media="print")
        expect(card).to_be_hidden()
        page.emulate_media(media="screen")
        card.locator("[data-guided-card-cancel]").click()
        expect(card).to_have_count(0)
        assert errors == []
    finally:
        context.close()


def test_row_without_source_link_gets_disabled_action_and_no_card(guided_browser, guided_artifact):
    from playwright.sync_api import expect

    context, page, errors = _open(guided_browser, guided_artifact, pip=False, helper=False)
    try:
        actions = page.locator("[data-active-chapter] table .data-table-icon-action")
        expect(actions).to_have_count(2)
        assert actions.evaluate_all("nodes => nodes.map(node => node.textContent)") == ["↻", "↻"]
        unavailable = page.get_by_role("button", name=f"Collect evidence: {UNAVAILABLE}", exact=True)
        expect(unavailable).to_be_disabled()
        expect(unavailable).to_have_attribute("title", f"Collect evidence: {UNAVAILABLE}")
        expect(unavailable).to_have_attribute("data-unavailable", "")
        assert unavailable.get_attribute("data-artifact-action") is None
        assert unavailable.locator("[data-icon]").get_attribute("data-icon-state") == "inactive"
        expect(_action(page)).to_be_enabled()
        assert _action(page).locator("[data-icon]").get_attribute("data-icon-state") == "active"
        unavailable.evaluate("node => node.click()")
        expect(page.locator("[data-guided-card]")).to_have_count(0)
        expect(page.locator("[data-application-runtime-error]")).to_have_count(0)
        assert errors == []
    finally:
        context.close()


def test_apply_records_change_time_in_saved_html(guided_browser, guided_artifact, tmp_path):
    from playwright.sync_api import expect

    context, page, errors = _open(guided_browser, guided_artifact, pip=False, helper=False)
    try:
        timestamp = "JSON.parse(obsArtifact.serializeModel()).document.generation.timestamp"
        built = page.evaluate(timestamp)
        page.clock.set_fixed_time("2031-02-03T04:05:06Z")
        _action(page).click()
        card = page.locator("[data-guided-card]")
        card.locator("[data-guided-card-file]").set_input_files(
            files=[{"name": "new.txt", "mimeType": "text/plain", "buffer": b"changed"}])
        card.locator("[data-guided-card-submit]").click()
        expect(card).to_have_count(0)
        changed = "2031-02-03T04:05:06.000+00:00"
        assert built != changed
        assert page.evaluate(timestamp) == changed
        saved = tmp_path / "saved.html"
        saved.write_text(page.evaluate("obsComments.reviewedHtml()"), encoding="utf-8")
        page.goto(saved.as_uri())
        page.evaluate("obsHtmlReady")
        assert page.evaluate(timestamp) == changed
        assert errors == []
    finally:
        context.close()


@pytest.mark.parametrize("old, new, match", [
    ("submit: Apply evidence", "submitt: x", "collect"),
    ("unavailable: No source link", "help: No source link", "collect"),
])
def test_invalid_card_declaration_is_rejected(tmp_path, old, new, match):
    from obs_html_interim.content import ContentError

    manifest = _write_fixture(tmp_path)
    chapter = tmp_path / "chapter.md"
    source = chapter.read_text(encoding="utf-8")
    assert old in source
    chapter.write_text(source.replace(old, new), encoding="utf-8")
    with pytest.raises(ContentError, match=match):
        render_artifact(manifest, parse_manifest(manifest))
