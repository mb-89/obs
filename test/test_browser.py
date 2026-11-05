import base64
import json
import os
import shutil
import subprocess
from importlib.resources import files
from pathlib import Path

import pytest

from obs_html.content import ContentError, validate_base_definition
from obs_html.content import parse_manifest
from obs_html.renderer import render_report


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"),
                    reason="Set OBS_HTML_TEST_NATIVE_BROWSER for native reference navigation.")
def test_open_point_references_reveal_rows_and_canonical_backlinks(tmp_path: Path) -> None:
    from playwright.sync_api import sync_playwright, expect

    target = "owner#mark-owner-open-point-datum-a-continuity"
    (tmp_path / "owner.md").write_text(
        "# Owner\n\n## Datum\n\nDoes the datum continue? "
        "#mark/open_point/datum_a_continuity\n\n"
        "Another question. #mark/open_point/another\n", encoding="utf-8",
    )
    (tmp_path / "simplification.md").write_text(
        f"---\nkind: simplification\nOpen: '[[{target}|Copied question]]'\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "review.md").write_text(
        "# Review\n\n```base\nfilters: 'kind == \"simplification\"'\n"
        "views:\n  - type: table\n    order: [title, Open]\n```\n\n"
        f"Body reference [[{target}]].\n", encoding="utf-8",
    )
    (tmp_path / "register.md").write_text(
        "# Register\n\n## Questions\n\n### All points\n\n"
        "```base\nfilters: 'type == \"open_point\"'\n"
        "views:\n  - type: table\n    order: [label, text, backlinks]\nobsHtml: {records: tag}\n```\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[owner]]\n- [[review]]\n- [[register]]\n", encoding="utf-8")
    report = tmp_path / "report.html"
    report.write_text(render_report(manifest, parse_manifest(manifest), table_page_size=1),
                      encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"])
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(report.as_uri() + "#review")
            link = page.locator('[data-chapter-body] td a[data-tag-label="datum_a_continuity"]')
            expect(link).to_have_text("#mark/open_point/datum_a_continuity")
            page.evaluate("""() => document.addEventListener("obs-chapter-change", (event) => {
                if (event.detail.slug === "register") {
                    document.querySelectorAll('[data-heading-toggle][aria-expanded="true"]')
                        .forEach((button) => button.click());
                }
            })""")
            link.click()
            row = page.locator('[data-row-key="owner:open_point:datum_a_continuity"]')
            expect(row).to_be_visible()
            expect(page.locator('[data-active-chapter]')).to_have_attribute("data-chapter", "register")
            expect(row.locator("li a")).to_have_text([
                "Owner", "Review · line 10", "Simplification · Open",
            ])
            assert row.locator("li a").count() == 3
            row.get_by_role("link", name="Simplification · Open", exact=True).click()
            field = page.locator('[data-frontmatter-field="open"]')
            expect(field).to_be_visible()
            expect(field.locator("a")).to_have_text("#mark/open_point/datum_a_continuity")
            field.locator("a").click()
            expect(row).to_be_visible()
            row.get_by_role("link", name="Owner", exact=True).click()
            expect(page.locator("#mark-owner-open-point-datum-a-continuity")).to_be_visible()
            assert errors == []
        finally:
            browser.close()


@pytest.mark.skipif(not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"),
                    reason="Set OBS_HTML_TEST_NATIVE_BROWSER for native reference navigation.")
def test_tag_navigation_uses_bases_filter_grammar(tmp_path: Path) -> None:
    from playwright.sync_api import sync_playwright, expect

    table = ("```base\nfilters: 'type == \"{kind}\"'\n"
             "views:\n  - type: table\n    order: [label, text]\nobsHtml: {{records: tag}}\n```\n")
    (tmp_path / "owner.md").write_text(
        "# Owner\n\nDoes the datum continue? #mark/open_point/datum_a_continuity\n", encoding="utf-8",
    )
    (tmp_path / "decoy.md").write_text("# Decoy\n\n" + table.format(kind="OPEN_POINT"), encoding="utf-8")
    (tmp_path / "register.md").write_text("# Register\n\n" + table.format(kind="open_point"), encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[owner]]\n- [[decoy]]\n- [[register]]\n", encoding="utf-8")
    document = tmp_path / "document.html"
    document.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"])
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(document.as_uri() + "#owner")
            page.locator('[data-chapter-body] a[data-tag-label="datum_a_continuity"]').first.click()
            expect(page.locator('[data-active-chapter]')).to_have_attribute("data-chapter", "register")
            expect(page.locator('[data-row-key="owner:open_point:datum_a_continuity"]')).to_be_visible()
            assert errors == []
        finally:
            browser.close()


@pytest.fixture(scope="module")
def native_reader_report(tmp_path_factory):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native reader checks.")
    from playwright.sync_api import sync_playwright

    vault = tmp_path_factory.mktemp("reader-features")
    manifest = vault / "manifest.md"
    manifest.write_text("- [[glossary]]\n- [[alpha]]\n  - [[beta]]\n", encoding="utf-8")
    (vault / "glossary.md").write_text(
        '# Glossary\n\n```base\nobsHtml: {records: glossary}\n'
        "views:\n  - type: table\n    order: [term, definition]\n```\n", encoding="utf-8",
    )
    for name, term in (("bluf", "BLUF"), ("bottom-line", "Bottom line")):
        (vault / f"{name}.md").write_text(
            f"---\nkind: glossary\nterm: {term}\ndefinition: The conclusion.\n---\n"
            f"# {term}\n\nExplanation.\n", encoding="utf-8",
        )
    (vault / "alpha.md").write_text(
        "# Alpha\n\n## Knowledge ownership\n\nOpening text.\n\n"
        "### Details\n\nMore detail.\n\n#### Deep detail\n\nNested text.\n\n"
        "| Assumption | Qualification |\n|---|---|\n| Independent inputs | Scenario only |\n\n"
        "## Change locality\n\n" + "\n\n".join(
            f"Paragraph {index}. " + "Reader content. " * 12 for index in range(25)
        ), encoding="utf-8",
    )
    (vault / "beta.md").write_text("# Beta\n\nLast chapter.\n", encoding="utf-8")
    report = vault / "report.html"
    report.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        try:
            yield browser, report
        finally:
            browser.close()


@pytest.fixture
def native_reader_page(native_reader_report):
    browser, report = native_reader_report
    page = browser.new_page(viewport={"width": 1920, "height": 900})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(report.as_uri() + "#alpha")
    try:
        yield page
    finally:
        page.close()
    assert errors == []


def test_native_comment_export_uses_isolated_browser_clipboard(native_reader_report) -> None:
    from playwright.sync_api import expect

    browser, report = native_reader_report
    context = browser.new_context(permissions=["clipboard-write"])
    context.add_init_script("""{
        const write = navigator.clipboard.writeText.bind(navigator.clipboard);
        window.fixtureClipboardWrites = [];
        navigator.clipboard.writeText = async text => {
            await write(text);
            window.fixtureClipboardWrites.push(text);
        };
    }""")
    documents = {"report.html": report.read_text(encoding="utf-8")}
    context.route(
        "http://localhost/**",
        lambda route: route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=documents[route.request.url.rsplit("/", 1)[-1]],
        ),
    )
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto("http://localhost/report.html#alpha")
        page.evaluate("""() => {
            obsReport.openBar('comments');
            // Review mode prepends a gutter of icon buttons; match the paragraph's own text.
            const paragraph = [...document.querySelectorAll('[data-chapter-body] p')]
                .find(node => node.lastChild?.nodeValue === 'Opening text.');
            const range = document.createRange();
            range.selectNodeContents(paragraph);
            const selection = getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            document.dispatchEvent(new Event('selectionchange'));
            document.querySelector('[data-comment-add]').click();
            const annotation = obsComments.data.annotations[0];
            annotation.author = 'Fixture reviewer Ω';
            annotation.text = 'Clipboard boundary fixture.\\n<not executable> & Unicode “quote”.';
            window.fixtureExpectedPage = paragraph.closest('.paper-sheet')
                .querySelector('.paper-page-number').textContent.match(/Page (\\d+)/)[1];
            obsComments.data.annotations.push({
                id: 'inactive-copy', author: 'Other reviewer',
                text: 'Offscreen feedback.', status: 'open',
                target: {
                    chapter: 'beta', quote: 'Last chapter.', prefix: '',
                    suffix: '', start: 0, end: 13, item: 'item-1',
                },
                replies: [],
            });
            window.fixtureOriginal = {
                data: JSON.stringify(obsComments.data),
                island: document.querySelector('[data-comment-island]').textContent,
                dirty: document.querySelector('[data-review-save-guidance]').dataset.dirty,
            };
            const filter = document.querySelector('[data-comment-filter-input]');
            filter.value = 'no matching comment';
            filter.dispatchEvent(new Event('input'));
        }""")
        page.set_viewport_size({"width": 1280, "height": 900})
        desktop = page.evaluate("""() => {
            const rect = selector => {
                const {x, y, width, height, right} =
                    document.querySelector(selector).getBoundingClientRect();
                return {x, y, width, height, right};
            };
            return {
                controls: rect('.comment-save-controls'),
                left: rect('.comment-save-controls-left'),
                save: rect('[data-comment-save]'),
                load: rect('[data-comment-load]'),
                copy: rect('[data-comment-copy]'),
            };
        }""")
        assert desktop["save"]["y"] == desktop["load"]["y"]
        assert desktop["copy"]["x"] >= desktop["left"]["right"]
        assert desktop["left"]["width"] == pytest.approx(desktop["copy"]["width"], abs=1)
        page.locator("[data-comment-copy]").click()
        expect(page.locator("[data-comment-announcer]")).to_have_text(
            "Comments copied to clipboard.",
        )
        expect(page.locator("[data-comment-announcer]")).to_be_visible()
        copied = page.evaluate("window.fixtureClipboardWrites")
        assert len(copied) == 1
        assert "Fixture reviewer Ω" in copied[0]
        assert '<not executable> & Unicode “quote”.' in copied[0]
        assert "Opening text." in copied[0]
        assert f"Page: {page.evaluate('fixtureExpectedPage')}\n" in copied[0]
        assert "Offscreen feedback." in copied[0]
        assert "Page: unavailable" in copied[0]
        assert "Section: Knowledge ownership" in copied[0]
        assert page.evaluate("""() =>
            JSON.stringify(obsComments.data) === fixtureOriginal.data &&
            document.querySelector('[data-comment-island]').textContent === fixtureOriginal.island &&
            document.querySelector('[data-review-save-guidance]').dataset.dirty === fixtureOriginal.dirty &&
            document.querySelector('[data-comment-filter-input]').value === 'no matching comment'
        """)
        page.evaluate("""() => {
            window.showSaveFilePicker = async () => ({createWritable: async () => ({
                write: async contents => { window.fixtureSavedHtml = contents; },
                close: async () => {},
            })});
        }""")
        page.locator("[data-comment-save]").click()
        expect(page.locator("[data-comment-announcer]")).to_have_text("HTML saved.")
        expect(page.locator("[data-review-save-guidance]")).to_have_attribute("data-dirty", "false")
        documents["reviewed.html"] = page.evaluate("window.fixtureSavedHtml")
        reviewed = report.with_name("reviewed.html")
        reviewed.write_text(documents["reviewed.html"], encoding="utf-8")
        report.with_name("comments.md").write_text(copied[0], encoding="utf-8")
        reopened = context.new_page()
        reopened.on("pageerror", lambda error: errors.append(str(error)))
        reopened.goto("http://localhost/reviewed.html#alpha")
        restored = reopened.evaluate("obsComments.data")
        assert len(restored["annotations"]) == 2
        assert restored["annotations"][0]["target"]["section"] == "Knowledge ownership"
        assert restored["annotations"][0]["target"]["item"].startswith("item-")
        assert restored["annotations"][0]["text"].startswith("Clipboard boundary fixture.")
        assert reopened.locator("[data-review-save-guidance]").get_attribute("data-dirty") == "false"
        reopened.evaluate("""async html => {
            await obsComments.importFiles([{text: async () => html}]);
        }""", documents["reviewed.html"])
        assert reopened.evaluate("obsComments.data.annotations.length") == 2
        assert reopened.locator("[data-review-save-guidance]").get_attribute("data-dirty") == "false"
        reopened.close()
        page.set_viewport_size({"width": 390, "height": 844})
        narrow = page.evaluate("""() => {
            const controls = document.querySelector('.comment-save-controls');
            return {
                width: controls.clientWidth,
                scrollWidth: controls.scrollWidth,
                right: controls.getBoundingClientRect().right,
                buttons: [...controls.querySelectorAll('button')].map(button =>
                    button.getBoundingClientRect().right),
            };
        }""")
        assert narrow["scrollWidth"] <= narrow["width"]
        assert all(right <= narrow["right"] + 1 for right in narrow["buttons"])
        report.with_name("native-comment-proof.json").write_text(
            json.dumps({
                "clipboard_writes": len(copied), "clipboard_reads": 0,
                "native_page": page.evaluate("fixtureExpectedPage"),
                "desktop": desktop, "narrow": narrow,
                "reopened_annotations": len(restored["annotations"]), "errors": errors,
            }, indent=2), encoding="utf-8",
        )
        assert errors == []
    finally:
        context.close()


