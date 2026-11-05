"""Reference notes in the reader: hover card per kind, one floating window, one overlay system.

Owners: artifact-ui.md "Overlays", "Floating window", "Link hover card";
input-model.md "Reference notes and link text".
"""
import os
from pathlib import Path

import pytest
import yaml

from obs_html.content import parse_manifest
from obs_html.renderer import render_artifact
from pickers import choose_files
from test_guided_card_browser import CARD, RUNTIME, UNAVAILABLE

URL = "https://webstore.iec.ch/publication/1234"
pytestmark = pytest.mark.browser


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fixture(root: Path) -> Path:
    evidence = {
        "filters": 'kind == "evidence"',
        "properties": {"collect": {"displayName": "Actions", "obsHtml": {"icon": {
            "name": "reload", "label": "Collect evidence", "action": "collect",
            "help": "Collect a replacement file.", "card": CARD, "unavailable": UNAVAILABLE,
        }}}},
        "views": [{"type": "table", "order": ["label", "collect"]}],
    }
    _write(root / "manifest.md", "- [[chapter]]\n- [[other]]\n")
    _write(root / "chapter.md", "# Chapter\n\nThe limit follows [[iec]], see [[iec|the standard]] and "
           "[IEC 1234](iec.md). The gap is [[q_gap]]. Errors add as [[RSS]]. #mark/open_point/scope\n\n"
           "Also see [[other]].\n\n```base\n" + yaml.safe_dump(evidence, sort_keys=False) + "```\n")
    _write(root / "other.md", "# Other\n\nIn the contents.\n")
    _write(root / "iec.md", f"---\ntitle: IEC 1234\nurl: {URL}\n"
           "description: Safety of medical electrical equipment.\naccessed: 2026-10-29\n---\n"
           "Cited for the [[frame]]; compare [[other]].\n")
    _write(root / "frame.md", "# Frame drawing\n\nThe frame holds the node.\n")
    _write(root / "q_gap.md", "---\nkind: quantity\ntitle: Gap\naliases: [q_gap]\nvalue: 2\nunit: mm\n"
           "source: '[[iec]]'\n---\nMeasured on the frame drawing.\n")
    _write(root / "rss.md", "---\nkind: glossary\nterm: RSS\ndefinition: Root sum of squares.\n---\n")
    _write(root / "evidence.md", "---\n" + yaml.safe_dump({
        "kind": "evidence", "label": "Requirements export", "description": "Old description",
        "payload": "old bytes", "instructions": "Export it.",
        "sourceLink": "[Open source system](https://example.org/source)",
    }, sort_keys=False) + "---\n")
    return root / "manifest.md"


@pytest.fixture(scope="module")
def artifact(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("reference-items")
    manifest = _fixture(root / "vault")
    output = root / "reference-items.html"
    output.write_text(render_artifact(
        manifest, parse_manifest(manifest), trusted_runtime_bundle=("guided-fixture", RUNTIME),
    ), encoding="utf-8")
    return output


@pytest.fixture(scope="module")
def browser():
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native reference-item checks.")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(executable_path=executable, headless=True)
        try:
            yield instance
        finally:
            instance.close()


def _open(browser, artifact: Path, *, helper: bool = False):
    context = browser.new_context(viewport={"width": 1200, "height": 800})
    context.set_default_timeout(10000)
    for pattern in ("https://webstore.iec.ch/**", "https://example.org/**"):
        context.route(pattern, lambda route: route.fulfill(status=200, content_type="text/html",
                                                           body="<title>External</title>External"))
    script = "delete window.documentPictureInPicture;" + ("" if helper else "window.open = () => null;")
    context.add_init_script(script)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: message.type == "error" and errors.append(message.text))
    page.goto(artifact.as_uri() + "#chapter")
    page.evaluate("obsHtmlReady")
    page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('chapter')")
    page.evaluate("obsArtifact.whenChapterReady()")
    return context, page, errors


def _prose(page, href: str, index: int = 0):
    return page.locator(f"[data-chapter-body] p a[href='{href}']").nth(index)


