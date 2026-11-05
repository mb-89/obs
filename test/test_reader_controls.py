import copy
import json
import os
import re
from pathlib import Path

import pytest
import yaml

from obs_html.content import ContentError, parse_manifest, validate_base_definition
from obs_html.renderer import render_artifact
from obs_html.artifact_data import decode_artifact_data


def definition():
    return {
        "properties": {
            "subject": {
                "displayName": "Subject",
                "obsHtml": {
                    "reference": {"label": ["item.id"], "metadata": ["item.name"]},
                    "detail": True,
                },
            },
            "actions": {
                "displayName": "Actions",
                "obsHtml": {
                    "icons": [
                        {
                            "name": "download", "label": "Download",
                            "linkProperty": "document", "unavailable": "No document",
                        },
                        {
                            "name": "help", "label": "Help",
                            "help": "Additional information.",
                        },
                    ],
                },
            },
        },
        "views": [{
            "type": "table",
            "order": ["subject", "actions"],
            "obsHtml": {
                "details": "columns",
                "pagination": False,
                "columnSizing": "equal",
                "detailFontSize": 10,
            },
        }],
    }


def test_reader_control_declarations_validate_and_round_trip():
    from test_browser import run_browser_script

    valid = definition()
    validate_base_definition(valid, Path("reader.md"))
    assert valid["views"][0]["obsHtml"] == {
        "details": "columns",
        "pagination": False,
        "columnSizing": "equal",
        "detailFontSize": 10,
    }
    run_browser_script("""
        context.obsBases.validate(payload);
        assert.deepEqual(JSON.parse(JSON.stringify(context.obsBases.parse(
            context.obsBases.dump(payload)))), payload);
    """, valid)


@pytest.mark.parametrize("mutate", [
    lambda spec: spec["views"][0]["obsHtml"].update(pagination="false"),
    lambda spec: spec["views"][0]["obsHtml"].update(columnSizing="natural"),
    lambda spec: spec["views"][0]["obsHtml"].update(detailFontSize=100),
    lambda spec: spec["properties"]["actions"]["obsHtml"].update(icons=[]),
    lambda spec: spec["properties"]["actions"]["obsHtml"]["icons"].append(
        {"name": "invalid/name", "label": "Invalid", "help": "Invalid action"},
    ),
    lambda spec: spec["properties"]["actions"]["obsHtml"].update(
        icon={"name": "help", "label": "Help", "help": "Duplicate action"},
    ),
])
def test_reader_control_declarations_reject_unsupported_values(mutate):
    from test_browser import run_browser_script

    invalid = copy.deepcopy(definition())
    mutate(invalid)
    with pytest.raises(ContentError, match=r"Invalid base definition|; see capabilities/bases\."):
        validate_base_definition(invalid, Path("reader.md"))
    run_browser_script("assert.throws(() => context.obsBases.validate(payload));", invalid)


def test_detail_font_configuration_is_bounded_and_reproduced(tmp_path):
    from importlib.resources import files
    from io import BytesIO
    from zipfile import ZipFile
    from jsonschema import ValidationError
    from obs_html.cli import PROJECT_ROOT
    from obs_html.config import load_config
    from obs_html.reproduction import source_archive

    manifest = _write_reader_fixture(tmp_path / "source")
    override = tmp_path / "config.json"
    override.write_text('{"artifact":{"tableDetailFontSizePoints":11}}', encoding="utf-8")
    config = load_config(files("obs_html").joinpath("cfg.json"), override)
    assert config.table_detail_font_size_points == 11
    with ZipFile(BytesIO(source_archive(manifest.parent, manifest, PROJECT_ROOT, config, False))) as archive:
        assert json.loads(archive.read("build-config.json"))["artifact"]["tableDetailFontSizePoints"] == 11
    for unsupported in (7, 15):
        override.write_text(json.dumps({"artifact": {"tableDetailFontSizePoints": unsupported}}), encoding="utf-8")
        with pytest.raises(ValidationError):
            load_config(files("obs_html").joinpath("cfg.json"), override)


@pytest.fixture(scope="module")
def reader_browser():
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native reader controls.")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        try:
            yield browser
        finally:
            browser.close()


def _write_reader_fixture(root):
    root.mkdir(exist_ok=True, parents=True)
    (root / "manifest.md").write_text(
        "---\ntitle: \"\"\nproduct:\n  name: Document Identity\n---\n"
        "- [[chapter]]\n\n"
        "||| 1:2\n```cards\n" + json.dumps({"version": 1, "cards": [{
            "title": "Coverage",
            "metricStyle": "pills",
            "body": "",
            "metrics": [{"label": "Coverage", "where": []}],
        }]}) + "\n```\n|||\n"
        "## Evidence\n\nCompact evidence table.\n\n"
        "| Check | Result |\n|---|---|\n| E-1 | Complete |\n|||\n",
        encoding="utf-8",
    )
    definition_text = yaml.safe_dump({
        "filters": 'kind == "relation"',
        "properties": {
            "subject": {
                "displayName": "Subject",
                "obsHtml": {
                    "reference": {"label": ["item.id"], "metadata": ["item.name", "item.homepage"]},
                    "detail": True,
                },
            },
            "status": {"displayName": "Status"},
            "actions": {
                "displayName": "Actions",
                "obsHtml": {"icons": [
                    {"name": "download", "label": "Download", "linkProperty": "document",
                     "unavailable": "No document"},
                    {"name": "help", "label": "Help", "help": "Supplementary action."},
                ]},
            },
        },
        "views": [{
            "type": "table",
            "order": ["subject", "status", "actions"],
            "obsHtml": {
                "details": "columns", "pagination": False, "columnSizing": "equal",
                "detailFontSize": 10,
            },
        }],
    }, sort_keys=False)
    home_definition = yaml.safe_load(definition_text)
    home_definition["filters"] = {"and": ['kind == "relation"', "document != null"]}
    home = root / "manifest.md"
    home.write_text(home.read_text(encoding="utf-8").replace(
        "| Check | Result |\n|---|---|\n| E-1 | Complete |",
        "```base\n" + yaml.safe_dump(home_definition, sort_keys=False) + "```",
    ), encoding="utf-8")
    (root / "chapter.md").write_text(
        "# Reader controls\n\n```base\n" + definition_text + "```\n",
        encoding="utf-8",
    )
    (root / "subject.md").write_text(
        "---\nkind: subject\nitem:\n  id: S-1\n  name: Canonical subject\n"
        "  homepage: '[Official site](https://example.org/subject)'\n"
        "privateField: MUST-NOT-APPEAR\n---\n"
        "# Subject body\n\nCanonical body detail.\n",
        encoding="utf-8",
    )
    (root / "empty.md").write_text(
        "---\nkind: subject\nitem:\n  id: S-EMPTY\n---\n", encoding="utf-8",
    )
    for index in range(65):
        (root / f"relation-{index:03d}.md").write_text(
            "---\nkind: relation\n"
            f"subject: '[[{'empty' if index == 1 else 'subject'}]]'\n"
            f"status: Complete {index}\n"
            + ("document: '[Download](https://example.org/evidence.pdf)'\n" if index == 0 else "")
            + "internalIndex: PRIVATE-INTERNAL\n---\n",
            encoding="utf-8",
        )
    return root / "manifest.md"