def test_native_comment_export_preserves_multiblock_selection(native_reader_page) -> None:
    from playwright.sync_api import expect

    page = native_reader_page
    target = page.evaluate("""() => {
        obsReport.openBar('comments');
        const paragraphs = [...document.querySelectorAll('[data-chapter-body] p')];
        const first = paragraphs.find(node => node.lastChild?.nodeValue === 'Opening text.');
        const last = paragraphs.find(node => node.lastChild?.nodeValue === 'More detail.');
        const range = document.createRange();
        range.setStart(first.lastChild, 0);
        range.setEnd(last.lastChild, last.lastChild.textContent.length);
        const selection = getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        document.dispatchEvent(new Event('selectionchange'));
        document.querySelector('[data-comment-add]').click();
        Object.defineProperty(navigator, 'clipboard', {value: {
            writeText: async text => { window.fixtureCopiedText = text; },
        }});
        return obsComments.data.annotations[0].target;
    }""")
    page.locator("[data-comment-copy]").click()
    expect(page.locator("[data-comment-announcer]")).to_have_text(
        "Comments copied to clipboard.",
    )
    copied = page.evaluate("window.fixtureCopiedText")
    assert "Opening text." in target["quote"]
    assert "More detail." in target["quote"]
    assert target["quote"] in copied
    assert "item" not in target
    assert f'paragraph anchor, text positions {target["start"]}-{target["end"]}' in copied


def test_native_comment_export_omits_hidden_target_page(native_reader_page) -> None:
    from playwright.sync_api import expect

    page = native_reader_page
    page.evaluate("""() => {
        obsReport.openBar('comments');
        const paragraph = [...document.querySelectorAll('[data-chapter-body] p')]
            .find(node => node.lastChild?.nodeValue === 'Opening text.');
        const range = document.createRange();
        range.selectNodeContents(paragraph);
        const selection = getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        document.dispatchEvent(new Event('selectionchange'));
        document.querySelector('[data-comment-add]').click();
        obsComments.data.annotations[0].text = 'Hidden target feedback.';
        paragraph.hidden = true;
        Object.defineProperty(navigator, 'clipboard', {value: {
            writeText: async text => { window.fixtureCopiedText = text; },
        }});
    }""")
    page.locator("[data-comment-copy]").click()
    expect(page.locator("[data-comment-announcer]")).to_have_text(
        "Comments copied to clipboard.",
    )
    copied = page.evaluate("window.fixtureCopiedText")
    assert "- Page: unavailable" in copied
    assert 'review item "item-1"' in copied
    assert "Opening text." in copied
    assert "Hidden target feedback." in copied


def test_native_comment_controls_compact_layout(native_reader_report) -> None:
    browser, report = native_reader_report
    page = browser.new_page()
    measurements = []
    try:
        page.goto(report.as_uri() + "#alpha")
        page.evaluate("obsReport.openBar('comments')")
        for width in (1280, 390):
            page.set_viewport_size({"width": width, "height": 900})
            result = page.evaluate("""() => {
                const rect = selector => {
                    const element = document.querySelector(selector);
                    const {x, y, width, height, right, bottom} = element.getBoundingClientRect();
                    return {x, y, width, height, right, bottom, text: element.textContent.trim(),
                        overflow: element.scrollWidth > element.clientWidth};
                };
                return {
                    controls: rect('.comment-save-controls'),
                    left: rect('.comment-save-controls-left'),
                    save: rect('[data-comment-save]'),
                    load: rect('[data-comment-load]'),
                    copy: rect('[data-comment-copy]'),
                };
            }""")
            assert result["save"]["text"] == "Save"
            assert result["load"]["text"] == "Load"
            assert result["save"]["y"] == result["load"]["y"]
            assert not any(result[key]["overflow"] for key in result)
            if width == 1280:
                assert result["left"]["width"] == pytest.approx(result["copy"]["width"], abs=1)
                assert result["copy"]["x"] >= result["left"]["right"]
                assert result["controls"]["height"] < 64
            else:
                assert result["copy"]["y"] >= result["left"]["bottom"]
            measurements.append({"viewport_width": width, **result})
            page.screenshot(path=str(report.with_name(f"comment-controls-{width}.png")))
        report.with_name("compact-controls-proof.json").write_text(
            json.dumps(measurements, indent=2), encoding="utf-8",
        )
    finally:
        page.close()