def test_hover_card_shows_per_kind_content_and_the_only_external_link(browser, artifact):
    from playwright.sync_api import expect

    context, page, errors = _open(browser, artifact)
    try:
        card = page.locator("#hover-card")
        assert page.locator(f"[data-chapter-body] a[href^='http']").count() == 0
        assert _prose(page, "#iec").inner_text() == "IEC 1234"
        _prose(page, "#iec").hover()
        expect(card).to_be_visible()
        expect(card.locator(".hover-card-title")).to_have_text("IEC 1234")
        expect(card).to_contain_text("Safety of medical electrical equipment.")
        expect(card).to_contain_text("Accessed 2026-10-29")
        external = card.locator("a[href^='http']")
        expect(external).to_have_count(1)
        expect(external).to_have_attribute("href", URL)
        expect(external).to_have_attribute("target", "_blank")
        expect(external).to_contain_text("opens in a new tab")
        with context.expect_page() as opened:
            external.click()
        tab = opened.value
        tab.wait_for_load_state()
        assert tab.url == URL and tab.evaluate("window.opener") is None
        tab.close()

        # The same reference through its other two links shows the same card and URL.
        for index, href in ((1, "#iec"), (2, "#iec")):
            page.locator("[data-chapter-body] p a[href='#iec']").nth(index).hover()
            expect(card.locator("a[href^='http']")).to_have_attribute("href", URL)

        _prose(page, "#q-gap").hover()
        expect(card.locator(".hover-card-title")).to_have_text("Gap")
        expect(card.locator(".hover-card-value")).to_have_text("2 mm")
        expect(card).to_contain_text("Measured on the frame drawing.")
        expect(card).to_contain_text("Source: IEC 1234")
        expect(card.locator("a[href^='http']")).to_have_count(0)

        _prose(page, "#rss").hover()
        expect(card.locator(".hover-card-title")).to_have_text("RSS")
        expect(card).to_contain_text("Root sum of squares.")

        page.locator("[data-chapter-body] a.semantic-mark-icon").hover()
        expect(card.locator(".hover-card-title")).to_have_text("open point: scope")
        expect(card).to_contain_text("The limit follows")
        expect(card.get_by_role("link", name="Chapter", exact=True)).to_have_attribute("data-source-chapter", "chapter")

        _prose(page, "#other").hover()
        expect(card.locator(".hover-card-title")).to_have_text("Other")
        expect(card).to_contain_text("In the contents.")
        assert page.locator(".hover-card").count() == 1
        assert errors == []
    finally:
        context.close()


def test_hover_card_stays_until_escape_click_outside_or_another_hover(browser, artifact):
    from playwright.sync_api import expect

    context, page, errors = _open(browser, artifact)
    try:
        card = page.locator("#hover-card")
        link = _prose(page, "#iec")
        link.hover()
        expect(card).to_be_visible()
        page.mouse.move(1150, 750)
        page.wait_for_timeout(600)
        expect(card).to_be_visible()
        assert link.get_attribute("aria-describedby") == "hover-card"

        page.keyboard.press("Escape")
        expect(card).to_be_hidden()
        assert link.get_attribute("aria-describedby") is None

        link.hover()
        expect(card).to_be_visible()
        page.locator("[data-chapter-body] h1").click()
        expect(card).to_be_hidden()

        # The persistent card sits below its trigger, so hover a lower link first, then one above it.
        lower = _prose(page, "#other")
        lower.hover()
        expect(card.locator(".hover-card-title")).to_have_text("Other")
        handle = card.element_handle()
        link.hover()
        expect(card.locator(".hover-card-title")).to_have_text("IEC 1234")
        assert card.element_handle().evaluate("(node, previous) => node === previous", handle)
        assert lower.get_attribute("aria-describedby") is None

        # Passing over a link without resting on it shows nothing new.
        page.keyboard.press("Escape")
        _prose(page, "#q-gap").hover()
        page.mouse.move(1150, 750)
        page.wait_for_timeout(600)
        expect(card).to_be_hidden()

        # Scrolling keeps the card until its trigger leaves the view.
        link.hover()
        expect(card).to_be_visible()
        page.evaluate("""() => {
            const scroll = document.querySelector('[data-chapter-scroll]');
            scroll.append(Object.assign(document.createElement('div'), {style: 'height: 3000px'}));
            scroll.scrollTop = 4;
            scroll.dispatchEvent(new Event('scroll'));
        }""")
        expect(card).to_be_visible()
        page.evaluate("""() => {
            const scroll = document.querySelector('[data-chapter-scroll]');
            scroll.scrollTop = scroll.scrollHeight;
            scroll.dispatchEvent(new Event('scroll'));
        }""")
        expect(card).to_be_hidden()
        assert errors == []
    finally:
        context.close()


