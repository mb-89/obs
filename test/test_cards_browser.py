"""Native check of the same data-only contracts with non-reference service records."""
import json
import os
from urllib.parse import quote

import pytest

from obs_html.content import parse_manifest
from obs_html.renderer import render_artifact


def test_native_generic_cards_follow_global_not_local_filters(tmp_path):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native card checks.")
    from playwright.sync_api import sync_playwright, expect

    card = {"version": 1, "cards": [
        {"title": "Service health", "body": "Ordinary **operations**.", "metrics": [
            {"label": "Availability", "where": [{"field": "healthy", "equals": "yes"}],
             "denominator": [{"field": "kind", "equals": "service"}]},
            {"label": "Regions", "where": [{"field": "kind", "equals": "service"}], "distinct": "region"},
        ]},
        {"title": "Evidence", "body": "Static [instructions](https://example.org)."},
    ]}
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n\n```cards\n" + json.dumps(card) + "\n```\n", encoding="utf-8")
    (tmp_path / "chapter.md").write_text(
        "# Operations\n\n[[one]] [[two]] [[three]]\n\n"
        "```base\nfilters: 'kind == \"service\"'\nviews:\n  - type: table\n"
        "    order: [healthy, region]\n```\n", encoding="utf-8",
    )
    for name, healthy, region in [("one", "yes", "north"), ("two", "no", "south"), ("three", "yes", "north")]:
        (tmp_path / f"{name}.md").write_text(
            "---\n" + json.dumps({"kind": "service", "healthy": healthy, "region": region}) + "\n---\n",
            encoding="utf-8",
        )
    artifact = tmp_path / "artifact.html"
    manifest = tmp_path / "manifest.md"
    artifact.write_text(render_artifact(manifest, parse_manifest(manifest)), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(artifact.as_uri())
        page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('home')")
        card = page.locator("[data-active-chapter] [data-record-card]").first
        expect(card.locator("strong").first).to_have_text("66.7%")
        expect(card.locator("[data-record-metric='1'] strong")).to_have_text("2")
        evidence = page.locator("[data-active-chapter] [data-record-card]").nth(1).inner_text()
        page.evaluate("obsArtifact.setFilter(obsQuery.compile('region:north'))")
        expect(card.locator("strong").first).to_have_text("100.0%")
        page.evaluate("obsArtifact.setFilter(obsQuery.compile('region:missing'))")
        expect(card.locator("strong").first).to_have_text("-")
        expect(card.locator("[data-record-metric='1'] strong")).to_have_text("0")
        assert page.locator("[data-active-chapter] [data-record-card]").nth(1).inner_text() == evidence
        page.evaluate("obsArtifact.setFilter(obsQuery.compile(''))")
        expect(card.locator("strong").first).to_have_text("66.7%")
        assert errors == []
        browser.close()


def test_native_weighted_coverage_pills_are_compact_and_evidence_is_wider(tmp_path):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native card checks.")
    from playwright.sync_api import sync_playwright, expect

    card = {"version": 1, "cards": [{
        "title": "Coverage", "body": "", "metricStyle": "pills",
        "metrics": [{
            "label": "Covered", "where": [{"field": "status", "equals": "yes"}],
            "denominator": [{"field": "kind", "equals": "trace"}], "link": "#chapter",
        }],
    }]}
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "chapter.md").write_text(
        "# Results\n\n||| 1:2\n```cards\n" + json.dumps(card) + "\n```\n"
        "|||\nEvidence remains readable in its wider column. See [[path]].\n|||\n",
        encoding="utf-8",
    )
    (tmp_path / "path.md").write_text(
        '---\nkind: trace\nstatus: "yes"\n---\n', encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    artifact = tmp_path / "artifact.html"
    artifact.write_text(render_artifact(manifest, parse_manifest(manifest)), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(artifact.as_uri())
        page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('chapter')")
        columns = page.locator(".markdown-columns--weighted")
        expect(columns).to_have_count(1)
        first, second = columns.locator(".markdown-column").nth(0), columns.locator(".markdown-column").nth(1)
        ratio = page.evaluate("""() => {
            const columns = document.querySelectorAll('.markdown-columns--weighted .markdown-column');
            return columns[0].getBoundingClientRect().width / columns[1].getBoundingClientRect().width;
        }""")
        assert 0.45 <= ratio <= 0.55
        metric = first.locator(".record-metric")
        expect(metric).to_have_count(1)
        expect(metric.locator("strong")).to_have_text("100.0%")
        assert metric.evaluate("(node) => node.getBoundingClientRect().height <= 30")
        expect(metric.locator("a[href='#chapter']")).to_have_count(1)
        assert second.evaluate("(node) => node.getBoundingClientRect().width") > first.evaluate(
            "(node) => node.getBoundingClientRect().width",
        )
        dimensions = {
            "coverage_width_px": first.evaluate("(node) => node.getBoundingClientRect().width"),
            "evidence_width_px": second.evaluate("(node) => node.getBoundingClientRect().width"),
            "coverage_to_evidence_ratio": ratio,
            "pill_height_px": metric.evaluate("(node) => node.getBoundingClientRect().height"),
        }
        page.screenshot(path=str(tmp_path / "compact-pills.png"))
        page.set_viewport_size({"width": 600, "height": 900})
        assert columns.evaluate(
            "node => getComputedStyle(node).gridTemplateColumns.split(' ').length",
        ) == 1
        dimensions["mobile_stacks"] = True
        (tmp_path / "compact-pill-dimensions.json").write_text(json.dumps(dimensions), encoding="utf-8")
        browser.close()


def test_native_card_metric_link_filters_and_focuses_embedded_table_group(tmp_path):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native card checks.")
    from playwright.sync_api import sync_playwright, expect

    body = (
        "```base\n"
        "filters:\n"
        "  and: ['kind == \"service\"']\n"
        "obsHtml: {records: note}\n"
        "views:\n"
        "  - type: table\n"
        "    name: Services\n"
        "    order: [healthy, region]\n"
        "    groupBy: {property: region}\n"
        "```"
    )
    region = 'North "East" & \\ Route'
    table_filter = f"region:{json.dumps(region)}"
    metric_link = (
        "#chapter/@table-group--chapter-base-3--region--north-east-route?tableFilter="
        + quote(table_filter, safe="~!*'()-._")
    )
    exact_group_link = (
        "#chapter/@table-group--chapter-base-4--segment--active?tableFilter="
        + quote("segment:/^active$/", safe="~!*'()-._")
    )
    card = {"version": 1, "cards": [{
        "title": "Services",
        "body": body,
        "metrics": [{
            "label": "Healthy",
            "where": [{"field": "healthy", "equals": "yes"}],
            "denominator": [{"field": "kind", "equals": "service"}],
            "link": metric_link,
        }, {
            "label": "Active",
            "where": [{"field": "segment", "equals": "active"}],
            "denominator": [{"field": "kind", "equals": "service"}],
            "link": exact_group_link,
        }],
    }]}
    (tmp_path / "manifest.md").write_text(
        "- [[chapter]]\n\n```cards\n" + json.dumps(card) + "\n```\n", encoding="utf-8",
    )
    chapter_table = (
        "```base\n"
        "filters:\n"
        "  and: ['kind == \"service\"']\n"
        "obsHtml: {records: note}\n"
        "views:\n"
        "  - type: table\n"
        "    name: Services\n"
        "    order: [healthy, region]\n"
        "```\n"
    )
    grouped_table = chapter_table.replace(
        "    order: [healthy, region]\n",
        "    order: [healthy, region]\n    groupBy: {property: region}\n",
    )
    exact_group_table = chapter_table.replace(
        "    order: [healthy, region]\n",
        "    order: [healthy, segment]\n    groupBy: {property: segment}\n",
    )
    (tmp_path / "chapter.md").write_text(
        "# Operations\n\n" + chapter_table + "\n" + chapter_table + "\n"
        + grouped_table + "\n" + exact_group_table,
        encoding="utf-8",
    )
    for name, healthy, region in [
        ("one", "yes", region), ("two", "no", "south"), ("three", "yes", region),
    ]:
        (tmp_path / f"{name}.md").write_text(
            "---\n" + json.dumps({
                "kind": "service", "healthy": healthy, "region": region,
                "segment": {"yes": "active", "no": "inactive"}[healthy]
                + ("" if name == "one" else "-plus" if name == "three" else ""),
            }) + "\n---\nService details.\n",
            encoding="utf-8",
        )
    artifact = tmp_path / "artifact.html"
    manifest = tmp_path / "manifest.md"
    artifact.write_text(render_artifact(manifest, parse_manifest(manifest)), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(artifact.as_uri())
        page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('home')")
        card = page.locator("[data-active-chapter] [data-record-card]").first
        metric = card.locator(".record-metric-value").first
        expect(metric.locator("strong")).to_have_text("66.7%")
        expect(metric).to_have_attribute("href", metric_link)
        expect(metric).to_have_attribute("aria-label", "66.7% Healthy")
        metric_row_box = card.locator(".record-metrics").bounding_box()
        assert metric_row_box and metric_row_box["height"] < 60
        assert all(
            row["height"] < 30
            for row in card.locator(".record-metric").evaluate_all(
                "nodes => nodes.map(node => node.getBoundingClientRect())",
            )
        )
        card_table = page.locator('[data-active-chapter] [data-data-table="home-base-1"]')
        expect(card_table).to_have_count(1)
        expect(card_table.locator("[data-row-key]")).to_have_count(3)
        page.evaluate("""() => {
            const shell = document.querySelector(
                '[data-data-table="home-base-1"].data-table-shell',
            );
            shell.dispatchEvent(new CustomEvent('obs-table-set-filter', {
                detail: {expression: 'region:south'},
            }));
        }""")
        expect(card_table.locator(".data-table-filter").first).to_have_value("region:south")
        expect(card_table.locator("[data-row-key]")).to_have_count(1)
        page.evaluate("""() => {
            document.querySelector('[data-data-table="home-base-1"]')
                .dispatchEvent(new CustomEvent('obs-table-set-filter', {
                    detail: {expression: ''},
                }));
        }""")
        expect(card_table.locator("[data-row-key]")).to_have_count(3)
        metric.click()
        table = page.locator('[data-active-chapter] [data-data-table="chapter-base-3"]')
        expect(table).to_have_count(1)
        expect(table.locator(".data-table-filter").first).to_have_value(table_filter)
        expect(page.locator('[data-active-chapter] pre')).to_have_count(0)
        group = page.locator("#table-group--chapter-base-3--region--north-east-route")
        expect(group).to_have_count(1)
        expect(group).to_be_visible()
        rows = page.locator(
            '[data-active-chapter] [data-data-table="chapter-base-3"] [data-row-key]',
        )
        expect(rows).to_have_count(2)
        page.evaluate("obsArtifact.activateChapter('home')")
        card.locator(".record-metric-value").nth(1).click()
        exact_table = page.locator(
            '[data-active-chapter] [data-data-table="chapter-base-4"]',
        )
        expect(exact_table.locator(".data-table-filter").first).to_have_value(
            "segment:/^active$/",
        )
        expect(exact_table.locator("[data-row-key]")).to_have_count(1)
        exact_group = page.locator("#table-group--chapter-base-4--segment--active")
        expect(exact_group).to_have_count(1)
        expect(exact_group).to_be_visible()
        page.evaluate("""() => {
            window.scrollTargets = [];
            const original = Element.prototype.scrollIntoView;
            Element.prototype.scrollIntoView = function (...args) {
                window.scrollTargets.push({id: this.id, key: this.dataset.dataTable});
                return original.apply(this, args);
            };
        }""")
        page.evaluate(
            "obsArtifact.activateChapter("
            "'chapter/@table-group--chapter-base-3--region--missing?tableFilter=region%3Amissing')",
        )
        expect(table.locator(".data-table-filter").first).to_have_value("region:missing")
        expect(page.locator("#table-group--chapter-base-3--region--missing")).to_have_count(0)
        assert page.evaluate(
            "window.scrollTargets.some(target => target.key === 'chapter-base-3')",
        )
        assert errors == []
        browser.close()


def test_native_card_desktop_layout_keeps_metrics_and_embedded_table_compact(tmp_path):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native card checks.")
    from playwright.sync_api import sync_playwright, expect

    evidence_query = (
        "```base\n"
        "filters:\n"
        "  and: ['kind == \"evidence\"']\n"
        "obsHtml: {records: note}\n"
        "views:\n"
        "  - type: table\n"
        "    name: Evidence\n"
        "    order: [evidenceLabel, description, approved]\n"
        "```"
    )
    metric_labels = [
        "Coverage",
        "findings at Example",
        "explained findings at Example",
        "Exported to System",
        "Exported to SCM",
        "Exported to Labels",
    ]
    card = {"version": 1, "cards": [
        {
            "title": "Results overview",
            "body": "",
            "metrics": [
                {
                    "label": label,
                    "where": [{"field": "kind", "equals": "evidence"}],
                    "denominator": [{"field": "kind", "equals": "evidence"}],
                    "link": "#chapter",
                }
                for label in metric_labels
            ],
        },
        {
            "title": "Evidence",
            "body": evidence_query,
        },
    ]}
    (tmp_path / "manifest.md").write_text(
        "- [[chapter]]\n\n```cards\n" + json.dumps(card) + "\n```\n",
        encoding="utf-8",
    )
    (tmp_path / "chapter.md").write_text("# Results\n", encoding="utf-8")
    for index in range(7):
        (tmp_path / f"evidence-{index}.md").write_text(
            "---\n"
            + json.dumps({
                "kind": "evidence",
                "evidenceLabel": f"Trace — E{index} → E{index + 1}",
                "description": (
                    "Revision 2 plus small updates"
                    if index % 2 else "Initial version, draft"
                ),
                "approved": False,
            }, ensure_ascii=False)
            + "\n---\nExisting evidence note.\n",
            encoding="utf-8",
        )
    artifact = tmp_path / "artifact.html"
    manifest = tmp_path / "manifest.md"
    artifact.write_text(
        render_artifact(manifest, parse_manifest(manifest)),
        encoding="utf-8",
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.goto(artifact.as_uri())
        page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('home')")
        cards = page.locator("[data-active-chapter] [data-record-card]")
        metric_card, evidence_card = cards.nth(0), cards.nth(1)
        metrics = metric_card.locator(".record-metric")
        expect(metrics).to_have_count(6)
        assert all(
            height <= 30
            for height in metrics.evaluate_all(
                "(nodes) => nodes.map(node => node.getBoundingClientRect().height)",
            )
        )
        metric_size = metric_card.evaluate(
            "(node) => ({width: node.getBoundingClientRect().width, "
            "height: node.getBoundingClientRect().height})",
        )
        evidence_size = evidence_card.evaluate(
            "(node) => ({width: node.getBoundingClientRect().width, "
            "height: node.getBoundingClientRect().height})",
        )
        assert metric_size["width"] >= 480
        assert evidence_size["width"] >= 480
        assert metric_size["height"] <= 300
        assert evidence_size["height"] <= 480
        assert metric_size["height"] < evidence_size["height"]
        table = evidence_card.locator("[data-data-table]")
        expect(table.locator("[data-row-key]")).to_have_count(7)
        row_heights = table.locator("tbody tr").evaluate_all(
            "(nodes) => nodes.map(node => node.getBoundingClientRect().height)",
        )
        assert max(row_heights) <= 56

        page.set_viewport_size({"width": 390, "height": 844})
        page.evaluate("obsPages.setPaged(true)")
        assert page.locator(".chapter-scroll").evaluate(
            "reader => reader.scrollWidth <= reader.clientWidth + 1",
        )
        assert all(cards.evaluate_all("""nodes => nodes.map(node =>
            Math.abs(node.getBoundingClientRect().width -
                node.closest(".paper-content").getBoundingClientRect().width) <= 1
        )"""))
        page.evaluate("obsPages.setPaged(false)")
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth + 1",
        )
        mobile_metrics = metric_card.locator(".record-metric")
        expect(mobile_metrics).to_have_count(6)
        assert all(
            height <= 48
            for height in mobile_metrics.evaluate_all(
                "(nodes) => nodes.map(node => node.getBoundingClientRect().height)",
            )
        )
        page.set_viewport_size({"width": 1600, "height": 1000})
        page.evaluate("obsPages.setPaged(true)")
        paged = page.locator(".paged-mode .record-cards")
        expect(paged).to_have_count(1)
        paged_layout = paged.evaluate("""node => ({
            columns: getComputedStyle(node).gridTemplateColumns.trim().split(/\\s+/).length,
            cards: [...node.querySelectorAll('[data-record-card]')].map(card => {
                const box = card.getBoundingClientRect();
                return {top: box.top, bottom: box.bottom, width: box.width};
            }),
        })""")
        assert paged_layout["columns"] == 1
        assert len(paged_layout["cards"]) == 2
        assert paged_layout["cards"][1]["top"] >= paged_layout["cards"][0]["bottom"]
        assert min(card["width"] for card in paged_layout["cards"]) >= 480
        browser.close()
