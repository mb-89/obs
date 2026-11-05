import copy
import json
import os
from html import escape
from pathlib import Path

import pytest
import yaml

from obs_html_interim.content import ContentError, parse_manifest, validate_base_definition
from obs_html_interim.renderer import render_artifact
from test_reader_controls import _write_reader_fixture, definition, reader_browser


MARKUP = '<p>Pressure <strong>above</strong> 5%.</p><ul><li>First</li><li>Second</li></ul>'


def rich_definition():
    spec = definition()
    reference = spec["properties"]["subject"]["obsHtml"]["reference"]
    reference["metadataFormats"] = {
        "item.description": {"format": "html", "source": "item.descriptionHtml"},
        "item.testSteps": {"format": "table", "source": "item.testStepTable"},
        "item.content": {"format": "html", "source": "item.descriptionHtml"},
        "item.acceptanceCriteria": {"format": "html", "source": "item.acceptanceCriteriaHtml"},
    }
    return spec


def test_rich_metadata_formats_validate_and_roundtrip():
    from test_browser import run_browser_script

    spec = rich_definition()
    validate_base_definition(spec, Path("rich.md"))
    run_browser_script("""
        context.obsBases.validate(payload);
        assert.deepEqual(JSON.parse(JSON.stringify(context.obsBases.parse(
            context.obsBases.dump(payload)))), payload);
    """, spec)


@pytest.mark.parametrize("value", [
    {"format": "script"},
    {"format": "html", "source": 1},
    {"source": "item.descriptionHtml"},
    {"format": "table", "unknown": True},
])
def test_rich_metadata_formats_reject_invalid_declarations(value):
    from test_browser import run_browser_script

    spec = rich_definition()
    spec["properties"]["subject"]["obsHtml"]["reference"]["metadataFormats"]["item.description"] = value
    with pytest.raises(ContentError, match=r"Invalid base definition|; see capabilities/bases\."):
        validate_base_definition(spec, Path("rich.md"))
    run_browser_script("assert.throws(() => context.obsBases.validate(payload));", spec)


def _rich_fixture(tmp_path, item):
    manifest = _write_reader_fixture(tmp_path)
    chapter = tmp_path / "chapter.md"
    text = chapter.read_text(encoding="utf-8")
    block = text.split("```base\n")[1].split("```")[0]
    spec = yaml.safe_load(block)
    reference = spec["properties"]["subject"]["obsHtml"]["reference"]
    reference["metadataFormats"] = copy.deepcopy(
        rich_definition()["properties"]["subject"]["obsHtml"]["reference"]["metadataFormats"])
    reference["metadata"] = list(reference["metadataFormats"])
    chapter.write_text(text.replace(block, yaml.safe_dump(spec)), encoding="utf-8")
    subject = tmp_path / "subject.md"
    source = subject.read_text(encoding="utf-8")
    _, frontmatter, body = source.split("---", 2)
    metadata = yaml.safe_load(frontmatter)
    metadata["item"].update(item)
    subject.write_text("---\n" + yaml.safe_dump(metadata) + "---" + body, encoding="utf-8")
    artifact = tmp_path / "rich.html"
    artifact.write_text(render_artifact(manifest, parse_manifest(manifest)), encoding="utf-8")
    return artifact


def _open_rich_detail(page, artifact):
    page.goto(artifact.as_uri())
    page.evaluate("obsHtmlReady")
    page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('chapter')")
    page.evaluate("obsArtifact.whenChapterReady()")
    table_view = page.locator("[data-active-chapter] [data-data-table]")
    table_view.locator(".data-table-tree-toggle").first.click()
    return table_view.locator("[data-detail-owner]").first