def test_every_hover_trigger_uses_the_one_card(browser, artifact):
    """Overlay tier 1 has one owner: no CSS tooltips, no per-feature popovers, no explanation titles."""
    from playwright.sync_api import expect

    context, page, errors = _open(browser, artifact)
    try:
        assert page.locator("[role='tooltip'], .query-tooltip, .storage-tooltip").count() == 0
        popovers = page.evaluate("[...document.querySelectorAll('[popover]')].map(node => node.id || node.className)")
        assert "hover-card" in popovers
        assert all(name == "hover-card" or "menu" in name or "options" in name or "filter-values" in name
                   for name in popovers), popovers
        explanations = page.evaluate("""[...document.querySelectorAll('[title]:not(:disabled)')]
            .map(node => node.getAttribute('title')).filter(text => /[.;]\\s|\\.$/.test(text))""")
        assert explanations == []
        card = page.locator("#hover-card")
        triggers = page.evaluate("""() => [...document.querySelectorAll('[data-hover-help]')]
            .map(node => node.dataset.hoverHelp)""")
        assert any("Bare terms search all fields" in text for text in triggers)
        assert any("cannot be remembered" in text for text in triggers)
        # Bars may be parked; keyboard focus opens the card like hover does.
        page.locator("[data-hover-help^='Bare terms']").first.evaluate(
            "node => node.dispatchEvent(new FocusEvent('focusin', {bubbles: true}))")
        expect(card).to_be_visible()
        expect(card).to_contain_text("Bare terms search all fields")
        page.keyboard.press("Escape")
        action = page.get_by_role("button", name="Collect evidence", exact=True)
        action.hover()
        expect(card).to_be_visible()
        expect(card).to_contain_text("Collect a replacement file.")
        _prose(page, "#iec").hover()
        expect(card).to_contain_text("IEC 1234")
        assert page.locator(".hover-card").count() == 1
        assert errors == []
    finally:
        context.close()


def test_off_contents_note_shows_in_the_floating_window_with_history(browser, artifact):
    from playwright.sync_api import expect

    context, page, errors = _open(browser, artifact)
    try:
        window = page.locator("[data-guided-card]")
        _prose(page, "#iec").click()
        assert page.evaluate("location.hash") == "#chapter"
        expect(page.locator("[data-active-chapter]")).to_have_attribute("data-chapter", "chapter")
        expect(window.locator("[data-guided-card-use]")).to_have_text("Context")
        expect(window.locator(".guided-card-title")).to_have_text("IEC 1234")
        expect(window).to_contain_text("Cited for the Frame drawing")
        back, forward = window.locator("[data-guided-card-back]"), window.locator("[data-guided-card-forward]")
        expect(back).to_be_disabled()

        window.locator(".guided-card-note a[href='#frame']").click()
        expect(window.locator(".guided-card-title")).to_have_text("Frame drawing")
        expect(page.locator("[data-guided-card]")).to_have_count(1)
        back.click()
        expect(window.locator(".guided-card-title")).to_have_text("IEC 1234")
        forward.click()
        expect(window.locator(".guided-card-title")).to_have_text("Frame drawing")
        back.click()

        # An unfinished evidence collection joins the same window and history and survives Back.
        page.get_by_role("button", name="Collect evidence", exact=True).click()
        expect(window.locator("[data-guided-card-use]")).to_have_text("Evidence collection")
        choose_files(page, window.locator("[data-guided-card-choose]").click,
                     {"name": "draft.txt", "mimeType": "text/plain", "buffer": b"draft"})
        window.locator("[data-guided-card-text]").fill("Unfinished")
        back.click()
        expect(window.locator("[data-guided-card-use]")).to_have_text("Context")
        forward.click()
        expect(window.locator("[data-guided-card-use]")).to_have_text("Evidence collection")
        expect(window.locator("[data-guided-card-staged]")).to_contain_text("draft.txt")
        expect(window.locator("[data-guided-card-text]")).to_have_value("Unfinished")
        back.click()

        # A link inside the window to a note in the contents navigates the page; the window stays.
        window.locator(".guided-card-note a[href='#other']").click()
        expect(page.locator("[data-active-chapter]")).to_have_attribute("data-chapter", "other")
        expect(window.locator(".guided-card-title")).to_have_text("IEC 1234")
        window.locator("[data-guided-card-close]").click()
        expect(page.locator("[data-guided-card]")).to_have_count(0)
        assert page.evaluate("obsArtifact.canonicalNotes().find(n => n.sourcePath === 'evidence.md')"
                             ".frontmatter.payload") == "old bytes"
        assert errors == []
    finally:
        context.close()