def _declare_query(manifest, query):
    """Declare the manifest's global query profile (input-model) in its existing frontmatter."""
    manifest.write_text(manifest.read_text(encoding="utf-8").replace(
        "---\n", "---\nobsHtml: " + json.dumps({"query": query}) + "\n", 1), encoding="utf-8")
    return manifest


def test_native_reader_controls_and_compact_metrics(tmp_path, reader_browser):
    from playwright.sync_api import expect

    manifest = _declare_query(_write_reader_fixture(tmp_path), {
        "scope": "records", "where": [{"field": "kind", "equals": "relation"}],
        "fields": [{"field": "kind"}, {"field": "status", "label": "State"}],
    })
    artifact = tmp_path / "reader.html"
    artifact.write_text(render_artifact(
        manifest, parse_manifest(manifest), table_page_size=5,
    ), encoding="utf-8")
    page = reader_browser.new_page(viewport={"width": 1500, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(artifact.as_uri() + "#chapter")
        page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('chapter')")
        table = page.locator('[data-active-chapter] [data-data-table="chapter-base-1"]')
        expect(table.locator("tbody tr[data-row-key]")).to_have_count(65)
        expect(table.locator(".data-table-footer")).to_be_hidden()
        expect(table.locator("thead th")).to_have_count(3)
        row = table.locator('[data-row-key="note:relation-000"]')
        expect(row.get_by_role("link", name="Download", exact=True)).to_have_attribute(
            "href", "https://example.org/evidence.pdf",
        )
        expect(row.get_by_role("button", name="Help", exact=True)).to_have_count(1)
        row.get_by_role("link", name="S-1", exact=True).click()
        details = table.locator('[data-detail-owner="note:relation-000"]')
        expect(details.get_by_role("tab", name="Subject", exact=True)).to_have_count(1)
        expect(details.get_by_role("tabpanel").locator("dt")).to_have_text(["name", "homepage"])
        expect(details.locator("a[href='https://example.org/subject']")).to_have_text("Official site")
        expect(details).to_contain_text("Canonical body detail.")
        expect(details).not_to_contain_text("MUST-NOT-APPEAR")
        empty = table.locator('[data-row-key="note:relation-001"]')
        expect(empty.locator(".data-table-tree-toggle")).to_have_count(0)
        expect(table.locator('[data-detail-owner="note:relation-001"] [role="tab"]')).to_have_count(0)
        table.get_by_role("button", name="Table options").click()
        table.get_by_role("button", name="Properties", exact=True).click()
        property_names = table.locator('[aria-label="Find a property"]').locator(
            "xpath=following-sibling::div",
        ).locator(".filter-pill").all_text_contents()
        assert property_names[:3] == ["Subject", "Status", "Actions"]
        assert "internalIndex" not in property_names and "sourcePath" not in property_names
        page.evaluate("obsArtifact.activateChapter('home')")
        cards = page.locator(".chapter-body .markdown-columns")
        positions = cards.locator(":scope > .markdown-column").evaluate_all(
            "nodes => nodes.map(node => node.getBoundingClientRect().toJSON())",
        )
        assert positions[0]["width"] < positions[1]["width"]
        metrics = page.locator(".record-metric")
        assert metrics.count() == 1
        assert metrics.evaluate("node => node.scrollWidth <= node.clientWidth + 1")
        assert page.evaluate("obsArtifact.navigationChapters().every(record => record.slug !== 'home')")
        assert page.locator(".chapter-home-link").get_attribute("title").endswith("Document Identity")
        overview = []
        for paged in (False, True):
            page.evaluate("value => obsPages.setPaged(value)", paged)
            evidence = page.locator('[data-active-chapter] [data-data-table="home-base-1"]')
            expect(evidence.locator("tbody tr[data-row-key]")).to_have_count(1)
            expect(evidence.locator(".data-table-icon-action")).to_have_count(2)
            fit = evidence.locator(".data-table-scroll").evaluate(
                "node => ({available:node.clientWidth, content:node.scrollWidth})",
            )
            assert fit["content"] <= fit["available"] + 1
            overview.append({"paged": paged, **fit})
        (tmp_path / "compact-overview-fit.json").write_text(json.dumps(overview, indent=2), encoding="utf-8")
        page.locator(".paged-reader .markdown-columns").screenshot(path=str(tmp_path / "compact-overview.png"))
        assert errors == []
    finally:
        page.close()


def test_cli_reader_fixture_generation_does_not_write_live_paths(tmp_path):
    from obs_html.cli import main

    manifest = _write_reader_fixture(tmp_path / "source")
    output = tmp_path / "artifact.html"
    assert main(["--source", str(manifest), "--output", str(output)]) == 0
    html = output.read_text(encoding="utf-8")
    data = decode_artifact_data(html)
    assert data["tableDetailFontSizePoints"] == 10
    chapter = next(note for note in data["notes"] if note["slug"] == "chapter")
    assert chapter["tables"][0]["definition"]["views"][0]["obsHtml"]["pagination"] is False


def _control_artifact(root, *, subject_text=""):
    output = root / "control.html"
    root = root / "source"
    manifest = _write_reader_fixture(root)
    manifest.write_text(manifest.read_text(encoding="utf-8").replace(
        "- [[chapter]]", "- [[intro]]\n- [[chapter]]\n- [[after]]",
    ), encoding="utf-8")
    (root / "intro.md").write_text("# Introduction\n\nAlways authored.\n", encoding="utf-8")
    (root / "after.md").write_text("# Afterwards\n\nStill authored.\n", encoding="utf-8")
    if subject_text:
        subject = root / "subject.md"
        subject.write_text(subject.read_text(encoding="utf-8") + subject_text, encoding="utf-8")
    chapter = root / "chapter.md"
    text = chapter.read_text(encoding="utf-8")
    text = text.replace("details: columns", "details: columns\n    wide: true")
    chapter.write_text(
        text + "\n" + text[text.index("```base"):] +
        "\n```base\nfilters: 'kind == \"subject\"'\nviews:\n"
        "  - type: table\n    order: [title]\n```\n", encoding="utf-8",
    )
    for index in range(65):
        source = root / f"relation-{index:03d}.md"
        source.write_text(source.read_text(encoding="utf-8").replace(
            f"status: Complete {index}", f"status: {'Complete' if index % 2 else 'Review'}\nidentifier: ID-{index}",
        ), encoding="utf-8")
    _declare_query(manifest, {
        "scope": "records", "where": [{"field": "kind", "equals": "relation"}],
        "fields": [
            {"field": "kind"}, {"field": "status", "label": "State"},
            {"field": "identifier", "label": "Identifier"},
        ],
    })
    from obs_html.cli import main
    artifact = output
    assert main(["--source", str(manifest), "--output", str(artifact)]) == 0
    return artifact


def test_native_discovered_bar_close_and_record_facet_scope(tmp_path, reader_browser):
    from playwright.sync_api import expect

    artifact = _control_artifact(tmp_path)
    page = reader_browser.new_page(viewport={"width": 1500, "height": 1000})
    try:
        page.goto(artifact.as_uri())
        page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('chapter')")
        bar_names = page.locator("[data-bar]").evaluate_all("nodes => nodes.map(n => n.dataset.bar)")
        for name in bar_names:
            page.evaluate("name => obsArtifact.openBar(name, 'left')", name)
            bar = page.locator(f'[data-bar="{name}"]')
            close = bar.get_by_role("button", name=f"Close {bar.get_attribute('aria-label')}", exact=True)
            expect(close).to_be_visible()
            header = bar.locator(".dock-bar-header")
            bounds = header.bounding_box()
            button = close.bounding_box()
            assert abs(bounds["x"] + bounds["width"] - button["x"] - button["width"]) <= 2
            close.focus()
            close.press("Enter")
            expect(bar).to_be_hidden()
            assert page.evaluate("document.activeElement.matches('[data-menu-button], [data-dock-bar]')")
        page.evaluate("obsArtifact.openBar('filter', 'left')")
        facets = page.locator("[data-filter-fields] .filter-field")
        expect(facets).to_have_count(1)
        expect(facets).to_have_attribute("data-field", "status")
        page.evaluate("obsFilter.selectExpression('identifier: /^ID-1$/')")
        assert page.evaluate("obsArtifact.navigationChapters().map(r => r.slug)") == [
            "intro", "chapter", "after",
        ]
        assert page.evaluate("obsArtifact.exportChapters().map(r => r.slug)") == [
            "intro", "chapter", "after",
        ]
        expect(page.locator("[data-filter-warning]")).to_contain_text("1/65 records")
        page.locator('[data-bar="filter"]').get_by_role("button", name="Close Filter", exact=True).click()
        expect(page.locator("[data-filter-input]")).to_have_value("")
        expect(page.locator("[data-filter-warning]")).to_be_hidden()
        table = page.locator('[data-active-chapter] [data-data-table="chapter-base-1"]')
        table.get_by_role("button", name="Table options", exact=True).click()
        table.get_by_role("button", name="Filter", exact=True).click()
        expect(table.locator('[aria-label="Filter fields"] .filter-field-button')).to_have_attribute(
            "aria-label", "State; 2 unique values")
        table.locator('[aria-label="Filter table"]').fill("identifier: /^ID-1$/")
        expect(table.locator("tbody tr[data-row-key]")).to_have_count(1)
        table.get_by_role("button", name="Properties", exact=True).click()
        properties = table.locator('[aria-label="Properties"] .filter-pill').all_text_contents()
        assert "Identifier" in properties and "internalIndex" not in properties
        ordinary = page.locator('[data-active-chapter] [data-data-table="chapter-base-3"]')
        ordinary.get_by_role("button", name="Table options", exact=True).click()
        ordinary.get_by_role("button", name="Properties", exact=True).click()
        assert "privateField" in ordinary.locator('[aria-label="Properties"] .filter-pill').all_text_contents()
        page.evaluate("obsArtifact.openBar('toc')")
        expect(page.locator('[data-toc-link="home"]')).to_have_count(0)
        (tmp_path / "discovered-bars.json").write_text(json.dumps(bar_names), encoding="utf-8")
    finally:
        page.close()


def test_native_local_filter_warning_clear_is_scoped_and_survives_continuations(tmp_path, reader_browser):
    from playwright.sync_api import expect

    artifact = _control_artifact(tmp_path)
    page = reader_browser.new_page(viewport={"width": 1500, "height": 1000})
    try:
        page.goto(artifact.as_uri() + "#chapter")
        page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('chapter')")
        first = page.locator('[data-active-chapter] [data-data-table="chapter-base-1"]')
        second = page.locator('[data-active-chapter] [data-data-table="chapter-base-2"]')
        page.evaluate("""() => {
            const first = document.querySelector('[data-data-table="chapter-base-1"]');
            first.dispatchEvent(new CustomEvent('obs-table-set-filter', {detail:{expression:'kind: relation'}}));
            const second = document.querySelector('[data-data-table="chapter-base-2"]');
            second.dispatchEvent(new CustomEvent('obs-table-set-filter', {detail:{expression:'status: Complete'}}));
        }""")
        expect(first.locator("[data-table-filter-warning]")).to_be_visible()
        expect(first).to_have_attribute("data-filter-active", "true")
        expect(second.locator("tbody tr[data-row-key]")).to_have_count(32)
        first.evaluate("""node => node.dispatchEvent(new CustomEvent(
            'obs-table-set-filter', {detail:{expression:'status: Missing'}}))""")
        expect(first.locator("[data-table-filter-warning]")).to_be_visible()
        expect(first.locator("tbody tr[data-row-key]")).to_have_count(0)
        first.evaluate("""node => node.dispatchEvent(new CustomEvent(
            'obs-table-set-filter', {detail:{expression:'('}}))""")
        expect(first.locator("[data-table-filter-warning]")).to_be_visible()
        first.get_by_role("button", name="Clear table filter", exact=True).click()
        expect(first.locator("[data-table-filter-warning]")).to_be_hidden()
        expect(first.locator("tbody tr[data-row-key]")).to_have_count(65)
        expect(second.locator("tbody tr[data-row-key]")).to_have_count(32)
        expect(first.locator('[aria-label="Filter table"]')).to_have_value("")
        page.evaluate("obsFilter.selectExpression('kind: relation'); obsPages.setPaged(true)")
        projections = page.locator('.paged-reader [data-data-table="chapter-base-2"]')
        assert projections.count() > 1
        assert projections.evaluate_all("""nodes => nodes.every(node =>
            node.dataset.filterActive === 'true' &&
            node.querySelector('[data-table-filter-warning]') &&
            !node.querySelector('[data-table-filter-warning]').hidden)""")
        badge = projections.last.locator("[data-table-filter-warning]")
        badge.scroll_into_view_if_needed()
        assert badge.evaluate("""node => {
            const badge=node.getBoundingClientRect(), table=node.parentElement.querySelector('table').getBoundingClientRect();
            return badge.bottom <= table.top + 1;
        }""")
        badge.screenshot(path=str(tmp_path / "local-filter-badge.png"))
        projections.last.get_by_role("button", name="Clear table filter", exact=True).click()
        expect(page.locator(".paged-reader [data-table-filter-warning]:not([hidden])")).to_have_count(0)
        expect(page.locator("[data-filter-warning]")).to_be_visible()
        expect(page.locator("[data-filter-input]")).to_have_value("kind: relation")
    finally:
        page.close()


def test_native_actual_subject_shares_stable_tabs_and_computed_detail_font(tmp_path, reader_browser):
    from playwright.sync_api import expect

    manifest = _write_reader_fixture(tmp_path)
    chapter = tmp_path / "chapter.md"
    spec = yaml.safe_load(chapter.read_text(encoding="utf-8").split("```base\n")[1].split("```")[0])
    for field in ("peer", "absent"):
        spec["properties"][field] = {
            "displayName": field.title(),
            "obsHtml": {"detail": True, "reference": {"label": ["item.id"], "metadata": ["item.name"]}},
        }
    spec["views"][0]["order"] = ["subject", "peer", "absent", "actions"]
    chapter.write_text("# Controls\n\n```base\n" + yaml.safe_dump(spec) + "```\n", encoding="utf-8")
    (tmp_path / "peer.md").write_text(
        "---\nitem: {id: P-1, name: Peer detail}\n---\n" +
        "\n".join(f"- Nested **detail {i}** with [safe URL](https://example.org/nested)" for i in range(8)) +
        "\n\n```base\nfilters: 'kind == \"nested\"'\nviews:\n"
        "  - type: table\n    order: [title]\n```\n",
        encoding="utf-8",
    )
    (tmp_path / "nested.md").write_text(
        "---\nkind: nested\nwebsite: https://example.org/plain\n---\n"
        "# Nested subject\n\nNested description with [nested URL](https://example.org/deep).\n",
        encoding="utf-8",
    )
    relation = tmp_path / "relation-000.md"
    relation.write_text(relation.read_text(encoding="utf-8").replace(
        "kind: relation", "kind: relation\npeer: '[[peer]]'\nabsent: '[[empty]]'",
    ), encoding="utf-8")
    artifact = tmp_path / "font.html"
    artifact.write_text(render_artifact(manifest, parse_manifest(manifest)), encoding="utf-8")
    page = reader_browser.new_page(viewport={"width": 1500, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(artifact.as_uri() + "#chapter")
        page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('chapter')")
        table = page.locator('[data-active-chapter] [data-data-table="chapter-base-1"]')
        widths = table.locator(":scope > .data-table-scroll > table > thead th").evaluate_all(
            "nodes => nodes.slice(0, -1).map(n => n.getBoundingClientRect().width)",
        )
        assert max(widths) - min(widths) < 2
        table.locator('[data-row-key="note:relation-000"] .data-table-tree-toggle').click()
        detail = table.locator('[data-detail-owner="note:relation-000"]')
        expect(detail.get_by_role("tab")).to_have_text(["Subject", "Peer"])
        heights = []
        sizes = {}
        for name in ("Subject", "Peer"):
            detail.get_by_role("tab", name=name, exact=True).click()
            panel = detail.get_by_role("tabpanel")
            heights.append(panel.bounding_box()["height"])
            sizes[name] = panel.locator("p, li, dd, dd a, li a, strong").evaluate_all(
                "nodes => nodes.map(n => ({text:n.textContent, size:parseFloat(getComputedStyle(n).fontSize)}))",
            )
            assert sizes[name] and all(abs(item["size"] - 40 / 3) < 0.02 for item in sizes[name])
        assert abs(heights[0] - heights[1]) < 2
        expect(detail.get_by_role("tabpanel").get_by_role("link", name="safe URL")).to_have_count(8)
        nested = detail.get_by_role("tabpanel").locator('[data-data-table="peer-base-1"]')
        nested.locator(".data-table-tree-toggle").click()
        nested_detail = nested.locator(".data-table-detail-content")
        expect(nested_detail.get_by_role("link", name="https://example.org/plain", exact=True)).to_have_attribute(
            "href", "https://example.org/plain",
        )
        expect(nested_detail.get_by_role("link", name="nested URL", exact=True)).to_be_visible()
        nested_sizes = nested_detail.locator("p, dd, dd a, p a").evaluate_all(
            "nodes => nodes.map(n => parseFloat(getComputedStyle(n).fontSize))",
        )
        assert nested_sizes and all(abs(size - 40 / 3) < 0.02 for size in nested_sizes)
        sizes["nested"] = nested_sizes
        sizes["reference12pt"] = nested_detail.evaluate("""node => {
            const previous = node.style.getPropertyValue('--table-detail-font-size');
            node.style.setProperty('--table-detail-font-size', '12pt');
            const reference = parseFloat(getComputedStyle(node.querySelector('p')).fontSize);
            node.style.setProperty('--table-detail-font-size', previous);
            return reference;
        }""")
        assert sizes["reference12pt"] == pytest.approx(16)
        assert sizes["reference12pt"] - nested_sizes[0] == pytest.approx(8 / 3, abs=0.02)
        detail.screenshot(path=str(tmp_path / "nested-font-details.png"))
        table.evaluate("""node => node.dispatchEvent(new CustomEvent(
            'obs-table-set-columns', {detail:{columns:['subject','peer','actions']}}))""")
        widths = table.locator(":scope > .data-table-scroll > table > thead th").evaluate_all(
            "nodes => nodes.slice(0, -1).map(n => n.getBoundingClientRect().width)",
        )
        assert len(widths) == 2 and max(widths) - min(widths) < 2
        assert sum(widths) > table.locator(":scope > .data-table-scroll > table").bounding_box()["width"] * 0.8
        sizes["layout"] = {"panelHeights": heights, "subjectWidths": widths}
        detail.screenshot(path=str(tmp_path / "subject-details.png"))
        (tmp_path / "computed-font.json").write_text(json.dumps(sizes, indent=2), encoding="utf-8")
        assert errors == []
    finally:
        page.close()


def test_native_screen_relayout_cannot_clear_pending_print_sheets(tmp_path, reader_browser):
    from playwright.sync_api import expect

    artifact = _control_artifact(tmp_path)
    page = reader_browser.new_page(viewport={"width": 1500, "height": 1000})
    try:
        page.goto(artifact.as_uri() + "#chapter")
        page.evaluate("""() => {
            let preparations = 0;
            window.obsFigures = {
                pageNode: node => node,
                projectSankeys() {},
                async preparePrint() {
                    if (++preparations === 2) await new Promise(resolve => {
                        window.releasePrintLayout = resolve;
                        window.printLayoutHeld = true;
                    });
                },
            };
            window.print = () => {};
            window.pendingPrint = obsPages.exportPDF();
        }""")
        page.wait_for_function("window.printLayoutHeld === true")
        sheets = page.locator(".print-book .paper-sheet")
        count = sheets.count()
        assert count > 1
        page.evaluate("document.dispatchEvent(new CustomEvent('obs-table-definition-change'))")
        expect(sheets).to_have_count(count)
        page.evaluate("async () => {releasePrintLayout(); await pendingPrint;}")
        expect(sheets).to_have_count(count)
        page.evaluate("window.dispatchEvent(new Event('afterprint'))")
        expect(sheets).to_have_count(0)
        assert page.locator(".paged-reader .paper-sheet").count() > 0
    finally:
        page.close()


def test_native_continuation_numbering_and_resize_from_last_sheet(tmp_path, reader_browser):
    from playwright.sync_api import expect

    artifact = _control_artifact(tmp_path)
    page = reader_browser.new_page(viewport={"width": 1500, "height": 1000})
    try:
        page.goto(artifact.as_uri() + "#chapter")
        page.evaluate("obsArtifact.activateChapter('chapter'); obsPages.setPaged(true)")
        page.wait_for_function("document.documentElement.dataset.artifactStatus === 'ready'")
        page.evaluate("obsArtifact.whenChapterReady()")
        initial_labels = page.locator(".paged-reader .paper-page-number").all_text_contents()
        initial_numbers = [int(label.split()[1]) for label in initial_labels]
        total = int(initial_labels[0].split()[-1])
        assert initial_numbers == list(range(initial_numbers[0], initial_numbers[-1] + 1))
        assert 1 <= initial_numbers[0] <= initial_numbers[-1] <= total
        assert all(label.endswith(f" of {total}") for label in initial_labels)
        page.evaluate("obsArtifact.activateChapter('after')")
        next_before = page.locator(".paged-reader .paper-page-number").first.inner_text()
        assert int(next_before.split()[1]) == initial_numbers[-1] + 1
        assert next_before.endswith(f" of {total}")
        page.evaluate("obsArtifact.activateChapter('chapter')")
        page.evaluate("obsArtifact.whenChapterReady()")
        assert page.locator(".paged-reader .paper-page-number").all_text_contents() == initial_labels
        projections = page.locator('.paged-reader [data-data-table="chapter-base-1"]')
        assert projections.count() > 1
        initial_fragments = projections.count()
        handles = projections.last.get_by_role("separator", name="Resize Subject", exact=True)
        handles.scroll_into_view_if_needed()
        before = projections.last.locator("thead th").first.bounding_box()["width"]
        handles.focus()
        handles.press("ArrowRight")
        after = projections.locator("thead th:first-child").evaluate_all(
            "nodes => nodes.map(n => n.getBoundingClientRect().width)",
        )
        assert min(after) >= before + 14 and max(after) - min(after) < 2
        assert page.locator(".paged-reader .paper-page-number").all_text_contents() == initial_labels
        assert projections.count() == initial_fragments
        handle_bounds = projections.last.get_by_role(
            "separator", name="Resize Subject", exact=True,
        ).bounding_box()
        x = handle_bounds["x"] + handle_bounds["width"] / 2
        y = handle_bounds["y"] + handle_bounds["height"] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 20, y, steps=4)
        page.mouse.up()
        pointer_widths = projections.locator("thead th:first-child").evaluate_all(
            "nodes => nodes.map(n => n.getBoundingClientRect().width)",
        )
        assert min(pointer_widths) >= min(after) + 18 and max(pointer_widths) - min(pointer_widths) < 2
        assert page.locator(".paged-reader .paper-page-number").all_text_contents() == initial_labels
        assert projections.count() == initial_fragments
        for key in ("chapter-base-1", "chapter-base-2"):
            keys = page.locator(f'.paged-reader [data-data-table="{key}"] tbody tr[data-row-key]').evaluate_all(
                "rows => rows.map(row => row.dataset.rowKey)",
            )
            assert len(keys) == len(set(keys)) == 65
        last_number = int(page.locator(".paged-reader .paper-page-number").last.inner_text().split()[1])
        page.evaluate("obsArtifact.activateChapter('after')")
        expect(page.locator(".paged-reader .paper-page-number").first).to_have_text(next_before)
        number = int(page.locator(".paged-reader .paper-page-number").first.inner_text().split()[1])
        assert number == last_number + 1
        page.evaluate("obsArtifact.activateChapter('home')")
        contents = page.locator('.paged-reader [data-contents-chapter="after"]')
        expect(contents).to_have_text(str(number))
        expect(page.locator('.paged-reader [data-contents-chapter="home"]')).to_have_count(0)
        page.evaluate("obsFilter.selectExpression('identifier: /^ID-1$/')")
        page.evaluate("obsArtifact.activateChapter('chapter')")
        page.evaluate("obsArtifact.whenChapterReady()")
        page.wait_for_function("""() => [...document.querySelectorAll(
            '.paged-reader .paper-page-number')].every(node => /^Page \\d+ of \\d+$/.test(node.textContent))""")
        filtered_labels = page.locator(".paged-reader .paper-page-number").all_text_contents()
        assert int(filtered_labels[-1].split()[-1]) < total
        for key in ("chapter-base-1", "chapter-base-2"):
            expect(page.locator(
                f'.paged-reader [data-data-table="{key}"] tr[data-row-key]',
            )).to_have_count(1)
        page.evaluate("obsArtifact.activateChapter('after')")
        assert int(page.locator(".paged-reader .paper-page-number").first.inner_text().split()[1]) == (
            int(filtered_labels[-1].split()[1]) + 1
        )
        page.evaluate("obsArtifact.activateChapter('chapter')")
        page.evaluate("obsArtifact.whenChapterReady()")
        assert page.locator(".paged-reader .paper-page-number").all_text_contents() == filtered_labels
        (tmp_path / "continuation-layout.json").write_text(json.dumps({
            "widthBefore": before, "keyboardWidths": after, "pointerWidths": pointer_widths,
            "lastTableChapterPage": last_number, "nextChapterPage": number,
            "initialLabels": initial_labels, "initialFragments": initial_fragments,
            "filteredLabels": filtered_labels,
        }, indent=2), encoding="utf-8")
    finally:
        page.close()


def test_native_frozen_table_allocation_survives_detail_growth_and_pdf(tmp_path, reader_browser):
    from playwright.sync_api import expect
    from pypdf import PdfReader

    text = "\n\n".join(f"Stable detail {index}: " + "Canonical detail remains accessible. " * 8
                       for index in range(24))
    artifact = _control_artifact(tmp_path, subject_text="\n\n" + text)
    page = reader_browser.new_page(viewport={"width": 1500, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(artifact.as_uri() + "#chapter")
        page.wait_for_function("document.documentElement.dataset.artifactStatus === 'ready'")
        page.evaluate("obsArtifact.whenChapterReady()")
        initial = page.locator(".paged-reader .paper-page-number").all_text_contents()
        fragments = {
            key: page.locator(f'.paged-reader [data-data-table="{key}"]').count()
            for key in ("chapter-base-1", "chapter-base-2")
        }
        assert min(fragments.values()) > 1
        row = page.locator(
            '.paged-reader [data-data-table="chapter-base-1"] [data-row-key="note:relation-064"]',
        )
        row.locator(".data-table-tree-toggle").click()
        detail = page.locator(
            '.paged-reader [data-data-table="chapter-base-1"] [data-detail-owner="note:relation-064"]',
        )
        expect(detail).to_contain_text("Stable detail 23:")
        assert page.locator(".paged-reader .paper-page-number").all_text_contents() == initial
        assert {
            key: page.locator(f'.paged-reader [data-data-table="{key}"]').count() for key in fragments
        } == fragments
        for key in fragments:
            keys = page.locator(f'.paged-reader [data-data-table="{key}"] tr[data-row-key]').evaluate_all(
                "rows => rows.map(row => row.dataset.rowKey)",
            )
            assert len(keys) == len(set(keys)) == 65
        assert detail.evaluate("""node => {
            const sheet = node.closest('.paper-sheet'), content = sheet.querySelector('.paper-content');
            return sheet.classList.contains('paper-sheet-flexible') &&
                content.scrollHeight <= content.clientHeight + 1;
        }""")
        page.evaluate("obsArtifact.activateChapter('after')")
        assert int(page.locator(".paged-reader .paper-page-number").first.inner_text().split()[1]) == (
            int(initial[-1].split()[1]) + 1
        )
        page.evaluate("obsArtifact.activateChapter('chapter')")
        page.evaluate("obsArtifact.whenChapterReady()")
        assert page.locator(".paged-reader .paper-page-number").all_text_contents() == initial
        expect(detail).to_contain_text("Stable detail 23:")
        page.evaluate("async () => {window.print = () => {}; await obsPages.exportPDF();}")
        printed = page.locator(".print-book .paper-sheet")
        print_sheets = printed.count()
        assert print_sheets > 1
        assert page.locator(".print-book .paper-sheet-flexible").count() == 0
        for key in fragments:
            tables = page.locator(f'.print-book table[data-review-table="{key}"]')
            assert tables.count() > 1
            assert tables.locator("thead").count() == tables.count()
            keys = tables.locator("tr[data-row-key]").evaluate_all(
                "rows => rows.map(row => row.dataset.rowKey)",
            )
            assert len(keys) == len(set(keys)) == 65
        pdf = tmp_path / "stable-allocation.pdf"
        page.pdf(path=str(pdf), prefer_css_page_size=True)
        document = PdfReader(pdf)
        assert len(document.pages) == print_sheets
        assert {page.mediabox.width > page.mediabox.height for page in document.pages} == {True, False}
        assert "Stable detail 23:" in "\n".join(page.extract_text() for page in document.pages)
        page.evaluate("window.dispatchEvent(new Event('afterprint'))")
        assert page.locator(".paged-reader .paper-page-number").all_text_contents() == initial
        row.locator(".data-table-tree-toggle").click()
        expect(detail).to_have_count(0)
        assert page.locator(".paged-reader .paper-page-number").all_text_contents() == initial
        assert not errors
        (tmp_path / "frozen-allocation.json").write_text(json.dumps({
            "initialLabels": initial, "fragments": fragments, "physicalPdfPages": print_sheets,
            "longDetailAndReentryPreserved": True, "browserErrors": errors,
        }, indent=2), encoding="utf-8")
    finally:
        page.close()


def test_native_expanded_figure_filter_updates_in_top_layer_without_disappearing(tmp_path, reader_browser):
    from playwright.sync_api import expect

    artifact = _control_artifact(tmp_path)
    chapter = tmp_path / "source" / "chapter.md"
    chapter.write_text(chapter.read_text(encoding="utf-8") +
        "\n```figure\nversion: 1\nkind: sankey\nsource: graph.json\nalt: Small graph\n```\n",
        encoding="utf-8",
    )
    (tmp_path / "source" / "graph.json").write_text(json.dumps({
        "version": 1,
        "data": {"where": [{"field": "kind", "equals": "relation"}]},
        "nodes": [{"id": "a", "label": "A", "stage": 0}, {"id": "b", "label": "B", "stage": 1}],
        "links": [{"source": "a", "target": "b", "value": 1,
                   "where": [{"field": "status", "equals": "Complete"}]}],
    }), encoding="utf-8")
    from obs_html.cli import main
    assert main(["--source", str(tmp_path / "source" / "manifest.md"), "--output", str(artifact)]) == 0
    page = reader_browser.new_page(viewport={"width": 1500, "height": 1000})
    try:
        page.goto(artifact.as_uri() + "#chapter")
        page.get_by_role("button", name="Expand figure", exact=True).click()
        dialog = page.get_by_role("dialog", name="Enlarged figure")
        expect(dialog.locator("figure")).to_be_visible()
        page.evaluate("obsFilter.selectExpression('status: Missing')")
        expect(dialog.locator("figure")).to_be_visible()
        expect(dialog.locator(".sankey-canvas")).to_contain_text("No matching records")
        warning = dialog.locator("[data-filter-warning]")
        expect(warning).to_be_visible()
        expect(warning).to_contain_text("0/65 records")
        assert warning.evaluate("""node => {
            const r=node.getBoundingClientRect();
            return node.contains(document.elementFromPoint(r.left+r.width/2,r.top+r.height/2));
        }""")
        dialog.screenshot(path=str(tmp_path / "expanded-filtered-figure.png"))
        warning.get_by_role("button", name="Clear filter", exact=True).click()
        expect(dialog.locator("figure")).to_be_visible()
        expect(warning).to_be_hidden()
        expect(dialog.locator(".sankey-canvas .sankey-link")).not_to_have_count(0)
        dialog.get_by_role("button", name="Close enlarged figure").click()
        expect(page.locator("dialog[open]")).to_have_count(0)
        expect(page.locator("[data-filter-warning]")).to_be_hidden()
    finally:
        page.close()


def test_native_joined_empty_tabs_metadata_properties_and_counted_scoped_filters(tmp_path, reader_browser):
    from playwright.sync_api import expect

    manifest = _write_reader_fixture(tmp_path)
    chapter = tmp_path / "chapter.md"
    text = chapter.read_text(encoding="utf-8")
    definition_text = text.split("```base\n")[1].split("```")[0]
    spec = yaml.safe_load(definition_text)
    spec["views"][0]["obsHtml"].update(showEmptyDetailTabs=True, screenPageBreaks=False)
    spec["properties"]["absent"] = {"displayName": "Absent",
        "obsHtml": {"detail": True, "reference": {"label": ["title"], "metadata": ["item"]}}}
    spec["properties"]["subject"]["obsHtml"]["reference"]["metadata"] = ["item"]
    spec["properties"]["actions"]["displayName"] = ""
    spec["views"][0]["order"] = ["subject", "absent", "status", "actions"]
    chapter.write_text(text.replace(definition_text, yaml.safe_dump(spec)), encoding="utf-8")
    subject = tmp_path / "subject.md"
    subject.write_text(subject.read_text(encoding="utf-8").replace(
        "item:", "item:\n  blank: ''\n  nullValue: null\n  emptyList: []\n  zero: 0\n  disabled: false",
    ), encoding="utf-8")
    for index, relation in enumerate(sorted(tmp_path.glob("relation-*.md"))):
        relation.write_text(relation.read_text(encoding="utf-8").replace(
            f"status: Complete {index}", f"status: {'Complete' if index < 8 else 'Pending'}",
        ), encoding="utf-8")
    artifact = tmp_path / "table-controls.html"
    artifact.write_text(render_artifact(manifest, parse_manifest(manifest)), encoding="utf-8")
    page = reader_browser.new_page(viewport={"width": 1500, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(artifact.as_uri())
        page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('chapter')")
        table = page.locator("[data-active-chapter] [data-data-table='chapter-base-1']")
        expect(table).to_have_attribute("data-screen-page-breaks", "false")
        expect(table.locator("thead th").last).to_have_attribute("aria-label", "actions")
        assert table.locator("thead th").last.locator(":scope > span").first.inner_text() == ""
        table.locator(".data-table-tree-toggle").first.click()
        detail = table.locator("[data-detail-owner]").first
        expect(detail.get_by_role("tab")).to_have_text(["Subject", "Absent"])
        expect(detail.get_by_role("tab", name="Absent")).to_be_disabled()
        terms = detail.locator(".note-detail-metadata dt").all_text_contents()
        assert "blank" not in terms and "nullValue" not in terms and "emptyList" not in terms
        assert "zero" in terms and "disabled" in terms
        active = detail.get_by_role("tab", name="Subject")
        active.press("End")
        expect(active).to_be_focused()
        table.locator(".data-table-options-toggle").click()
        table.locator(".data-table-options").get_by_role("button", name="Properties", exact=True).click()
        pills = table.locator("[aria-label='Properties'] .filter-pills button")
        assert pills.all_text_contents()[:4] == ["Subject", "Absent", "Status", "actions"]
        before = table.locator("thead th").count()
        pills.first.click()
        assert table.locator("thead th").count() == before - 1
        table.locator(".data-table-options").get_by_role("button", name="Filter", exact=True).click()
        table.locator("[aria-label='Filter fields'] .filter-field-button").filter(has_text="Status").click()
        picker = table.locator(".filter-values:popover-open")
        value = picker.locator("[data-filter-value='Complete']")
        expect(value.locator("small")).to_have_text("8")
        value.click()
        expect(table).to_have_attribute("data-filter-active", "true")
        assert page.evaluate("obsArtifact.filterSummary().empty") is True
        assert table.locator("[aria-label='Filter table']").input_value().startswith("status:")
        page.evaluate("obsArtifact.openBar('filter')")
        page.locator("[data-filter-fields] .filter-field-button").filter(has_text="Status").click()
        global_picker = page.locator("[data-filter-fields] .filter-values:popover-open")
        expect(global_picker.locator("[data-filter-value='Complete'] small")).to_have_text("8")
        global_picker.locator("[data-filter-value='Complete']").click()
        expect(page.locator("body > [data-header-notices] [data-filter-warning]")).to_be_visible()
        expect(page.locator("[data-menu-button]")).not_to_have_attribute("data-filter-active", "true")
        page.screenshot(path=str(tmp_path / "counted-filter-pickers.png"))
        (tmp_path / "table-controls.json").write_text(json.dumps({"errors": errors,
            "metadata": terms, "scopedCount": 8, "propertiesRemainVisibility": True}), encoding="utf-8")
        assert errors == []
    finally:
        page.close()


def _write_reader_artifact(root, spec=None, page_size=20):
    manifest = _write_reader_fixture(root)
    if spec:
        chapter = root / "chapter.md"
        text = chapter.read_text(encoding="utf-8")
        previous = text.split("```base\n")[1].split("```")[0]
        definition = yaml.safe_load(previous)
        spec(definition)
        chapter.write_text(text.replace(previous, yaml.safe_dump(definition)), encoding="utf-8")
    (root / "after.md").write_text("# Subsequent chapter\n\nA stable destination.", encoding="utf-8")
    manifest.write_text(manifest.read_text(encoding="utf-8").replace(
        "- [[chapter]]", "- [[chapter]]\n- [[after]]"), encoding="utf-8")
    output = root / "reader.html"
    output.write_text(render_artifact(manifest, parse_manifest(manifest), table_page_size=page_size),
                      encoding="utf-8")
    return output


def test_native_mounted_pagination_and_stable_logical_numbers(tmp_path, reader_browser):
    from playwright.sync_api import expect

    def configure(spec):
        spec["views"][0]["obsHtml"].pop("pagination")
        spec["views"][0]["obsHtml"].update(wide=True, screenPageBreaks=False)

    output = _write_reader_artifact(tmp_path, configure)
    page = reader_browser.new_page(viewport={"width": 1500, "height": 1000})
    try:
        page.goto(output.as_uri())
        page.evaluate("obsPages.setPaged(true); obsArtifact.activateChapter('after')")
        page.wait_for_function("!document.querySelector('[data-active-chapter] [aria-busy=true]')")
        after = page.locator(".paged-reader .paper-page-number").all_text_contents()
        page.evaluate("obsArtifact.activateChapter('chapter')")
        table = page.locator(".paged-reader [data-data-table='chapter-base-1']")
        expect(table.locator(".data-table-page")).to_have_text("Page 1 of 4")
        numbers = page.locator(".paged-reader .paper-page-number").all_text_contents()
        assert int(re.search(r"Page (\d+)", after[0])[1]) == (
            int(re.search(r"Page (\d+)", numbers[-1])[1]) + 1)
        first = table.locator("tr[data-row-key]").evaluate_all("rows=>rows.map(r=>r.dataset.rowKey)")
        table.locator(".data-table-tree-toggle").first.click()
        assert table.locator("tbody tr[data-row-key]").first.evaluate(
            "row=>row.nextElementSibling?.dataset.detailOwner===row.dataset.rowKey")
        expect(table.locator(".data-table-page")).to_have_text("Page 1 of 4")
        table.get_by_role("button", name="Next table page", exact=True).click()
        expect(table.locator(".data-table-page")).to_have_text("Page 2 of 4")
        second = table.locator("tr[data-row-key]").evaluate_all("rows=>rows.map(r=>r.dataset.rowKey)")
        assert first != second
        table.get_by_role("button", name="Previous table page", exact=True).press("Enter")
        expect(table.locator(".data-table-page")).to_have_text("Page 1 of 4")
        assert table.locator("tr[data-row-key]").evaluate_all(
            "rows=>rows.map(r=>r.dataset.rowKey)") == first
        table.locator(".data-table-page").click()
        direct = table.get_by_role("spinbutton", name="Table page", exact=True)
        direct.fill("3")
        direct.press("Enter")
        expect(table.locator(".data-table-page")).to_have_text("Page 3 of 4")
        table.get_by_role("button", name="Last table page", exact=True).click()
        expect(table.locator(".data-table-page")).to_have_text("Page 4 of 4")
        table.get_by_role("button", name="First table page", exact=True).click()
        size = table.get_by_role("spinbutton", name="Items per page", exact=True)
        size.fill("5")
        size.press("Tab")
        expect(table.locator(".data-table-page")).to_have_text("Page 1 of 13")
        assert page.locator(".paged-reader .paper-page-number").all_text_contents() == numbers
        page.evaluate("obsArtifact.activateChapter('after')")
        expect(page.locator(".paged-reader .paper-page-number")).to_have_text(after)
        page.evaluate("obsArtifact.activateChapter('chapter')")
        expect(table.locator(".data-table-page")).to_have_text("Page 1 of 4")
    finally:
        page.close()