def test_native_table_vertical_viewport(tmp_path: Path) -> None:
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native table viewport checks.")
    from playwright.sync_api import sync_playwright

    (tmp_path / "overview.md").write_text(
        "# Overview\n\n"
        "```base\n"
        "views:\n  - type: table\n    name: Viewport\n    order: [term, definition]\n"
        "    groupBy: {property: recordType}\n"
        "    sort: {property: term, direction: ASC}\n"
        "obsHtml:\n  records: glossary\n  maxRows: 3\n```\n",
        encoding="utf-8",
    )
    for index in range(26):
        slug = f"item-{index:02d}"
        (tmp_path / f"{slug}.md").write_text(
            f"---\nkind: glossary\nterm: Item {index:02d}\n"
            f"definition: Definition {index:02d}.\n---\n"
            f"# Item {index:02d}\n\n"
            + ("A long detail paragraph with wrapped content. " * 70 if index == 0
               else f"Details for item {index:02d}.\n"),
            encoding="utf-8",
        )
    (tmp_path / "manifest.md").write_text("- [[overview]]\n", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    report = tmp_path / "report.html"
    report.write_text(
        render_report(manifest, parse_manifest(manifest)),
        encoding="utf-8",
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        page = browser.new_page(viewport={"width": 620, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(report.as_uri() + "#overview")
            shell = page.locator(".data-table-shell").first
            scroller = shell.locator(".data-table-scroll")
            assert scroller.get_attribute("data-max-rows") == "3"
            page.wait_for_function(
                "document.querySelector('.data-table-scroll[data-max-rows]')"
                ".style.getPropertyValue('--table-viewport-max-height') !== ''"
            )
            assert shell.locator("tbody tr[data-row-key]").count() == 20
            assert shell.locator(".data-table-count").inner_text() == "26 of 26 items"
            assert shell.locator(".data-table-group-row").inner_text().replace(
                "▾", "",
            ).strip() == "recordType: glossary (26)"
            first_row = shell.locator("tbody tr[data-row-key]").first
            assert first_row.get_attribute("data-row-key") == "glossary:item-00"
            shell.locator("th[data-column-key='term']").click()
            assert shell.locator("tbody tr[data-row-key]").first.get_attribute(
                "data-row-key",
            ) == "glossary:item-25"
            shell.locator("th[data-column-key='term']").click()
            assert shell.locator("tbody tr[data-row-key]").first.get_attribute(
                "data-row-key",
            ) == "glossary:item-00"
            metrics = scroller.evaluate("""node => {
                const header = node.querySelector('thead').getBoundingClientRect().height;
                const row = node.querySelector('tbody tr[data-row-key]').getBoundingClientRect().height;
                return {height: node.clientHeight, scrollHeight: node.scrollHeight,
                    header, row, footer: node.nextElementSibling.getBoundingClientRect().height};
            }""")
            assert metrics["scrollHeight"] > metrics["height"]
            assert metrics["height"] <= metrics["header"] + metrics["row"] * 3 + 2
            assert shell.locator(".data-table-footer").is_visible()

            page.set_viewport_size({"width": 460, "height": 900})
            shell.locator("tbody tr[data-row-key='glossary:item-00'] .data-table-tree-toggle").click()
            detail = shell.locator("tr[data-detail-owner='glossary:item-00']")
            assert detail.count() == 1
            assert scroller.evaluate(
                "node => node.scrollHeight > node.clientHeight"
            )
            scroller.evaluate("node => {node.scrollTop = node.scrollHeight;}")
            assert scroller.evaluate(
                "node => node.scrollTop + node.clientHeight >= node.scrollHeight - 1"
            )
            page.evaluate("document.body.classList.add('review-mode')")
            assert scroller.evaluate("node => getComputedStyle(node).overflowY !== 'visible'")

            first_page = shell.locator("tbody tr[data-row-key]").evaluate_all(
                "rows => rows.map(row => row.dataset.rowKey)"
            )
            shell.locator(".data-table-page-button[aria-label='Next table page']").click()
            second_page = shell.locator("tbody tr[data-row-key]").evaluate_all(
                "rows => rows.map(row => row.dataset.rowKey)"
            )
            assert len(second_page) == 6
            assert set(first_page).isdisjoint(second_page)

            size = shell.get_by_label("Items per page")
            size.fill("5")
            size.press("Enter")
            assert shell.locator(".data-table-page").inner_text() == "Page 1 of 6"
            page.evaluate("""() => {
                const shell = document.querySelector('.data-table-shell');
                shell.dispatchEvent(new CustomEvent('obs-table-set-filter', {
                    detail: {expression: 'term: /Item 2/'},
                }));
            }""")
            assert shell.locator(".data-table-count").inner_text() == "6 of 26 items"
            page.evaluate("""() => {
                document.querySelector('.data-table-shell').dispatchEvent(
                    new CustomEvent('obs-table-set-filter', {
                        detail: {expression: 'term: /^Item 25$/'},
                    }),
                );
            }""")
            small = scroller.evaluate("""node => ({
                height: node.clientHeight,
                max: parseFloat(getComputedStyle(node).maxBlockSize),
            })""")
            assert shell.locator(".data-table-count").inner_text() == "1 of 26 items"
            assert small["height"] < small["max"]
            page.evaluate("""() => {
                document.querySelector('.data-table-shell').dispatchEvent(
                    new CustomEvent('obs-table-set-filter', {
                        detail: {expression: 'term: /^absent$/'},
                    }),
                );
            }""")
            empty = scroller.evaluate("""node => ({
                height: node.clientHeight,
                header: node.querySelector('thead').getBoundingClientRect().height,
            })""")
            assert shell.locator(".data-table-count").inner_text() == "0 of 26 items"
            assert empty["height"] <= empty["header"] + 2
            page.evaluate("""() => {
                const shell = document.querySelector('.data-table-shell');
                shell.dispatchEvent(new CustomEvent('obs-table-set-filter', {
                    detail: {expression: ''},
                }));
                shell.dispatchEvent(new CustomEvent('obs-table-reveal-row', {
                    detail: {key: 'glossary:item-22'},
                }));
            }""")
            assert shell.locator(".data-table-page").inner_text() == "Page 5 of 6"
            target_row = shell.locator("tbody tr[data-row-key='glossary:item-22']")
            assert target_row.count() == 1
            target_row.evaluate("node => node.scrollIntoView({block: 'center'})")
            assert scroller.evaluate("""node => {
                const row = node.querySelector("tr[data-row-key='glossary:item-22']");
                const bounds = row.getBoundingClientRect();
                const viewport = node.getBoundingClientRect();
                return bounds.top >= viewport.top && bounds.bottom <= viewport.bottom;
            }""")

            page.evaluate("obsPages.setPaged(true)")
            assert page.locator(".paged-reader .data-table-scroll[data-max-rows='3']").count() == 1
            static = page.evaluate("""() => {
                const root = document.createElement('div');
                obsReport.renderStatic('overview', root, true);
                return {
                    rows: root.querySelectorAll('table tbody tr[data-row-key]').length,
                    scrollers: root.querySelectorAll('.data-table-scroll').length,
                };
            }""")
            assert static == {"rows": 26, "scrollers": 0}
            assert errors == []
        finally:
            page.close()
            browser.close()


@pytest.mark.skipif(not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"),
                    reason="Set OBS_HTML_TEST_NATIVE_BROWSER for native title checks.")
def test_native_explicit_empty_title_preserves_cover_and_pdf(tmp_path: Path, native_reader_report) -> None:
    from io import BytesIO
    from pypdf import PdfReader
    from playwright.sync_api import expect

    (tmp_path / "chapter.md").write_text("# Chapter\n\nEvidence.", encoding="utf-8")
    manifest = tmp_path / "My document.md"
    manifest.write_text(
        "---\ntitle: ''\nsubtitle: '[Source → Target](chapter.md)'\n"
        "organization: Example\ndocument type: Report\nauthors: [Ada]\n---\n"
        "- [[chapter]]\n\nOpening evidence.\n",
        encoding="utf-8",
    )
    report = tmp_path / "report.html"
    report.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    page = native_reader_report[0].new_page(viewport={"width": 1440, "height": 900})
    try:
        page.goto(report.as_uri())
        expect(page.locator("html")).to_have_attribute("data-theme", "light")
        expect(page.locator("html")).to_have_class("paged-mode")
        expect(page).to_have_title("My document")
        cover = page.locator('.paged-reader .paper-sheet[data-page-chapter="home"]')
        expect(cover.locator(".document-title")).to_have_count(0)
        expect(cover.locator(".document-subtitle a")).to_have_text("Source → Target")
        expect(cover.locator(".cover-organization")).to_have_text("Example")
        expect(cover.locator(".cover-type")).to_have_text("Report")
        expect(cover.locator(".cover-facts")).to_contain_text("Ada")
        assert cover.bounding_box()["height"] >= 297 * 96 / 25.4 - 1
        page.evaluate("window.print = () => {}; obsPages.exportPDF()")
        page.wait_for_function("document.querySelector('.print-book .paper-sheet')")
        pdf = PdfReader(BytesIO(page.pdf(prefer_css_page_size=True)))
        first_page = pdf.pages[0].extract_text()
        assert "Source" in first_page and "Target" in first_page
        assert "Example" in first_page and "Ada" in first_page and "Report" in first_page
        assert "My document" not in first_page
    finally:
        page.close()


def test_reader_mobile_pages_fit_reader_without_changing_print_paper(native_reader_page) -> None:
    page = native_reader_page
    page.evaluate("obsReport.activateChapter('home')")
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(100)
    dimensions = page.locator(".chapter-scroll").evaluate("""reader => ({
        width: reader.clientWidth, overflow: reader.scrollWidth,
        sheets: [...reader.querySelectorAll('.paper-sheet')].map(sheet => ({
            width: sheet.getBoundingClientRect().width,
            height: sheet.getBoundingClientRect().height,
            overflow: sheet.scrollWidth,
            content: sheet.clientWidth,
        })),
    })""")
    assert dimensions["overflow"] <= dimensions["width"] + 1
    assert dimensions["sheets"]
    assert all(sheet["width"] <= dimensions["width"] + 1 for sheet in dimensions["sheets"])
    assert all(sheet["overflow"] <= sheet["content"] + 1 for sheet in dimensions["sheets"])
    assert dimensions["sheets"][0]["height"] >= 297 * 96 / 25.4 - 1
    page.evaluate("window.print = () => {}; obsPages.exportPDF()")
    page.wait_for_function("document.querySelector('.print-book .paper-sheet')")
    assert page.locator(".print-book .paper-sheet").first.bounding_box()["width"] == pytest.approx(
        210 * 96 / 25.4, abs=1,
    )


def test_reader_title_sheet_keeps_full_paper_size(native_reader_page) -> None:
    from io import BytesIO
    from pypdf import PdfReader

    page = native_reader_page
    page.evaluate("obsReport.activateChapter('home')")
    cover = page.locator('.paged-reader .paper-sheet[data-page-chapter="home"]')
    assert cover.count() == 1
    bounds = cover.bounding_box()
    assert bounds["width"] == pytest.approx(210 * 96 / 25.4, abs=1)
    assert bounds["height"] == pytest.approx(297 * 96 / 25.4, abs=1)
    page.evaluate("obsPages.setPaged(false); obsPages.setPaged(true)")
    assert cover.bounding_box()["height"] == pytest.approx(bounds["height"], abs=1)

    page.evaluate("obsReport.activateChapter('beta')")
    assert page.locator(".paged-reader .paper-sheet").bounding_box()["height"] < bounds["height"]

    page.evaluate("obsReport.activateChapter('home')")
    page.evaluate("window.print = () => {}; obsPages.exportPDF()")
    try:
        pdf = PdfReader(BytesIO(page.pdf(prefer_css_page_size=True, print_background=True)))
        assert float(pdf.pages[0].mediabox.width) == pytest.approx(210 * 72 / 25.4, abs=1)
        assert float(pdf.pages[0].mediabox.height) == pytest.approx(297 * 72 / 25.4, abs=1)
    finally:
        page.evaluate("window.dispatchEvent(new Event('afterprint'))")


@pytest.mark.parametrize("follower", ["paragraph", "list", "figure", "captioned-figure", "table"])
@pytest.mark.parametrize("chain", [False, True])
def test_native_heading_keeps_content(tmp_path, native_reader_report, follower, chain):
    """Real layout must look through section wrappers, not just clip a preview."""
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[sample]]\n", encoding="utf-8")
    following = {
        "paragraph": "  \n".join(f"Following line {index}." for index in range(8)),
        "list": "\n".join(f"- Following item {index}." for index in range(8)),
        "figure": "![Following figure](figure.svg)",
        "captioned-figure": "```figure\nversion: 1\nkind: svg\nsource: scene.json\n"
        "fallback: figure.svg\ncaption: Following caption\n```",
        "table": "| Following | Value |\n|---|---|\n" +
        "\n".join(f"| Item {index} | Value {index} |" for index in range(8)),
    }[follower]
    (tmp_path / "figure.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="180" viewBox="0 0 400 180">'
        '<rect width="400" height="180" fill="teal"/></svg>', encoding="utf-8",
    )
    (tmp_path / "scene.json").write_text(
        '{"version":1,"panels":[{"id":"a","title":"A","box":[0,0,400,180]}]}', encoding="utf-8",
    )
    (tmp_path / "sample.md").write_text(
        "# Sample\n\n**Spacer**\n\n## Topic\n\n" +
        ("### Nested\n\n" if chain else "") + following + "\n", encoding="utf-8",
    )
    output = tmp_path / "report.html"
    output.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    page = native_reader_report[0].new_page()
    try:
        page.goto(output.as_uri() + "#sample")
        page.evaluate("obsPages.setPaged(false)")
        page.add_style_tag(content=".chapter-body p:has(>strong:only-child) {height:700px; margin:0}")
        page.evaluate("obsPages.setPaged(true)")
        selector = {"paragraph": "p", "list": "ul", "figure": "figure[data-report-figure]:has(img)",
                    "captioned-figure": "figure", "table": "table"}[follower]
        for projection in (".paged-reader", ".print-book"):
            if projection == ".print-book":
                page.evaluate("window.print = () => {}; obsPages.exportPDF()")
            heading_sheet = page.locator(projection + " h2").filter(has_text="Topic").evaluate(
                "(h) => h.closest('.paper-sheet').dataset.sheetIndex = "
                "[...h.closest('.paper-sheet').parentElement.children].indexOf(h.closest('.paper-sheet'))"
            )
            first_sheet = page.locator(projection + " [data-page-chapter='sample'] " + selector).filter(
                has_text="Following" if follower != "figure" else None,
            ).first.evaluate(
                "(p) => [...p.closest('.paper-sheet').parentElement.children].indexOf(p.closest('.paper-sheet'))"
            )
            assert heading_sheet == first_sheet
            if chain:
                assert page.locator(projection + " h3").evaluate(
                    "(h) => [...h.closest('.paper-sheet').parentElement.children].indexOf(h.closest('.paper-sheet'))"
                ) == first_sheet
            if follower == "captioned-figure":
                assert page.locator(projection + " figcaption").evaluate(
                    "(caption) => caption.closest('.paper-sheet') === "
                    "caption.closest('figure').querySelector('img').closest('.paper-sheet')"
                )
            if follower == "table":
                assert page.locator(projection + " [data-page-chapter='sample'] table").evaluate_all(
                    "(tables) => tables.every(table => table.querySelector('thead') && "
                    "table.querySelector('tbody tr'))"
                )
    finally:
        page.close()


def test_wide_reader_tables_fit_fixed_print_area(tmp_path, native_reader_report):
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[wide]]\n", encoding="utf-8")
    columns = ["Description", "Assumptions", "Evidence", "Qualification", "Open"]
    table = "| " + " | ".join(columns) + " |\n|" + "|".join("---" for _ in columns) + "|\n"
    table += "\n".join(
        "| " + " | ".join(f"Row {index} column {column}. " + "Detailed qualification. " * 5
                          for column in range(len(columns))) + " |"
        for index in range(28)
    )
    (tmp_path / "wide.md").write_text("# Wide table\n\n" + table, encoding="utf-8")
    output = tmp_path / "report.html"
    output.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    page = native_reader_report[0].new_page(viewport={"width": 1920, "height": 1440})
    try:
        page.goto(output.as_uri() + "#wide")
        page.evaluate("window.print = () => {}; obsPages.exportPDF()")
        page.emulate_media(media="print")
        assert page.locator(".print-book .paper-content").evaluate_all("""areas =>
            areas.every(area => area.scrollHeight <= area.clientHeight + 1 &&
                area.closest('.paper-sheet').scrollWidth <= area.closest('.paper-sheet').clientWidth + 1)""")
        tables = page.locator(".print-book [data-page-chapter='wide'] table")
        assert tables.count() > 1
        assert tables.evaluate_all("""tables => tables.every(table =>
            table.querySelectorAll(':scope > colgroup').length === 1 &&
            table.querySelectorAll('thead tr:first-child th').length === 5 &&
            [...table.querySelectorAll('tbody tr')].every(row => row.children.length === 5))""")
        assert page.pdf(prefer_css_page_size=True).startswith(b"%PDF")
    finally:
        page.close()


def test_native_compact_heading_spacing(native_reader_page):
    page = native_reader_page
    for scope in ("[data-chapter-body]", ".paged-reader", ".print-book"):
        if scope == ".print-book":
            page.evaluate("window.print = () => {}; obsPages.exportPDF()")
        else:
            page.evaluate("(enabled) => obsPages.setPaged(enabled)", scope == ".paged-reader")
        spacing = page.locator(scope + " h2").filter(has_text="Knowledge ownership").evaluate("""(heading) => {
            const wrapper = heading.closest('.collapsible-heading') || heading;
            const next = wrapper.nextElementSibling;
            const paragraph = next.matches('p') ? next : next.querySelector('p');
            return {gap: paragraph.getBoundingClientRect().top - heading.getBoundingClientRect().bottom,
                font: parseFloat(getComputedStyle(paragraph).fontSize)};
        }""")
        assert 0 <= spacing["gap"] <= 12
        assert spacing["font"] == pytest.approx(
            1.08 * 16 if scope == "[data-chapter-body]" else 11 * 96 / 72, abs=.1,
        )


@pytest.mark.parametrize("space,lines", [(1, 8), (3, 4), (4, 5), (5, 8), (40, 95)])
def test_native_paragraph_widows_and_orphans(tmp_path, native_reader_report, space, lines):
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[sample]]\n", encoding="utf-8")
    prose = "  \n".join(f"Line {index:03} with *inline emphasis*." for index in range(lines))
    (tmp_path / "sample.md").write_text(
        "# Sample\n\n**Spacer**\n\n" + prose + "\n\nFinal marker.\n", encoding="utf-8",
    )
    output = tmp_path / "report.html"
    output.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    page = native_reader_report[0].new_page()
    try:
        page.goto(output.as_uri() + "#sample")
        # Reserve an exact number of text lines after the fixture's preceding block.
        height = page.locator(".paged-reader").evaluate("""(body, space) => {
            const paper = JSON.parse(document.querySelector('[data-report-data]').textContent).paper;
            const title = body.querySelector('h1');
            const paragraph = [...body.querySelectorAll('p')].find(p => p.textContent.startsWith('Line'));
            const style = getComputedStyle(paragraph);
            return (paper.heightMillimeters - 2 * paper.marginMillimeters) * 96 / 25.4 -
                title.getBoundingClientRect().height -
                parseFloat(getComputedStyle(title).marginBottom) -
                parseFloat(style.marginTop) - space * parseFloat(style.lineHeight) - 2;
        }""", space)
        page.evaluate("obsPages.setPaged(false)")
        page.add_style_tag(content=(
            f".chapter-body p:has(>strong:only-child) {{height:{height}px; margin:0}}"
        ))
        page.evaluate("window.print = () => {}; obsPages.exportPDF()")
        paragraphs = page.locator('.print-book [data-page-chapter="sample"] p').filter(has_text="Line")
        fragments = paragraphs.evaluate_all("""(paragraphs) => paragraphs.map(p => {
            const range = document.createRange();
            range.selectNodeContents(p);
            const tops = [];
            for (const rect of range.getClientRects()) {
                if (rect.width && !tops.some(top => Math.abs(top - rect.top) < 2)) tops.push(rect.top);
            }
            return {lines:tops.length, text:p.textContent,
                emphasis:[...p.querySelectorAll('em')].map(e => e.textContent).join('')};
        })""")
        assert len(fragments) >= 1
        assert all(fragment["lines"] >= 2 for fragment in fragments)
        assert "".join(fragment["emphasis"] for fragment in fragments) == "inline emphasis" * lines
        import re
        assert re.findall(r"Line \d{3}", "".join(fragment["text"] for fragment in fragments)) == [
            f"Line {index:03}" for index in range(lines)
        ]
        assert page.locator(".print-book .paper-content").evaluate_all(
            "(nodes) => nodes.every(n => n.scrollHeight <= n.clientHeight + 1)"
        )
        assert page.locator('.print-book [data-page-chapter="sample"]').evaluate_all(
            "(nodes) => nodes.every(n => n.querySelector('.paper-content').textContent.trim())"
        )
    finally:
        page.close()


def test_reader_edge_scroll_cues(native_reader_page) -> None:
    page = native_reader_page
    reader = page.locator("[data-chapter-scroll]")
    previous = page.locator('[data-step="-1"]')
    following = page.locator('[data-step="1"]')
    reader.evaluate("(node) => {node.scrollTop = 0;}")
    assert previous.get_attribute("data-scroll-boundary") is None
    reader.dispatch_event("wheel", {"deltaY": -100})
    assert previous.get_attribute("data-scroll-boundary") == "true"
    page.wait_for_function("""() => getComputedStyle(
        document.querySelector('[data-step="-1"]')).opacity === '1'""", timeout=3000)
    assert previous.evaluate("(button) => getComputedStyle(button).opacity") == "1"
    assert page.locator("[data-active-chapter]").get_attribute("data-chapter") == "alpha"
    reader.evaluate("(node) => {node.scrollTop = node.scrollHeight; node.dispatchEvent(new Event('scroll'));}")
    reader.dispatch_event("wheel", {"deltaY": 100})
    assert following.get_attribute("data-scroll-boundary") == "true"
    assert previous.get_attribute("data-scroll-boundary") is None
    reader.evaluate("(node) => {node.scrollTop -= 50; node.dispatchEvent(new Event('scroll'));}")
    assert following.get_attribute("data-scroll-boundary") is None
    reader.evaluate("""node => {
        node.scrollTop = 0;
        node.dispatchEvent(new Event('scroll'));
        for (const [type, clientY] of [['touchstart', 100], ['touchmove', 150]]) {
            node.dispatchEvent(new TouchEvent(type, {
                touches: [new Touch({identifier: 1, target: node, clientY})],
            }));
        }
    }""")
    assert previous.get_attribute("data-scroll-boundary") == "true"
    page.evaluate("""() => {
        const nested = document.createElement('div');
        nested.id = 'nested-scroller';
        nested.style.cssText = 'height: 40px; overflow-y: auto';
        nested.innerHTML = '<div style="height:200px">Nested scrolling</div>';
        document.querySelector('.paper-content').prepend(nested);
    }""")
    page.locator("#nested-scroller").dispatch_event("wheel", {"deltaY": 100})
    assert previous.get_attribute("data-scroll-boundary") == "true"
    reader.evaluate("(node) => {node.scrollTop = 0; node.dispatchEvent(new Event('scroll'));}")
    reader.press("ArrowUp")
    assert previous.get_attribute("data-scroll-boundary") == "true"
    page.evaluate("""() => {
        const editor = document.createElement('textarea');
        document.querySelector('.paper-content').prepend(editor);
        editor.dispatchEvent(new WheelEvent('wheel', {bubbles: true, deltaY: 100}));
    }""")
    assert following.get_attribute("data-scroll-boundary") is None
    page.evaluate("obsReport.activateChapter('beta')")
    assert previous.get_attribute("data-scroll-boundary") is None
    reader.dispatch_event("wheel", {"deltaY": 100})
    assert following.get_attribute("data-scroll-boundary") is None


def test_reader_nested_heading_toc(native_reader_page) -> None:
    page = native_reader_page
    page.goto(page.url.split("#")[0] + "#beta")
    page.reload()
    assert page.locator('[data-toc-toggle][aria-expanded="true"]').count() == 0
    page.evaluate("obsReport.activateChapter('alpha')")
    page.evaluate("obsReport.openBar('toc')")
    toc = page.locator("[data-toc-tree]")
    assert toc.locator('[data-toc-toggle][aria-expanded="true"]').count() == 0
    alpha = toc.locator('a[href="#alpha"]').locator("..")
    alpha.locator("[data-toc-toggle]").click()
    ownership = toc.get_by_role("link", name="Knowledge ownership", exact=True)
    assert ownership.is_visible()
    assert not toc.get_by_role("link", name="Deep detail", exact=True).is_visible()
    ownership.locator("..").locator("[data-toc-toggle]").click()
    toc.get_by_role("link", name="Details", exact=True).locator("..").locator("[data-toc-toggle]").click()
    deep = toc.get_by_role("link", name="Deep detail", exact=True)
    assert deep.is_visible()
    assert toc.get_by_role("link", name="Beta", exact=True).is_visible()
    page.locator('.paged-reader [data-heading-toggle][data-label="Knowledge ownership"]').click()
    deep.click()
    assert page.locator("#alpha--deep-detail").is_visible()
    assert page.evaluate("location.hash") == "#alpha/deep-detail"
    page.locator('[data-toc-action="collapse"]').click()
    assert not ownership.is_visible()
    page.locator('[data-toc-action="expand"]').click()
    assert deep.is_visible()


def test_reader_boundary_attention_ping(native_reader_page) -> None:
    page = native_reader_page
    reader = page.locator("[data-chapter-scroll]")
    icon = page.locator('[data-step="-1"] .chapter-nav-icon')
    icon_bounds = icon.bounding_box()
    control_bounds = page.locator('[data-step="-1"]').bounding_box()
    reader.evaluate("(node) => {node.scrollTop = 0;}")
    reader.dispatch_event("wheel", {"deltaY": -100})
    assert icon.get_attribute("class") == "chapter-nav-icon attention-ping"
    effect = icon.evaluate("""node => {
        const animation = node.getAnimations({subtree: true})
            .find(animation => animation.animationName === 'attention-radar');
        animation.pause();
        return {timing: animation.effect.getTiming(), frames: animation.effect.getKeyframes()};
    }""")
    assert effect["timing"]["duration"] == 250
    assert effect["timing"]["iterations"] == 4
    assert effect["frames"][-1]["transform"] == "scale(6)"
    assert effect["frames"][-1]["opacity"] == "0"
    icon.evaluate("""node => {
        const animation = node.getAnimations({subtree:true})[0];
        animation.currentTime = 125;
    }""")
    midpoint = icon.evaluate("""node => {
        const style = getComputedStyle(node, '::after');
        return {scale: new DOMMatrix(style.transform).a, opacity: Number(style.opacity),
            color: style.borderTopColor, bounds: node.getBoundingClientRect().toJSON()};
    }""")
    assert 1 < midpoint["scale"] < 6
    assert 0 < midpoint["opacity"] < 1
    assert midpoint["bounds"]["height"] < 50
    assert midpoint["bounds"]["width"] < 50
    assert icon.bounding_box() == pytest.approx(icon_bounds)
    assert page.locator('[data-step="-1"]').bounding_box() == pytest.approx(control_bounds)
    reader.dispatch_event("wheel", {"deltaY": -100})
    assert icon.evaluate("node => node.getAnimations({subtree:true})[0].currentTime") == 125
    icon.evaluate("node => node.getAnimations({subtree:true})[0].finish()")
    page.wait_for_function("!document.querySelector('.attention-ping')", timeout=2000)
    reader.dispatch_event("wheel", {"deltaY": -100})
    assert "attention-ping" in icon.get_attribute("class")
    reader.evaluate("(node) => {node.scrollTop = 100; node.dispatchEvent(new Event('scroll'));}")
    assert page.locator(".attention-ping").count() == 0
    reader.evaluate("(node) => {node.scrollTop = node.scrollHeight;}")
    reader.dispatch_event("wheel", {"deltaY": 100})
    assert page.locator('[data-step="1"] .attention-ping').count() == 1
    page.evaluate("obsReport.activateChapter('beta')")
    assert page.locator(".attention-ping").count() == 0
    page.emulate_media(reduced_motion="reduce")
    reader.evaluate("(node) => {node.scrollTop = 0;}")
    reader.dispatch_event("wheel", {"deltaY": -100})
    previous = page.locator('[data-step="-1"] .chapter-nav-icon')
    assert previous.evaluate("node => node.getAnimations({subtree:true}).length") == 0
    assert previous.evaluate("node => getComputedStyle(node, '::after').transform") == "none"
    assert previous.evaluate("node => getComputedStyle(node, '::after').borderTopColor") == midpoint["color"]


def test_reader_review_gutter_tracks_paper_edge(native_reader_page) -> None:
    page = native_reader_page
    page.evaluate("obsReport.openBar('comments')")
    for width in (1920, 1280, 2400):
        page.set_viewport_size({"width": width, "height": 900})
        page.wait_for_function("""() => {
            const gutter = document.querySelector('.paper-content p .review-gutter');
            const paper = gutter.closest('.paper-sheet').getBoundingClientRect();
            const bounds = gutter.getBoundingClientRect();
            const gap = paper.left - bounds.right;
            return gap >= 0 && gap <= 16;
        }""", timeout=3000)
        assert page.evaluate("""() => {
            const gutter = document.querySelector('.paper-content p .review-gutter');
            const paper = gutter.closest('.paper-sheet').getBoundingClientRect();
            const bounds = gutter.getBoundingClientRect();
            return bounds.left >= 0 && bounds.right <= paper.left;
        }""")
    page.evaluate("obsReport.openBar('toc', 'left')")
    page.wait_for_function("""() => {
        const gutter = document.querySelector('.paper-content p .review-gutter');
        const gap = gutter.closest('.paper-sheet').getBoundingClientRect().left -
            gutter.getBoundingClientRect().right;
        return gap >= 0 && gap <= 16;
    }""", timeout=3000)


def test_reader_review_controls_cover_continuation_sheets(native_reader_page) -> None:
    page = native_reader_page
    page.evaluate("obsReport.openBar('comments')")
    page.locator("[data-comment-author]").fill("Continuation reviewer")
    page.locator("[data-comment-author]").dispatch_event("change")
    sheets = page.locator(".paged-reader .paper-sheet")
    assert sheets.count() > 1
    for sheet in sheets.all():
        paragraphs = sheet.locator(".paper-content p")
        if not paragraphs.count():
            continue
        paragraph = paragraphs.first
        paragraph.scroll_into_view_if_needed()
        accept = paragraph.locator(".review-action--accept")
        assert accept.count() == 1
        assert accept.is_visible()
        accept.dispatch_event("click")
        assert paragraph.get_attribute("data-review-state") == "accepted"
        assert paragraph.locator(".review-action--accept").get_attribute("aria-pressed") == "true"
    assert page.locator(".paper-header [data-review-gutter], .paper-footer [data-review-gutter]").count() == 0


@pytest.mark.parametrize("reviewer", ["", "Alice"])
def test_reader_review_decision_updates_canonical_summary(native_reader_page, reviewer) -> None:
    page = native_reader_page
    page.evaluate("obsReport.openBar('comments')")
    page.locator("[data-comment-author]").fill(reviewer)
    page.locator("[data-comment-author]").dispatch_event("change")
    accepted = page.locator('[data-review-summary-state="accepted"] strong')
    waiting = page.locator('[data-review-summary-state="waiting"] strong')
    before = int(waiting.inner_text())
    page.evaluate("""() => {
        window.reviewStaticRenders = 0;
        const render = obsReport.renderStatic;
        obsReport.renderStatic = (...args) => { reviewStaticRenders++; return render(...args); };
    }""")
    item = page.locator(".paper-content p").filter(has_text="Paragraph 24.").first
    item.locator(".review-action--accept").dispatch_event("click")
    assert item.get_attribute("data-review-state") == "accepted"
    assert item.evaluate("""node => getComputedStyle(node, '::before').backgroundColor ===
        getComputedStyle(node.querySelector('.review-action--accept')).backgroundColor""")
    assert accepted.inner_text() == "1"
    assert int(waiting.inner_text()) == before - 1
    assert page.evaluate("reviewStaticRenders") == 0
    decision = page.evaluate("obsComments.data.reviews.at(-1)")
    assert decision["chapter"] == "alpha"
    assert page.evaluate("""() => {
        const record = obsReport.records.find(record => record.slug === 'alpha');
        return record.fields.review.includes('accepted') &&
            record.filterAttributes.review.includes('accepted');
    }""")
    item.locator(".review-action--accept").dispatch_event("click")
    assert accepted.inner_text() == "0"
    assert int(waiting.inner_text()) == before
    page.evaluate("obsReport.activateChapter('glossary')")
    row = page.locator('tr[data-row-key="glossary:bluf"]')
    row.locator(".review-action--accept").dispatch_event("click")
    assert row.get_attribute("data-review-state") == "accepted"
    assert accepted.inner_text() == "1"
    assert int(waiting.inner_text()) == before - 1
    row.locator(".review-action--reject").dispatch_event("click")
    assert row.get_attribute("data-review-state") == "rejected"
    assert row.locator(".review-action--reject").get_attribute("aria-pressed") == "true"
    assert page.locator(".comment-text-editor").count() == 1
    row.locator(".review-action--reject").dispatch_event("click")
    assert row.get_attribute("data-review-state") == "waiting"
    assert row.locator(".review-action--reject").get_attribute("aria-pressed") == "false"
    assert page.locator(".comment-text-editor").count() == 1
    assert int(waiting.inner_text()) == before


def test_reader_waiting_only_batch_review(native_reader_page, native_reader_report, tmp_path) -> None:
    from obs_html.comments import extract_comments

    page = native_reader_page
    page.evaluate("obsReport.openBar('comments')")
    author = page.locator("[data-comment-author]")
    author.fill("Bob")
    author.dispatch_event("change")
    opening = page.locator(".paper-content p").filter(has_text="Opening text.").first
    opening.locator(".review-action--reject").dispatch_event("click")
    page.locator(".comment-text-editor").fill("Existing Bob comment")
    bob = page.evaluate("structuredClone(obsComments.data.reviews)")
    author.fill("Alice")
    author.dispatch_event("change")
    opening.locator(".review-action--accept").dispatch_event("click")
    nested = page.locator(".paper-content p").filter(has_text="More detail.").first
    nested.locator(".review-action--reject").dispatch_event("click", {"shiftKey": True, "detail": 1})
    assert page.locator(".comment-text-editor").count() == 2
    batch = page.evaluate("obsComments.data.annotations.at(-1)")
    assert batch["batch"]["scope"] == "section"
    assert len(batch["batch"]["items"]) == 3  # nested prose, deeper prose, authored row
    assert "[Full section]" in page.locator(".comment-target").last.inner_text()
    guidance = page.locator("[data-review-modifier-guidance]").inner_text()
    assert "Shift-click" in guidance and "still-waiting items in this section" in guidance
    assert "Ctrl+Shift-click" in guidance and "throughout the document" in guidance
    guidance_style = page.locator("[data-review-modifier-guidance]").evaluate("""node => ({
        color: getComputedStyle(node).color,
        fontSize: parseFloat(getComputedStyle(node).fontSize),
        bodyColor: getComputedStyle(document.body).color,
        baseSize: parseFloat(getComputedStyle(document.body).fontSize),
    })""")
    assert guidance_style["color"] != guidance_style["bodyColor"]
    assert guidance_style["fontSize"] < guidance_style["baseSize"]
    page.locator(".comment-text-editor").last.fill("One scoped reason")
    before = page.evaluate("structuredClone(obsComments.data)")
    nested.locator(".review-action--reject").dispatch_event("click", {"shiftKey": True, "detail": 1})
    assert page.evaluate("obsComments.data") == before
    assert opening.get_attribute("data-review-state") == "rejected"  # Bob still rejects
    assert opening.evaluate("""node => getComputedStyle(node, '::before').backgroundColor !==
        getComputedStyle(node.querySelector('.review-action--accept')).backgroundColor""")
    assert opening.locator(".review-action--accept").get_attribute("aria-pressed") == "true"
    assert nested.locator(".review-action--comment").get_attribute("data-count") == "1"
    assert nested.evaluate("""node => getComputedStyle(node, '::before').backgroundColor ===
        getComputedStyle(node.querySelector('.review-action--reject')).backgroundColor""")
    assert page.locator('[data-review-summary-state="accepted"] strong').inner_text() == "1"
    assert page.locator('[data-review-summary-state="rejected"] strong').inner_text() == "3"
    assert "Shift" in nested.locator(".review-action--accept").get_attribute("aria-label")
    page.evaluate("obsFilter.setExpression('review: /^waiting$/')")
    remaining = page.locator('.paper-content p[data-review-state="waiting"]').first
    remaining.locator(".review-action--reject").dispatch_event(
        "click", {"ctrlKey": True, "shiftKey": True, "detail": 1},
    )
    assert page.locator(".comment-text-editor").count() == 3
    assert "[Full document]" in page.locator(".comment-target").last.inner_text()
    data = page.evaluate("structuredClone(obsComments.data)")
    assert [review for review in data["reviews"] if review["reviewer"] == "Bob"] == bob
    assert all(review in data["reviews"] for review in before["reviews"])
    assert any(review["chapter"] == "beta" for review in data["reviews"])
    assert any(review["item"].startswith("row-") for review in data["reviews"])
    assert page.locator('[data-review-summary-state="waiting"] strong').inner_text() == "0"
    author.fill("Bob")
    author.dispatch_event("change")
    assert int(page.locator('[data-review-summary-state="waiting"] strong').inner_text()) > 0
    assert page.evaluate("obsReport.exportChapters().some(record => record.slug === 'beta')")
    author.fill("Alice")
    author.dispatch_event("change")
    assert page.locator('[data-review-summary-state="waiting"] strong').inner_text() == "0"
    reviewed = page.evaluate("obsComments.reviewedHtml()")
    saved = tmp_path / "batch-reviewed.html"
    saved.write_text(reviewed, encoding="utf-8")
    extracted = extract_comments(saved)
    assert "[Full section]" in extracted
    for item in batch["batch"]["items"]:
        assert f"{item['chapter']} {item['item']}" in extracted
    browser, original = native_reader_report
    merge_page = browser.new_page()
    try:
        merge_page.goto(original.as_uri() + "#beta")
        merge_page.evaluate("""async html => {
            await obsComments.importFiles([{text: async () => html}]);
        }""", reviewed)
        assert merge_page.evaluate("obsComments.data.annotations") == data["annotations"]
        assert merge_page.evaluate("obsComments.data.reviews") == data["reviews"]
    finally:
        merge_page.close()
    page.goto(saved.as_uri() + "#alpha")
    assert page.evaluate("obsComments.data") == data
    assert page.evaluate("""async () => {
        const html = await obsComments.reviewedHtml();
        const before = JSON.stringify(obsComments.data);
        await obsComments.importFiles([{text: async () => html}]);
        return JSON.stringify(obsComments.data) === before;
    }""")
    # The reviewed copy restores the saved waiting-only filter, which leaves no alpha content.
    assert page.locator("[data-active-chapter]").get_attribute("data-chapter") == "home"
    page.evaluate("""obsReport.openBar('comments'); obsFilter.setExpression('');
        obsReport.activateChapter('alpha')""")
    repeated = page.locator(".paper-content p").first
    repeated.locator(".review-action--accept").click(modifiers=["Control", "Shift"])
    assert page.evaluate("obsComments.data") == data
    assert page.locator(".comment-text-editor").count() == 3
    legacy = {"version": 2, "annotations": [{
        "id": "legacy", "target": {"chapter": "beta", "quote": "Last chapter."},
        "author": "Bob", "text": "Legacy comment", "status": "open", "replies": [],
    }]}
    page.evaluate("""async data => {
        const text = '<script id="obs-comments" data-comment-island type="application/json">' +
            JSON.stringify(data) + '</script>';
        await obsComments.importFiles([{text: async () => text}]);
    }""", legacy)
    assert page.evaluate("obsComments.data.annotations.length") == 4
    assert page.evaluate("obsComments.data.annotations[1].batch") == batch["batch"]
    malformed = {**legacy, "annotations": [{**legacy["annotations"][0], "batch": {
        "scope": "section", "items": [],
    }}]}
    before_invalid = page.evaluate("structuredClone(obsComments.data)")
    page.evaluate("""async data => {
        const text = '<script id="obs-comments" data-comment-island type="application/json">' +
            JSON.stringify(data) + '</script>';
        await obsComments.importFiles([{text: async () => text}]);
    }""", malformed)
    assert page.evaluate("obsComments.data") == before_invalid
    assert "1 files rejected" in page.locator("[data-comment-announcer]").inner_text()


def test_reader_batch_generated_rows_ignore_local_view(native_reader_page) -> None:
    from playwright.sync_api import expect

    page = native_reader_page
    page.evaluate("obsReport.activateChapter('glossary'); obsReport.openBar('comments')")
    shell = page.locator("[data-data-table]").first
    # The two-row glossary fits one page, so the filter below is the local view under test.
    row = shell.locator('tr[data-row-key="glossary:bluf"]')
    row.locator("[data-table-detail-toggle]").dispatch_event("click")
    assert shell.locator(".data-table-detail-row").count() == 1
    shell.locator(".data-table-options-toggle").click()
    shell.locator(".filter-pill").filter(has_text="Filter").first.click()
    shell.locator(".data-table-filter").first.fill("BLUF")
    shell.locator(".data-table-filter").first.dispatch_event("input")
    expect(shell.locator('tr[data-row-key="glossary:bottom-line"]')).to_have_count(0)
    row = shell.locator('tr[data-row-key="glossary:bluf"]')
    row.locator(".review-action--reject").click(modifiers=["Shift"])
    assert page.locator(".comment-text-editor").count() == 1
    annotation = page.evaluate("obsComments.data.annotations[0]")
    assert annotation["batch"]["scope"] == "chapter"
    assert len(annotation["batch"]["items"]) == 2
    assert {item["item"] for item in annotation["batch"]["items"]} == {
        "row-glossary-base-1:glossary%3Abluf",
        "row-glossary-base-1:glossary%3Abottom-line",
    }
    assert page.locator('[data-review-summary-state="rejected"] strong').inner_text() == "2"
    assert row.locator(".review-action--comment").get_attribute("data-count") == "1"
    assert shell.locator(".data-table-detail-row [data-review-gutter]").count() == 0


def test_reader_batch_section_spans_continuation_pages(native_reader_page) -> None:
    page = native_reader_page
    page.evaluate("obsReport.openBar('comments')")
    paragraph = page.locator(".paper-content p").filter(has_text="Paragraph 24.").first
    paragraph.locator(".review-action--accept").click(modifiers=["Shift"])
    reviews = page.evaluate("obsComments.data.reviews")
    assert {review["item"] for review in reviews} == {f"item-{index}" for index in range(5, 30)}
    assert all(review["chapter"] == "alpha" and review["state"] == "accepted" for review in reviews)
    assert page.locator('[data-review-summary-state="accepted"] strong').inner_text() == "25"
    assert page.locator(".comment-text-editor").count() == 0


@pytest.fixture
def native_batch_page(native_reader_report, tmp_path):
    browser, _ = native_reader_report
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n- [[two]]\n", encoding="utf-8")
    (tmp_path / "one.md").write_text(
        "Introduction one.\n\nIntroduction two.\n\n# One\n\nChapter lead.\n\n"
        "## First\n\nSection lead.\n\n### Nested\n\nNested item.\n\n"
        "## Second\n\nOther section.\n", encoding="utf-8",
    )
    (tmp_path / "two.md").write_text("# Two\n\nInactive item.\n", encoding="utf-8")
    report = tmp_path.parent / f"{tmp_path.name}-report.html"
    report.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    page = browser.new_page(viewport={"width": 1920, "height": 900})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(report.as_uri() + "#one")
    page.evaluate("obsReport.openBar('comments')")
    try:
        yield page
    finally:
        page.close()
    assert errors == []


def test_reader_batch_introduction_chapter_and_keyboard(native_batch_page) -> None:
    page = native_batch_page
    intro = page.locator(".paper-content p").filter(has_text="Introduction one.").first
    intro.locator(".review-action--accept").click(modifiers=["Shift"])
    assert page.evaluate("obsComments.data.reviews.length") == 2
    assert page.locator('[data-review-summary-state="accepted"] strong').inner_text() == "2"
    lead = page.locator(".paper-content p").filter(has_text="Chapter lead.").first
    lead.locator(".review-action--reject").click(modifiers=["Shift"])
    assert page.evaluate("obsComments.data.reviews.length") == 6
    assert page.locator(".comment-text-editor").count() == 1
    assert "[Full chapter]" in page.locator(".comment-target").inner_text()
    assert len(page.evaluate("obsComments.data.annotations[0].batch.items")) == 4
    before = page.evaluate("structuredClone(obsComments.data)")
    lead.locator(".review-action--reject").click(modifiers=["Shift"])
    assert page.evaluate("obsComments.data") == before
    lead.locator(".review-action--accept").focus()
    page.keyboard.press("Control+Shift+Enter")
    assert page.evaluate("obsComments.data.reviews.length") == 6
    assert page.evaluate("obsComments.data.reviews.filter(r => r.chapter === 'two').length") == 0
    lead.locator(".review-action--accept").focus()
    page.keyboard.press("Enter")
    assert lead.locator(".review-action--accept").get_attribute("aria-pressed") == "true"
    assert page.locator(".comment-text-editor").count() == 1


def test_reader_batch_scope_ignores_collapsed_sections(native_batch_page) -> None:
    page = native_batch_page
    page.evaluate("""() => {
        const heading = [...document.querySelectorAll('h3')].find(node => node.textContent === 'Nested');
        heading.closest('.collapsible-heading').querySelector('button').click();
    }""")
    lead = page.locator(".paper-content p").filter(has_text="Section lead.").first
    lead.locator(".review-action--accept").click(modifiers=["Shift"])
    assert page.evaluate("obsComments.data.reviews.length") == 2
    nested = page.locator(".paper-content p").filter(has_text="Nested item.").first
    assert nested.get_attribute("data-review-state") == "accepted"
    assert page.locator(".paper-content p").filter(
        has_text="Other section.",
    ).get_attribute("data-review-state") == "waiting"
    before = page.evaluate("structuredClone(obsComments.data)")
    lead.locator(".review-action--reject").click(modifiers=["Shift"])
    assert page.evaluate("obsComments.data") == before
    assert page.locator(".comment-text-editor").count() == 0


def test_reader_batch_document_accepts_waiting_without_comments(native_batch_page) -> None:
    page = native_batch_page
    lead = page.locator(".paper-content p").filter(has_text="Section lead.").first
    lead.locator(".review-action--accept").click(modifiers=["Control", "Shift"])
    reviews = page.evaluate("structuredClone(obsComments.data.reviews)")
    assert any(review["chapter"] == "two" for review in reviews)
    assert all(review["state"] == "accepted" for review in reviews)
    assert page.locator('[data-review-summary-state="waiting"] strong').inner_text() == "0"
    assert page.locator(".comment-text-editor").count() == 0
    lead.locator(".review-action--reject").click(modifiers=["Control", "Shift"])
    assert page.evaluate("obsComments.data.reviews") == reviews
    assert page.locator(".comment-text-editor").count() == 0


def test_reader_table_width_includes_disclosure(native_reader_page) -> None:
    page = native_reader_page
    page.evaluate("obsReport.activateChapter('glossary')")
    for cell in page.locator(".paged-reader tr[data-row-key] td:first-child").all():
        assert cell.evaluate("""cell => {
            const buttons = cell.querySelectorAll('button');
            const toggle = buttons[0].getBoundingClientRect();
            const label = buttons[1].getBoundingClientRect();
            return label.left >= toggle.right && Math.abs(label.top - toggle.top) < 10;
        }""")
    page.evaluate("obsReport.activateChapter('alpha')")
    page.evaluate("""() => {
        const table = obsDataTable.render({
            key: 'width-check',
            columns: [{key: 'term', label: 'Term'}, {key: 'definition', label: 'Definition'}],
            rows: [
                {key: 'one', values: {term: 'Bottom line', definition: 'Conclusion'}},
                {key: 'two', parentKey: 'one', depth: 1,
                    values: {term: 'Nested concept', definition: 'Detail'}},
            ],
            hasDetails: () => true,
            renderDetails: () => document.createElement('p'),
        });
        document.querySelector('.paper-content').append(table.element);
    }""")
    page.wait_for_function("""() => {
        const cell = document.querySelector('[data-row-key="one"] td');
        const toggle = cell.querySelector('.data-table-tree-toggle').getBoundingClientRect();
        const range = document.createRange();
        range.selectNodeContents(cell);
        const text = [...range.getClientRects()].filter(rect => rect.width > 40).at(-1);
        return text && Math.abs(toggle.top - text.top) < 10;
    }""", timeout=2000)
    for key in ("one", "two"):
        assert page.locator(f'[data-row-key="{key}"] td').first.evaluate("""cell => {
            const button = cell.querySelector('button').getBoundingClientRect();
            const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
            let text;
            while (walker.nextNode()) if (!walker.currentNode.parentElement.closest('button'))
                text = walker.currentNode;
            const range = document.createRange(); range.selectNodeContents(text);
            const bounds = range.getBoundingClientRect();
            return bounds.left >= button.right && Math.abs(bounds.top - button.top) < 10 &&
                range.getClientRects().length === 1;
        }""")


def test_reader_header_options_reserve_short_final_label(native_reader_page) -> None:
    page = native_reader_page
    # Paged screens are derived layouts that drop injected nodes on relayout.
    page.evaluate("obsPages.setPaged(false)")
    page.evaluate("""() => {
        const columns = [
            ...["a", "b", "c", "d"].map((key, index) => ({
                key, label: `Column ${index}`,
            })),
            {key: "e", label: "Column 4"},
            {key: "open", label: "Open"},
        ];
        const values = Object.fromEntries(columns.map((column) => [
            column.key === "open" || column.key === "e"
                ? "No" : "A wide value ".repeat(20),
        ]));
        const table = obsDataTable.render({
            key: "header-options-width",
            columns,
            rows: [{key: "one", values}],
        });
        document.querySelector("[data-chapter-body]").append(table.element);
    }""")
    page.wait_for_function("""() => {
        const header = document.querySelector(
            '[data-data-table="header-options-width"] .data-table-last-header',
        );
        return header && header.getBoundingClientRect().width > 0;
    }""", timeout=3000)
    header_selector = (
    '[data-data-table="header-options-width"] .data-table-last-header'
    )
    page.wait_for_function("""() => {
    const header = document.querySelector(
        '[data-data-table="header-options-width"] .data-table-last-header',
    );
    const range = document.createRange();
    range.selectNodeContents(header.querySelector('span'));
    return range.getClientRects().length === 1;
    }""", timeout=3000)
    measure = lambda: page.locator(header_selector).evaluate("""header => {
    const range = document.createRange();
    range.selectNodeContents(header.querySelector('span'));
    const textRects = [...range.getClientRects()];
    const icon = header.querySelector('.data-table-options-toggle')?.getBoundingClientRect();
    const resize = header.querySelector('.data-table-column-resize').getBoundingClientRect();
    return {
        key: header.dataset.columnKey,
        lines: textRects.length,
        labelRight: textRects.at(-1)?.right,
        iconLeft: icon?.left,
        handleLeft: resize.left,
    };
    }""")
    ordinary = measure()
    assert ordinary["key"] == "open"
    assert ordinary["lines"] == 1
    assert page.locator(
    '[data-data-table="header-options-width"] .data-table-scroll',
    ).evaluate("node => node.scrollWidth <= node.clientWidth + 1")

    page.set_viewport_size({"width": 460, "height": 900})
    page.wait_for_function("""() => {
    const header = document.querySelector(
        '[data-data-table="header-options-width"] .data-table-last-header',
    );
    const range = document.createRange();
    range.selectNodeContents(header.querySelector('span'));
    return range.getClientRects().length === 1;
    }""", timeout=3000)
    measurement = measure()
    assert measurement["lines"] == 1
    assert measurement["labelRight"] <= measurement["iconLeft"]
    assert measurement["labelRight"] <= measurement["handleLeft"]

    page.locator(
    '[data-data-table="header-options-width"] th[data-column-key="open"]',
    ).focus()
    page.keyboard.press("Alt+ArrowLeft")
    page.wait_for_function("""() => {
    const header = document.querySelector(
        '[data-data-table="header-options-width"] .data-table-last-header',
    );
    const range = document.createRange();
    range.selectNodeContents(header.querySelector('span'));
    return header.dataset.columnKey === "e" &&
        range.getClientRects().length === 1 &&
        header.querySelector('.data-table-options-toggle');
    }""", timeout=3000)
    measurement = measure()
    assert measurement["labelRight"] <= measurement["iconLeft"]
    assert measurement["labelRight"] <= measurement["handleLeft"]
    page.evaluate("""() => {
    const shell = document.querySelector('[data-data-table="header-options-width"]');
    shell.querySelector('.data-table-options-toggle').click();
    [...shell.querySelectorAll('.filter-pill')]
        .find(button => button.textContent === "Properties").click();
    [...shell.querySelectorAll(
        '.data-table-panel[aria-label="Properties"] .filter-pill',
    )].find(button => button.textContent === "Column 4").click();
    }""")
    page.wait_for_function("""() => {
    const header = document.querySelector(
        '[data-data-table="header-options-width"] .data-table-last-header',
    );
    const range = document.createRange();
    range.selectNodeContents(header.querySelector('span'));
    return header.dataset.columnKey === "open" &&
        range.getClientRects().length === 1 &&
        header.querySelector('.data-table-options-toggle');
    }""", timeout=3000)
    measurement = measure()
    assert measurement["labelRight"] <= measurement["iconLeft"]
    assert measurement["labelRight"] <= measurement["handleLeft"]


def run_report_dom_contract(report: Path, mode: str, *runtimes: Path, arguments: tuple[str, ...] = ()) -> str:
    module = os.environ.get("OBS_HTML_TEST_DOM_MODULE") or str(
        ROOT / "test" / "browser" / "node_modules" / "linkedom"
    )
    node = shutil.which("node")
    assert node, "The observable report contracts require the existing Node adapter."
    assert Path(module).is_dir(), "Set OBS_HTML_TEST_DOM_MODULE to the existing linkedom adapter."
    paths = [str(path) for path in runtimes]
    paths.extend([""] * (3 - len(paths)))
    result = subprocess.run(
        [node, str(ROOT / "test" / "browser" / "report-ui.cjs"), str(report),
         module, *paths, mode, *arguments],
        text=True, encoding="utf-8", capture_output=True, cwd=ROOT, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def run_browser_script(script: str, payload: object = None) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for browser-runtime checks.")
    bootstrap = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const root = "src\\obs_html\\";
const context = vm.createContext({
    document: {querySelector: selector => ({textContent: fs.readFileSync(
        root + (selector.includes("assets.schema.json") ? "assets.schema.json" : "base.schema.json"), "utf8",
    )})},
});
for (const file of ["vendor\\js-yaml.min.js", "base.js", "query.js"]) {
    vm.runInContext(fs.readFileSync(root + file, "utf8"), context);
}
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
"""
    result = subprocess.run(
        [node, "-e", bootstrap + script],
        input=json.dumps(payload), text=True, capture_output=True, cwd=ROOT, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"),
                    reason="Set OBS_HTML_TEST_NATIVE_BROWSER for native paged layout checks.")
def test_native_live_pages_and_split_pdf(tmp_path: Path, native_reader_report) -> None:
    from io import BytesIO
    from pypdf import PdfReader

    manifest = tmp_path / "manifest.md"
    manifest.write_text(
        "---\ntitle: Live pages\norganization: TEMP\nproduct: {name: SE Harness}\n"
        'history: [{version: "00*", author: Ada, change: First draft}]\n---\n'
        "- [[prose]]\n- [[records]]\n- [[listing]]\n", encoding="utf-8",
    )
    (tmp_path / "prose.md").write_text(
        "# Prose\n\n## Context\n\n" + "A deliberately long paragraph for reading diagnostics. " * 30 +
        "\n\n" + "\n\n".join(f"Supporting paragraph {index}. " + "Preserved context. " * 12
                              for index in range(35)),
        encoding="utf-8",
    )
    (tmp_path / "records.md").write_text(
        '# Records\n\n```base\nobsHtml: {records: glossary}\n'
        "views:\n  - type: table\n    order: [term, definition]\n```\n", encoding="utf-8",
    )
    for index in range(65):
        definition = "Oversized cell text. " * 600 if index == 30 else f"Definition for entry {index}."
        (tmp_path / f"entry-{index}.md").write_text(
            f"---\nkind: glossary\nterm: Entry {index:02}\ndefinition: {definition}\n---\n"
            f"# Entry {index:02}\n\nExpanded detail {index}.\n", encoding="utf-8",
        )
    code = "\n".join(f"{index:02} " + "x" * 77 for index in range(80))
    (tmp_path / "listing.md").write_text(
        "# Listing\n\n## Ordered items\n\n" +
        "\n".join(f"{index}. List item {index}." for index in range(1, 101)) +
        "\n\n## Code\n\n```text\n" + code + "\n```\n", encoding="utf-8",
    )
    html = tmp_path / "live.html"
    html.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    with native_reader_report[0].new_context() as context:
        try:
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(html.as_uri())
            assert page.locator("html").get_attribute("data-theme") == "light"
            assert page.locator("html").evaluate("(root) => root.classList.contains('paged-mode')")
            assert page.locator('[data-page-chapter="home"] table').count() == 0
            assert page.locator('[data-page-chapter="home"] .cover-facts-frame').count() == 1
            assert page.locator('[data-page-chapter="@metadata"]').count() == 0
            assert len(page.locator(".contents-page-number").all_text_contents()) == 3
            page.evaluate("obsReport.activateChapter('records')")
            shell = page.locator(".paged-reader .data-table-shell")
            assert shell.count() == 1
            assert shell.locator(".data-table-footer").is_visible()
            shell.locator("tr[data-row-key] .data-table-tree-toggle").first.click()
            assert shell.locator(".data-table-detail-row").is_visible()
            assert "Expanded detail" in shell.locator(".data-table-detail-row").inner_text()
            shell.locator("tr[data-row-key] .data-table-tree-toggle").first.click()
            shell.locator("th").first.click()
            assert shell.locator("th").first.get_attribute("aria-sort") == "ascending"
            shell.locator("th").first.click()
            assert shell.locator("th").first.get_attribute("aria-sort") == "descending"
            width = shell.locator("col").first.get_attribute("style")
            shell.locator(".data-table-column-resize").first.press("ArrowRight")
            assert shell.locator("col").first.get_attribute("style") != width
            assert page.locator("[data-active-chapter]").get_attribute("data-chapter") == "records"
            page.evaluate("window.liveTable = document.querySelector('[data-data-table]')")
            page.evaluate("obsPages.setPaged(false); obsPages.setPaged(true)")
            assert page.evaluate("liveTable === document.querySelector('[data-data-table]')")
            assert shell.locator("th").first.get_attribute("aria-sort") == "descending"
            shell.locator(".data-table-options-toggle").click()
            shell.get_by_text("Query view", exact=True).click()
            editor = shell.locator("textarea")
            assert editor.is_visible()
            editor.fill(page.evaluate("""text => {
                const definition = obsBases.parse(text);
                definition.views[0].order = ['definition', 'term'];
                return obsBases.dump(definition);
            }""", editor.input_value()))
            editor.blur()
            assert shell.locator("th").first.inner_text().startswith("definition")
            page.evaluate("obsPages.setPaged(false); obsPages.setPaged(true)")
            assert shell.locator("th").first.inner_text().startswith("definition")
            page.evaluate("obsReport.activateChapter('listing')")
            assert page.locator(".paged-reader ol").count() == 1
            assert page.locator(".paged-reader ol li").count() == 100
            assert page.locator(".paged-reader pre").count() == 1
            assert page.locator(".paged-reader pre code").inner_text() == code + "\n"
            assert page.locator(".paged-reader pre").evaluate(
                "(pre) => pre.scrollWidth <= pre.clientWidth + 1")
            assert page.locator(".paged-reader .paper-sheet").evaluate_all(
                "(sheets) => sheets.some(sheet => sheet.clientHeight > 1123)")
            page.evaluate("obsReport.activateChapter('prose')")
            assert page.locator("p[data-paragraph-lines]").count() == 0
            visible_sheets = page.locator(".paged-reader .paper-sheet:visible")
            original_count = visible_sheets.count()
            assert original_count > 1
            toggle = page.locator(".paged-reader [data-heading-toggle]").first
            toggle.click()
            assert visible_sheets.count() == 1
            assert visible_sheets.first.evaluate("(sheet) => sheet.clientHeight") < 350
            assert page.locator(".paged-reader .paper-sheet:visible p:visible").count() == 0
            toggle.click()
            assert visible_sheets.count() == original_count
            assert page.locator(".paged-reader p").count() == 36
            page.evaluate("obsReport.openBar('comments')")
            assert page.locator(".paper-content .review-gutter").first.evaluate("""gutter => {
                const page = gutter.closest('.paper-sheet').getBoundingClientRect();
                const reader = document.querySelector('[data-chapter-scroll]').getBoundingClientRect();
                const bounds = gutter.getBoundingClientRect();
                return bounds.right < page.left && bounds.left >= reader.left;
            }""")
            first_item = page.locator(".paper-content p[data-review-item]").first
            first_item.locator(".review-action--accept").click()
            assert first_item.get_attribute("data-review-state") == "accepted"
            page.evaluate("""() => {
                const text = [...document.querySelector('.paper-content p').childNodes]
                    .find(node => node.nodeType === Node.TEXT_NODE);
                const range = document.createRange();
                range.setStart(text, 0); range.setEnd(text, 14);
                getSelection().removeAllRanges(); getSelection().addRange(range);
                document.dispatchEvent(new Event('selectionchange'));
            }""")
            page.locator("[data-comment-add]").click()
            assert page.evaluate("obsComments.data.annotations[0].target.quote") == "A deliberately"
            root_comment = page.locator(".comment-node").first
            root_comment.locator(".comment-text-editor").first.fill("Review this sentence.")
            root_comment.get_by_role("button", name="Reply", exact=True).first.click()
            page.locator(".comment-node .comment-node .comment-text-editor").fill("Nested reply.")
            assert page.evaluate("obsComments.data.annotations[0].replies[0].text") == "Nested reply."
            root_comment.get_by_role("button", name="Resolve", exact=True).first.click()
            assert page.evaluate("obsComments.data.annotations[0].status") == "resolved"
            root_comment.get_by_role("button", name="Reopen", exact=True).first.click()
            reviewed = page.evaluate("obsComments.reviewedHtml()")
            assert '"text":"Nested reply."' in reviewed
            reviewed_path = tmp_path / "reviewed.html"
            reviewed_path.write_text(reviewed, encoding="utf-8")
            page.locator("[data-comment-files]").set_input_files(reviewed_path)
            page.wait_for_function("document.querySelector('[data-comment-announcer]').textContent.includes('loaded')")
            assert page.evaluate("obsComments.data.annotations.length") == 1
            # Reload the saved copy to verify that paged content and reviews rebuild from their owners.
            saved_page = context.new_page()
            saved_page.on("pageerror", lambda error: errors.append(str(error)))
            saved_page.goto(reviewed_path.as_uri() + "#prose")
            assert saved_page.locator("html").evaluate("(root) => root.classList.contains('paged-mode')")
            saved_page.evaluate("""() => {
                if (document.querySelector('[data-bar="comments"]').hidden) obsReport.openBar('comments');
            }""")
            assert saved_page.evaluate("obsComments.data.annotations[0].replies[0].text") == "Nested reply."
            assert saved_page.locator(".paper-content p").first.get_attribute("data-review-state") == "accepted"
            saved_page.evaluate("obsPages.setPaged(false); obsReport.activateChapter('prose')")
            assert saved_page.evaluate("""() => [...CSS.highlights.get('obs-comments')][0].toString()""") == "A deliberately"
            saved_page.close()
            page.evaluate("obsPages.setPaged(true); window.print = () => {}")
            page.evaluate("obsPages.exportPDF()")
            assert page.locator(".print-book [data-contents-chapter]").evaluate_all("""numbers =>
                numbers.every(number => Number(number.textContent) ===
                    [...document.querySelectorAll('.print-book .paper-sheet')].findIndex(
                        sheet => sheet.dataset.pageChapter === number.dataset.contentsChapter) + 1)""")
            tables = page.locator('.print-book [data-page-chapter="records"] table')
            assert tables.count() > 2
            assert tables.evaluate_all("""tables => tables.every(table =>
                table.querySelectorAll('thead th').length === 2 &&
                table.querySelectorAll('tbody tr').length > 0 &&
                [...table.querySelectorAll('tbody tr')].every(row => row.cells.length === 2))""")
            split_text = "".join(page.locator(
                '.print-book [data-row-key="glossary:entry-30"] > td:first-child').all_text_contents())
            assert "".join(split_text.split()).count("Oversizedcelltext.") == 600
            assert page.locator(".print-book .paper-content").evaluate_all(
                "(pages) => pages.every(page => page.scrollHeight <= page.clientHeight + 1)")
            assert page.locator('.print-book [data-page-chapter="listing"] ol').count() > 1
            assert page.locator('.print-book [data-page-chapter="listing"] h2').evaluate_all(
                "(headings) => headings.every(heading => heading.nextElementSibling !== null)")
            assert page.locator('.print-book [data-page-chapter="listing"] ol li').count() == 100
            assert "".join("".join(page.locator(
                '.print-book [data-page-chapter="listing"] pre').all_text_contents()).split()) == "".join(code.split())
            starts = page.locator('.print-book [data-page-chapter="listing"] ol').evaluate_all(
                "(lists) => lists.map(list => list.start)")
            assert starts == sorted(set(starts))
            assert page.locator(".print-book .data-table-controls").count() == 0
            pdf = PdfReader(BytesIO(page.pdf(prefer_css_page_size=True, print_background=True)))
            text = "\n".join(sheet.extract_text() for sheet in pdf.pages)
            normalized = "".join(text.split())
            assert "Listitem100." in normalized and "Entry64" in normalized
            assert "Oversizedcelltext." in normalized
            assert not errors
        finally:
            page.close()


def test_browser_and_generation_share_definition_validation() -> None:
    valid = {"views": [{"type": "table", "order": ["chapter", "project status"]}]}
    viewport = {**valid, "obsHtml": {"maxRows": 10}}
    definitions = [
        valid,
        viewport,
        {**valid, "filters": {"and": ['chapter != null', 'note["project status"] != null']}},
        {**valid, "filters": {"not": {"or": ['type == "risk"', 'type != "issue"']}}},
        {**valid, "filters": "unsupported()"},
        {**valid, "filters": {"or": []}},
        {**valid, "unknown": True},
        {**valid, "properties": {"chapter": {"formula": "unsupported"}}},
        {**valid, "obsHtml": {"unknown": True}},
        {**valid, "obsHtml": {"maxRows": 0}},
        {**valid, "obsHtml": {"maxRows": -1}},
        {**valid, "obsHtml": {"maxRows": 1.5}},
        {**valid, "obsHtml": {"maxRows": "10"}},
        {**valid, "obsHtml": {"maxRows": {"value": 10}}},
        {"views": [{"type": "table", "order": []}]},
        {"views": [{"type": "table", "order": ["chapter", "chapter"]}]},
        {"views": [{"type": "table", "order": ["chapter"], "groupBy": {"property": " "}}]},
        {"views": [{"type": "table", "order": ["chapter"], "sort": {"property": "chapter", "direction": "SIDEWAYS"}}]},
        {**valid, "properties": {"help": {"obsHtml": {"icon": {
            "name": "a" * 33 + "." + "b" * 33, "label": "Shared long ID", "help": "Valid",
        }}}}},
        {**valid, "properties": {"help": {"obsHtml": {"icon": {
            "name": "a" * 65, "label": "Overlong segment", "help": "Invalid",
        }}}}},
    ]
    expected = [
        True, True, True, True, False, False,
        False, False, False, False, False, False,
        False, False, False, False, False, False,
        True, False,
    ]
    for definition, accepted in zip(definitions, expected, strict=True):
        if accepted:
            validate_base_definition(definition, Path("test.md"))
        else:
            with pytest.raises(ContentError):
                validate_base_definition(definition, Path("test.md"))
    run_browser_script(
        r"""
const results = payload.definitions.map(definition => {
    try { context.obsBases.validate(definition); return true; }
    catch { return false; }
});
assert.deepEqual(results, payload.expected);
for (const definition of payload.definitions.filter((_, index) => payload.expected[index])) {
    assert.equal(JSON.stringify(context.obsBases.parse(context.obsBases.dump(definition))), JSON.stringify(definition));
}
""", {"definitions": definitions, "expected": expected},
    )


def test_browser_yaml_and_queries_handle_spaced_fields_and_errors() -> None:
    run_browser_script(r"""
const yaml = `filters:
  and:
    - chapter == "One"
    - note["project status"] != null
views:
  - type: table
    order: [chapter, project status]
`;
const definition = context.obsBases.parse(yaml);
const query = context.obsQuery.compile(context.obsBases.filterExpression(definition.filters));
assert.equal(query.match({fields: {chapter: "One", "project status": "Result"}}), true);
assert.equal(query.match({fields: {chapter: "One"}}), false);
assert.equal(query.match({fields: {chapter: "Two", "project status": "Result"}}), false);
assert.equal(context.obsQuery.compile('"project status": result').match({fields: {"project status": "RESULT"}}), true);
assert.equal(context.obsQuery.compile('NOT "project status": result').match({fields: {"project status": "other"}}), true);
const exact = context.obsQuery.compile(context.obsBases.filterExpression('chapter == "One"'));
assert.equal(exact.match({fields: {chapter: "One"}}), true);
assert.equal(exact.match({fields: {chapter: "Someone"}}), false);
const slash = context.obsQuery.compile(context.obsBases.filterExpression('chapter == "A/B"'));
assert.equal(slash.match({fields: {chapter: "A/B"}}), true);
const quotedValue = 'A "quoted" \\ path';
const escaped = context.obsQuery.compile(`chapter:${JSON.stringify(quotedValue)}`);
assert.equal(escaped.match({fields: {chapter: quotedValue}}), true);
assert.equal(escaped.match({fields: {chapter: "A quoted path"}}), false);
for (const invalid of [
    "views: [",
    "views: []",
    "views: []\nviews: []",
    "views: &cycle [*cycle]",
    "!!js/function function() {}",
    "filters: arbitrary()\nviews: [{type: table, order: [chapter]}]",
]) assert.throws(() => context.obsBases.parse(invalid));
""")


def test_comment_export_dom_contract(tmp_path: Path) -> None:
    node = shutil.which("node")
    modules = os.environ.get("NODE_PATH", "").split(os.pathsep)
    module = os.environ.get("OBS_HTML_TEST_DOM_MODULE") or next(
        (str(Path(path) / "linkedom") for path in modules
         if (Path(path) / "linkedom").is_dir()),
        str(ROOT / "test" / "browser" / "node_modules" / "linkedom"),
    )
    if not node or not Path(module).is_dir():
        pytest.skip("Set OBS_HTML_TEST_DOM_MODULE to the installed linkedom module.")
    (tmp_path / "manifest.md").write_text("- [[parent|Parent]]\n- [[child|Child]]\n", encoding="utf-8")
    (tmp_path / "parent.md").write_text(
        "# Parent\n\n## Context\n\nQuote Ω on the first line.\nSecond line.\n",
        encoding="utf-8",
    )
    (tmp_path / "child.md").write_text(
        "# Child\n\nInactive paragraph.\n", encoding="utf-8",
    )
    report = tmp_path / "report.html"
    report.write_text(
        render_report(tmp_path / "manifest.md", parse_manifest(tmp_path / "manifest.md")),
        encoding="utf-8",
    )
    package = files("obs_html")
    runtimes = [str(package / "bars" / "comments.js"), str(package / "bars" / "settings.js"),
                str(package / "storage.js")]
    result = subprocess.run(
        [node, str(ROOT / "test" / "browser" / "report-ui.cjs"), str(report), module,
         *runtimes, "--comments-only"],
        text=True, capture_output=True, cwd=ROOT, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("paged", [False, True])
@pytest.mark.parametrize("width", [390, 460, 760])
def test_reader_navigation_gutters_leave_table_controls_clickable(
    native_reader_page, paged, width,
) -> None:
    from playwright.sync_api import expect

    page = native_reader_page
    page.set_viewport_size({"width": width, "height": 900})
    page.evaluate("""paged => {
        obsReport.activateChapter('glossary');
        obsPages.setPaged(paged);
    }""", paged)
    shell = page.locator('[data-chapter-body] .data-table-shell')
    for control in (
        shell.locator(".data-table-tree-toggle").first,
        shell.locator(".data-table-options-toggle"),
    ):
        control.scroll_into_view_if_needed()
        assert control.evaluate("""node => {
            const bounds = node.getBoundingClientRect();
            const hit = document.elementFromPoint(
                bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
            return node === hit || node.contains(hit);
        }""")
        control.click(timeout=3000)
    expect(shell.locator(".data-table-detail-row")).to_be_visible()
    expect(shell.get_by_role("button", name="Query view", exact=True)).to_be_visible()
    page.keyboard.press("Escape")
    page.locator('[data-step="1"]').click()
    expect(page.locator("[data-active-chapter]")).to_have_attribute("data-chapter", "alpha")


@pytest.mark.parametrize("restored", [False, True])
def test_query_editor_uses_table_local_session_state_and_reports_errors(
    native_reader_page, tmp_path, restored,
) -> None:
    from playwright.sync_api import expect

    page = native_reader_page
    page.evaluate("obsReport.activateChapter('glossary')")
    shell = page.locator('[data-chapter-body] [data-data-table="glossary-base-1"]')
    columns = lambda: shell.locator("thead th").evaluate_all(
        "headers => headers.map(header => header.dataset.columnKey)",
    )
    shell.locator(".data-table-column-resize").first.press("ArrowRight")
    resized = shell.locator("col").first.get_attribute("style")
    # Resized widths are session-only view state, never saved reader state.
    presentation = page.evaluate(
        "JSON.parse(obsReport.serializeModel()).readerState.tables['glossary-base-1']",
    )
    assert presentation is None
    if restored:
        saved = tmp_path / "reviewed.html"
        saved.write_text(page.evaluate("obsComments.reviewedHtml()"), encoding="utf-8")
        page.goto(saved.as_uri() + "#glossary")
        assert page.evaluate(
            "JSON.parse(obsReport.serializeModel()).readerState.tables['glossary-base-1']",
        ) == presentation
        assert shell.locator("col").first.get_attribute("style") != resized
        shell.locator(".data-table-column-resize").first.press("ArrowRight")
        resized = shell.locator("col").first.get_attribute("style")

    shell.locator(".data-table-options-toggle").click()
    shell.get_by_role("button", name="Query view", exact=True).click()
    editor = shell.get_by_role("textbox", name="Table base YAML definition")
    authored = editor.input_value()
    editor.fill("views: [")
    editor.blur()
    expect(editor).to_have_attribute("aria-invalid", "true")
    expect(shell.get_by_role("alert").filter(visible=True)).to_be_visible()
    assert columns() == ["term", "definition"]
    assert shell.locator("tbody tr[data-row-key]").count() == 2
    assert page.evaluate(
        "JSON.parse(obsReport.serializeModel()).readerState.tables['glossary-base-1']",
    ) == presentation
    assert shell.locator("col").first.get_attribute("style") == resized
    page.evaluate("obsReport.activateChapter('alpha'); obsReport.activateChapter('glossary')")
    expect(editor).to_have_value("views: [")
    editor.fill(page.evaluate("""text => {
        const definition = obsBases.parse(text);
        definition.views[0].order = ['definition', 'term'];
        definition.filters = 'term == "BLUF"';
        return obsBases.dump(definition);
    }""", authored))
    editor.blur()
    assert columns() == ["definition", "term"]
    assert shell.locator("tbody tr[data-row-key]").count() == 1
    assert page.evaluate(
        "JSON.parse(obsReport.serializeModel()).readerState.tables['glossary-base-1']",
    ) is None
    page.evaluate("obsReport.activateChapter('alpha'); obsReport.activateChapter('glossary')")
    assert columns() == ["definition", "term"]
    assert shell.locator("tbody tr[data-row-key]").count() == 1
    canonical = page.evaluate("""() => JSON.parse(obsReport.serializeModel())
        .notes.find(note => note.slug === 'glossary').tables[0].definition""")
    assert canonical["views"][0]["order"] == ["term", "definition"]


def test_complete_document_dom_interactions(tmp_path: Path) -> None:
    module = os.environ.get("OBS_HTML_TEST_DOM_MODULE") or str(
        ROOT / "test" / "browser" / "node_modules" / "linkedom"
    )
    node = shutil.which("node")
    if not Path(module).is_dir() or not node:
        if os.environ.get("OBS_HTML_REQUIRE_DOM") == "1":
            pytest.fail("Browser checks require Node and the DOM adapter: npm --prefix test/browser ci")
        pytest.skip("Set OBS_HTML_TEST_DOM_MODULE to an installed linkedom module to run DOM integration.")
    notes = {
        "parent": "# Parent\n\n[[node#Extra]]\n\n[1](reference.md)\n",
        "child": "---\nbottom line: Child result.\n---\n# Child\n\nQuestion. #mark/question/child_question\n\nResolve this. #mark/open_point/child_open\n",
        "node": (
            "---\nbottom line: Node result.\nowner: {team: [Ada, Lin]}\n"
            f"description: {'Long metadata ' * 20}\nstatus: draft\nextra: omitted\n"
            "---\n# Node\n\n## Extra\n\n" + "Long prose for the preview. " * 40 +
            "\n\n```text\nCODE MUST NOT APPEAR\n```\n\n"
            "```base\nfilters: 'kind == \"quantity\"'\n"
            "properties:\n  citation:\n    displayName: Citation\n"
            "views:\n  - type: table\n    order: [citation]\n```\n"
        ),
        "flatness": (
            "---\nkind: quantity\nvalue: 20\nunit: µm\naliases: [flatness_A]\n"
            "source: '[[details]]'\n"
            "citation: 'See [[details]] **sheet 2** and $x$.'\n---\n# Flatness\n\n"
            "Canonical datum A flatness.\n"
        ),
        "glossary": (
            '# Glossary\n\n```base\nobsHtml: {records: glossary}\n'
            "views:\n  - type: table\n    order: [term, definition]\n```\n\n"
            "```base\nfilters: 'table == \"abbreviations\"'\n"
            "properties:\n  term:\n    displayName: Term\n"
            "  citation:\n    displayName: Citation\n"
            "views:\n  - type: table\n    order: [term, citation]\nobsHtml: {records: glossary}\n```\n"
        ),
        "tags": (
            '# Tags\n\n```base\nobsHtml: {records: tag}\n'
            "views:\n  - type: table\n    order: [label, text, source]\n```\n"
        ),
        "bottom-line": (
            "---\nkind: glossary\nterm: Bottom line\naliases: [bottom line]\n"
            "definition: The conclusion.\ntable: abbreviations\n"
            "citation: 'See [[details]] **source note**.'\n---\n# Bottom line\n"
        ),
        "bluf": (
            "---\nkind: glossary\nterm: BLUF\naliases: [Bottom line upfront]\n"
            "definition: The principle of presenting the [[bottom line]] first.\n---\n# BLUF\n\n[[details]]\n"
            "\n```base\nobsHtml: {records: glossary}\n"
            "views:\n  - type: table\n    order: [term, definition]\n```\n"
        ),
        "details": "# Extra details\n\n[[bottom line]] [[metadata-only]]\n\n## More\n\nNested content.\n",
        "metadata-only": "---\nowner: Ada\ncitation: '**Canonical** [[details]]'\n---\n",
        "reference": (
            "---\ndocument: '[Source document](details.md)'\n"
            "description: A source whose metadata is its complete content.\nkind: reference\n---\n"
        ),
        "quiet-reference": (
            "---\ndocument: Unlinked source\n"
            "description: Selected only by a Bases query.\nkind: reference\n---\n"
        ),
        "references": (
            "# References\n\n```base\nfilters: 'kind == \"reference\"'\n"
            "properties:\n  obsHtml.label:\n    displayName: No.\n"
            "views:\n  - type: table\n    order: [obsHtml.label, document, description]\n"
            "obsHtml:\n  members:\n    - path: reference.md\n      label: '[1]'\n"
            "    - path: quiet-reference.md\n      label: '[2]'\n```\n\n"
            "```base\nfilters: 'kind == \"reference\"'\n"
            "views:\n  - type: table\n    order: [obsHtml.label, document]\n"
            "obsHtml:\n  members:\n    - path: quiet-reference.md\n      label: B\n"
            "    - path: reference.md\n      label: A\n```\n"
        ),
        "unreferenced": "# Not included\n\n[[missing]]\n",
    }
    shared_image = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a8xoAAAAASUVORK5CYII="
    )
    (tmp_path / "shared.png").write_bytes(shared_image)
    notes["parent"] += "\n![Shared image](shared.png)\n"
    notes["child"] += "\n![Shared image](shared.png)\n"
    for name, source in notes.items():
        (tmp_path / f"{name}.md").write_text(source, encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text(
        "---\ntitle: Test document\n"
        "subtitle: 'Bridge **subtitle** ![Obsidian](https://example.invalid/obsidian.svg) "
        "![HTML](https://example.invalid/html.svg)'\n"
        "status: active\nowners: {team: [Ada, Lin]}\n"
        "---\n"
        "- [[parent|Parent]]\n  - [[child|Child]]\n    - [[node|Node]]\n"
        "- [[glossary|Glossary]]\n- [[tags|Tags]]\n- [[references|References]]\n"
        "\n> [!important]\n> Abstract prose.\n"
        "\n```base\nfilters: 'note[\"bottom line\"] != null'\n"
        "views:\n  - type: table\n    name: Bottom lines\n    order: [chapter, bottom line]\n"
        "obsHtml: {records: chapter}\n```\n"
        "\n## Metadata\n"
        "\n```base\nfilters:\n  not:\n    or:\n      - 'key == \"title\"'\n      - 'key == \"subtitle\"'\n"
        "views:\n  - type: table\n    name: Metadata\n    order: [key, value]\n"
        "obsHtml: {records: documentMetadata}\n```\n",
        encoding="utf-8",
    )
    report = tmp_path / "report.html"
    report.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    package = files("obs_html")
    result = subprocess.run(
        [node, str(ROOT / "test" / "browser" / "report-ui.cjs"), str(report), module,
         str(package / "bars" / "comments.js"), str(package / "bars" / "settings.js"),
         str(package / "storage.js")],
        text=True, capture_output=True, cwd=ROOT, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