def test_open_helper_window_is_reused_in_place(browser, artifact):
    from playwright.sync_api import expect

    context, page, errors = _open(browser, artifact, helper=True)
    try:
        with context.expect_page() as opened:
            _prose(page, "#iec").click()
        helper = opened.value
        helper.wait_for_selector("[data-guided-card-content]")
        assert helper.title() == "IEC 1234"
        expect(helper.locator("[data-guided-card-use]")).to_have_text("Context")
        pages = len(context.pages)
        _prose(page, "#q-gap").click()
        expect(helper.locator(".guided-card-title")).to_have_text("Gap")
        assert len(context.pages) == pages and not helper.is_closed()
        expect(page.locator("[data-guided-card]")).to_have_count(0)
        helper.locator("[data-guided-card-back]").click()
        expect(helper.locator(".guided-card-title")).to_have_text("IEC 1234")
        helper.evaluate("() => setTimeout(() => document.querySelector('[data-guided-card-close]').click())")
        for _ in range(100):
            if helper.is_closed():
                break
            page.wait_for_timeout(50)
        assert helper.is_closed()
        assert errors == []
    finally:
        context.close()


@pytest.fixture(scope="module")
def spec_artifact(tmp_path_factory) -> Path:
    from obs_html.cli import main

    output = tmp_path_factory.mktemp("spec") / "spec.html"
    spec = Path(__file__).resolve().parents[1] / "spec"
    assert main(["--source", str(spec), "--execute-commands", "--output", str(output)]) == 0
    return output


def test_spec_build_hovers_use_the_one_card_without_console_errors(browser, spec_artifact):
    """Every hover trigger in the spec build resolves through the one hover-card owner."""
    from playwright.sync_api import expect

    context = browser.new_context(viewport={"width": 1200, "height": 800})
    context.set_default_timeout(15000)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: message.type == "error" and errors.append(message.text))
    try:
        page.goto(spec_artifact.as_uri())
        page.evaluate("obsHtmlReady")
        page.evaluate("obsPages.setPaged(false)")
        for slug in page.evaluate("JSON.parse(document.querySelector('[data-artifact-data]').textContent).toc"):
            page.evaluate(f"obsArtifact.activateChapter({slug!r})")
            page.evaluate("obsArtifact.whenChapterReady()")
        assert errors == []
        assert page.locator("[role='tooltip'], .query-tooltip, .storage-tooltip").count() == 0
        assert page.evaluate("""[...document.querySelectorAll('[title]:not(:disabled)')]
            .map(node => node.getAttribute('title')).filter(text => /[.;]\\s|\\.$/.test(text))""") == []
        card = page.locator("#hover-card")
        helps = page.evaluate("[...document.querySelectorAll('[data-hover-help]')].length")
        assert helps >= 5
        for index in range(helps):
            trigger = page.locator("[data-hover-help]").nth(index)
            text = trigger.get_attribute("data-hover-help")
            trigger.evaluate("node => node.dispatchEvent(new FocusEvent('focusin', {bubbles: true}))")
            expect(card).to_contain_text(text.strip()[:40])
            page.keyboard.press("Escape")
            expect(card).to_be_hidden()

        page.evaluate("obsArtifact.activateChapter('design-input-input-model')")
        page.evaluate("obsArtifact.whenChapterReady()")
        reference = page.locator("[data-chapter-body] a[href='#appendix-references-obsidian-bases-syntax']").first
        assert reference.inner_text() == "Bases syntax"
        reference.scroll_into_view_if_needed()
        reference.hover()
        expect(card.locator("a[href^='http']")).to_have_attribute("href", "https://help.obsidian.md/bases/syntax")
        expect(card.locator("a[href^='http']")).to_have_count(1)
        assert page.locator("[data-chapter-body] a[href^='https://help.obsidian.md']").count() == 0
        page.keyboard.press("Escape")

        page.evaluate("obsArtifact.activateChapter('appendix-references')")
        page.evaluate("obsArtifact.whenChapterReady()")
        rows = page.locator("[data-chapter-body] tbody tr[data-row-key]")
        expect(rows).to_have_count(7)
        assert page.locator(".hover-card").count() == 1
        assert errors == []
    finally:
        context.close()