@pytest.mark.parametrize("markup", [
    MARKUP,
    escape(MARKUP),
    escape(escape(MARKUP)),
    escape('<html xmlns="http://catalog.com/xml-export"><body>' + MARKUP + '</body></html>'),
    '<p style="font-size:99px" onclick="window.richInjected=1">Pressure <strong>above</strong> 5%.</p>'
    '<ul><li>First</li><li>Second</li></ul>'
    '<script>window.richInjected=1</script><img src="https://example.invalid/image" onerror="window.richInjected=1">'
    '<iframe src="https://example.invalid/frame"></iframe><a href="javascript:window.richInjected=1">Unsafe link</a>',
])
def test_native_imported_markup_and_steps_keep_structure_without_active_content(
    tmp_path, reader_browser, markup,
):
    from playwright.sync_api import expect

    table = {
        "headers": ["Step No.", "Action", "Expected Result", "OE"],
        "rows": [[
            '<html xmlns="http://catalog.com/xml-export"><p>1</p></html>',
            '<html xmlns="http://catalog.com/xml-export"><p>Check the risk analysis.</p></html>',
            '<p>Signed <em>and</em> released; pressure &lt;25kg.</p>',
            "<p>Y</p>",
        ]],
    }
    artifact = _rich_fixture(tmp_path, dict(
        description="Flattened description",
        descriptionHtml=markup,
        testSteps="5%Schema description.40%Action schema.45%Result schema.10%Evidence schema.",
        testStepTable=table,
    ))
    page = reader_browser.new_page(viewport={"width": 1500, "height": 1000})
    errors = []
    requests = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    def block_network(route):
        requests.append(route.request.url)
        route.abort()
    page.route("https://example.invalid/**", block_network)
    try:
        detail = _open_rich_detail(page, artifact)
        expect(detail.locator("dd strong")).to_have_text("above")
        expect(detail.locator("dd ul li")).to_have_text(["First", "Second"])
        expect(detail.locator("dd table thead th")).to_have_text(table["headers"])
        expect(detail.locator("dd table tbody td")).to_have_text([
            "1", "Check the risk analysis.", "Signed and released; pressure <25kg.", "Y",
        ])
        assert "Schema description" not in detail.inner_text()
        assert detail.locator(".rich-metadata").locator(
            "script, img, iframe, [onclick], [onerror], [style]").count() == 0
        assert detail.locator("a[href^='javascript:']").count() == 0
        assert page.evaluate("window.richInjected") is None
        assert requests == []
        assert page.evaluate("""() => obsArtifact.records.find(record =>
            record.sourcePath === 'subject.md').frontmatter.item.testStepTable""") == table
        assert errors == []
        page.screenshot(path=str(tmp_path / "rich-metadata.png"))
    finally:
        page.close()


def test_native_rich_metadata_fallback_empty_tables_and_literal_percentages(tmp_path, reader_browser):
    from playwright.sync_api import expect

    plain = "Literal <p>text</p> and 20%3C25."
    artifact = _rich_fixture(tmp_path, {
        "description": "Flattened description",
        "descriptionHtml": "Pressure <25kg, 5% and 20%3C25.",
        "acceptanceCriteria": plain,
        "testSteps": "Flattened schema text must not replace an empty structured table.",
        "testStepTable": {"headers": ["Action"], "rows": []},
    })
    page = reader_browser.new_page(viewport={"width": 1500, "height": 1000})
    try:
        detail = _open_rich_detail(page, artifact)
        expect(detail).to_contain_text("Pressure <25kg, 5% and 20%3C25.")
        expect(detail).to_contain_text(plain)
        assert "Flattened schema" not in detail.inner_text()
        assert detail.locator("dd table").count() == 0
        assert detail.locator(".rich-metadata").count() == 1
    finally:
        page.close()


@pytest.mark.parametrize("source_kind", ["catalog-requirements", "catalog-test-cases"])
def test_native_actual_imported_source_tables(tmp_path, reader_browser, source_kind):
    from playwright.sync_api import expect

    source = os.environ.get("REFERENCE_EXAMPLE_SNAPSHOT")
    if not source:
        pytest.skip("Set REFERENCE_EXAMPLE_SNAPSHOT for actual imported-source acceptance.")
    snapshot = json.loads(Path(source).read_text(encoding="utf-8-sig"))
    role = next(role for role in snapshot["roleData"] if role["kind"] == source_kind)
    items = role.get("sourceItems") or role["items"]
    if source_kind == "catalog-requirements":
        item = next(item for item in items if "<table" in item.get("descriptionHtml", ""))
    else:
        item = next(item for item in items if (item.get("testStepTable") or {}).get("rows")
                    and "risk analysis" in item.get("testSteps", "").lower())
    artifact = _rich_fixture(tmp_path, item)
    page = reader_browser.new_page(viewport={"width": 1500, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        detail = _open_rich_detail(page, artifact)
        expect(detail.locator("dd table").first).to_be_visible()
        if source_kind == "catalog-test-cases":
            steps = detail.locator("dt").filter(has_text="testSteps").locator(
                "xpath=following-sibling::dd[1]")
            table = item["testStepTable"]
            expect(steps.locator("thead th")).to_have_text(table["headers"])
            assert steps.locator("thead th").last.evaluate("""element => {
                const range = document.createRange();
                range.selectNodeContents(element);
                return range.getClientRects().length;
            }""") == 1
            assert steps.locator("tbody tr").count() == len(table["rows"])
            assert steps.locator("tbody td").count() == sum(map(len, table["rows"]))
            expect(steps).to_contain_text("Risk Analysis")
            assert "Schema description" not in steps.inner_text()
        actual = page.evaluate("""() => obsArtifact.records.find(record =>
            record.sourcePath === 'subject.md').frontmatter.item""")
        assert all(actual[key] == value for key, value in item.items())
        assert errors == []
        page.screenshot(path=str(tmp_path / f"actual-{source_kind}.png"))
    finally:
        page.close()
