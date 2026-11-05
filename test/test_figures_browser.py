"""Focused native figure checks; no large report fixture or mocked plotting engine."""
import json
import os

import pytest
import yaml

from obs_html.content import parse_manifest
from obs_html.renderer import render_report
from test_reader_controls import _write_reader_fixture, reader_browser  # noqa: F401


def test_cdn_unavailable_reports_missing_interaction_without_static_payload(tmp_path):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native figure checks.")
    from importlib.resources import files
    from obs_html.config import load_config
    from playwright.sync_api import sync_playwright
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n")
    (tmp_path / "fallback.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"/>',
    )
    (tmp_path / "values.json").write_text("{}")
    (tmp_path / "one.md").write_text(
        "# One\n\n```figure\nversion: 1\nkind: plot\nsource: values.json\n"
        "fallback: fallback.svg\ncaption: Static graph\ndomain: [0, 1]\nsamples: 3\n"
        "equations: {a: x}\ntraces: [{y: a, label: A}]\n```\n",
    )
    override = tmp_path / "cfg.json"
    override.write_text('{"schemaVersion":1,"report":{"figures":{"plotlyDelivery":"cdn"}}}')
    config = load_config(files("obs_html").joinpath("cfg.json"), override)
    output = tmp_path / "report.html"
    output.write_text(render_report(manifest, parse_manifest(manifest), figures=config.figures), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        page = browser.new_page()
        page.route("https://cdn.plot.ly/**", lambda route: route.abort())
        page.goto(output.as_uri() + "#one")
        assert page.evaluate("document.documentElement.dataset.reportStatus") == "ready"
        page.evaluate("obsPages.setPaged(false)")
        figure = page.locator("[data-active-chapter] figure")
        assert "Plotly could not load" in figure.inner_text()
        assert figure.locator("img:not([data-icon-asset])").count() == 0
        assert figure.locator(".figure-chart").count() == 0
        page.add_script_tag(content=files("obs_html").joinpath(
            "vendor", "plotly-basic.min.js",
        ).read_text(encoding="utf-8"))
        page.evaluate("obsFigures.preparePrint(document.querySelector('[data-active-chapter]'))")
        image = figure.locator("img.figure-default")
        assert image.get_attribute("src").startswith("data:image/svg+xml")
        assert image.evaluate("(image) => image.complete && image.naturalWidth > 0")
        browser.close()


def test_migrated_caption_paragraphs_keep_review_identities(tmp_path):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native figure checks.")
    from playwright.sync_api import sync_playwright
    (tmp_path / "manifest.md").write_text("- [[one]]\n", encoding="utf-8")
    (tmp_path / "image.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"/>', encoding="utf-8",
    )
    captions = ["*First caption.*", "*Second qualification.*"]
    versions = [
        "![Alternative](image.svg)\n\n" + "\n\n".join(captions),
        "```figure\n" + yaml.safe_dump({
            "version": 1, "kind": "image", "source": "image.svg", "alt": "Alternative",
            "caption": captions,
        }) + "```",
    ]
    paths = []
    for index, body in enumerate(versions):
        (tmp_path / "one.md").write_text("# One\n\n" + body + "\n\nOrdinary prose.\n", encoding="utf-8")
        manifest = tmp_path / "manifest.md"
        output = tmp_path / f"review-{index}.html"
        output.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
        paths.append(output)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        signatures = []
        for output in paths:
            page = browser.new_page()
            page.goto(output.as_uri() + "#one")
            page.evaluate("obsPages.setPaged(false)")
            page.evaluate("obsReport.openBar('comments')")
            signatures.append(page.locator("[data-active-chapter] [data-review-item]").evaluate_all(
                "(items) => items.map(item => [item.tagName, item.dataset.reviewItem])"
            ))
            if output == paths[-1]:
                assert page.locator("figcaption p[data-review-item]").count() == 2
                assert page.locator("[data-active-chapter] > [data-chapter-body]").count() == 1
                caption = page.locator("figcaption p").first
                caption.get_by_role("button", name="Accept item", exact=False).click()
                assert caption.get_attribute("data-review-state") == "accepted"
                saved = tmp_path / "caption-reviewed.html"
                saved.write_text(page.evaluate("obsComments.reviewedHtml()"), encoding="utf-8")
                reopened = browser.new_page()
                reopened.goto(saved.as_uri() + "#one")
                reopened.evaluate("obsPages.setPaged(false); obsReport.openBar('comments')")
                restored = reopened.locator("figcaption p").first
                assert restored.get_attribute("data-review-item") == caption.get_attribute("data-review-item")
                assert restored.get_attribute("data-review-state") == "accepted"
                reopened.close()
            page.close()
        assert signatures[0] == signatures[1]
        assert len(signatures[0]) == 4
        browser.close()


def test_native_sankey_places_upward_outcome_before_its_source_stage(tmp_path):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native figure checks.")
    from playwright.sync_api import sync_playwright, expect

    (tmp_path / "manifest.md").write_text("- [[flow]]\n", encoding="utf-8")
    (tmp_path / "flow.json").write_text(json.dumps({
        "version": 1,
        "nodes": [
            {"id": "upward-export", "label": "Exported to System", "stage": -1,
             "placement": "above", "color": "#2d7d46"},
            {"id": "source-role", "label": "ELH", "stage": 0},
        ],
        "links": [{
            "source": "source-role", "target": "upward-export", "value": 1,
            "color": "#4f8a62", "series": "path-1",
        }],
    }), encoding="utf-8")
    (tmp_path / "flow.md").write_text(
        "# Flow\n\n```figure\nversion: 1\nkind: sankey\nsource: flow.json\ncaption: Flow\n```\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    output = tmp_path / "report.html"
    output.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        page.goto(output.as_uri() + "#flow")
        page.evaluate("obsPages.setPaged(false)")
        diagram = page.locator("[data-active-chapter] .sankey-canvas")
        expect(diagram).to_have_count(1)
        source_x = float(diagram.locator("[data-node-id='source-role'] rect").get_attribute("x"))
        outcome = diagram.locator("[data-node-id='upward-export'] rect")
        outcome_x = float(outcome.get_attribute("x"))
        assert outcome_x < source_x
        assert outcome.get_attribute("fill") == "#2d7d46"
        assert diagram.locator("[data-flow-value]").first.get_attribute("stroke") == "#4f8a62"
        browser.close()


@pytest.mark.parametrize("placement", ["above", "below"])
def test_native_sankey_same_stage_shared_sink_stays_finite_when_filtered(tmp_path, placement):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native figure checks.")
    from playwright.sync_api import sync_playwright

    (tmp_path / "manifest.md").write_text(
        "---\nobsHtml: {query: {scope: records, where: [{field: kind, equals: path}]}}\n---\n" "- [[flow]]\n", encoding="utf-8",
    )
    (tmp_path / "flow.md").write_text(
        "# Flow\n\n[[early]] [[late]]\n\n"
        "```figure\nversion: 1\nkind: sankey\nsource: flow.json\n```\n", encoding="utf-8",
    )
    for case in ["early", "late"]:
        (tmp_path / f"{case}.md").write_text(f"---\nkind: path\ncase: {case}\n---\n", encoding="utf-8")
    (tmp_path / "flow.json").write_text(json.dumps({
        "version": 1,
        "nodes": [{"id": "early", "label": "Early", "stage": 0},
                  {"id": "late", "label": "Late", "stage": 1},
                  {"id": "sink", "label": "Shared sink", "stage": 1, "placement": placement}],
        "links": [{"source": case, "target": "sink", "value": 1,
                   "where": [{"field": "case", "equals": case}]} for case in ["early", "late"]],
        "data": {"where": [{"field": "kind", "equals": "path"}]},
    }), encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    output = tmp_path / "report.html"
    output.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(output.as_uri() + "#flow")
        page.evaluate("obsPages.setPaged(false)")
        diagram = page.locator("[data-active-chapter] .sankey-canvas")
        assert diagram.locator("[data-flow-value]").count() == 2
        page.evaluate("obsFilter.setExpression('case:late')")
        assert diagram.locator("[data-flow-value]").count() == 1
        assert diagram.locator("[data-node-id='early']").count() == 0
        assert diagram.locator("[data-node-id='sink']").count() == 1
        assert diagram.evaluate("""svg => [...svg.querySelectorAll('rect,path,text')].every(node =>
            [...node.attributes].every(attribute => !/\\b(?:NaN|Infinity)\\b/.test(attribute.value)))""")
        assert errors == []
        browser.close()


def test_native_sankey_origin_adjacent_exports_refit_after_filtered_expansion(tmp_path):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native figure checks.")
    from playwright.sync_api import sync_playwright, expect

    nodes = [{"id": name, "label": name, "stage": index}
             for index, name in enumerate(["A", "B", "C"])]
    nodes += [
        {"id": "early-up", "label": "System", "stage": -1, "placement": "above", "color": "#2d7d46"},
        {"id": "middle-down", "label": "SCM", "stage": 2, "placement": "below", "color": "#2d7d46"},
        {"id": "late-up", "label": "Labels", "stage": 1, "placement": "above", "color": "#2d7d46"},
        {"id": "inactive", "label": "Inactive alternative", "stage": 3, "placement": "below"},
    ]
    links = []
    for source, target, case in [
        ("A", "B", "short"), ("B", "middle-down", "short"),
        ("A", "early-up", "long"), ("A", "B", "long"),
        ("B", "C", "long"), ("C", "late-up", "long"), ("C", "inactive", "missing"),
    ]:
        links.append({"source": source, "target": target, "value": 1,
                      "color": "#4f8a62", "series": case,
                      "where": [{"field": "case", "equals": case}]})
    (tmp_path / "manifest.md").write_text(
        "---\nobsHtml: {query: {scope: records, where: [{field: kind, equals: path}]}}\n---\n" "- [[introduction]]\n- [[flow]]\n", encoding="utf-8",
    )
    (tmp_path / "introduction.md").write_text("# Introduction\n\nRetained explanation.\n", encoding="utf-8")
    (tmp_path / "flow.json").write_text(json.dumps({
        "version": 1, "nodes": nodes, "links": links,
        "data": {"where": [{"field": "kind", "equals": "path"}]},
    }), encoding="utf-8")
    (tmp_path / "flow.md").write_text(
        "# Results\n\n[[short]] [[long]]\n\n"
        "```figure\nversion: 1\nkind: sankey\nsource: flow.json\n```\n", encoding="utf-8",
    )
    for case in ["short", "long"]:
        (tmp_path / f"{case}.md").write_text(
            f"---\nkind: path\ncase: {case}\n---\n", encoding="utf-8",
        )
    manifest = tmp_path / "manifest.md"
    output = tmp_path / "report.html"
    output.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(output.as_uri() + "#flow")
        page.evaluate("obsPages.setPaged(false)")
        diagram = page.locator("[data-active-chapter] .sankey-canvas")
        def center(name):
            rect = diagram.locator(f"[data-node-id='{name}'] rect")
            return float(rect.get_attribute("x")) + float(rect.get_attribute("width")) / 2
        assert center("early-up") < center("A")
        assert center("B") < center("middle-down") < center("C")
        assert center("B") < center("late-up") < center("C")
        assert diagram.locator("[data-node-id='inactive']").count() == 0
        for name in ["early-up", "middle-down", "late-up"]:
            assert diagram.locator(f"[data-node-id='{name}'] rect").get_attribute("fill") == "#2d7d46"
        page.locator("[data-active-chapter] .figure-expand").click()
        page.evaluate("obsFilter.setExpression('case:short')")
        expanded = page.locator("dialog[open] .sankey-canvas")
        expect(expanded).to_have_count(1)
        assert expanded.locator("[data-node-id='C']").count() == 0
        assert expanded.evaluate("""svg => {
            const parent = svg.closest('dialog').getBoundingClientRect();
            const box = svg.getBoundingClientRect();
            return box.width <= parent.width && box.height <= parent.height;
        }""")
        assert page.evaluate("obsReport.exportChapters().some(chapter => chapter.slug === 'introduction')")
        page.screenshot(path=str(tmp_path / "filtered-expanded-sinks.png"))
        assert errors == []
        browser.close()


def test_large_images_fit_paper_independently_of_reader_viewport(tmp_path):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native figure checks.")
    from playwright.sync_api import sync_playwright
    (tmp_path / "manifest.md").write_text("- [[images]]\n", encoding="utf-8")
    body = "# Images\n\n"
    for name, width, height in [("portrait", 1800, 3600), ("landscape", 3600, 1800)]:
        (tmp_path / f"{name}.svg").write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="gray"/></svg>',
            encoding="utf-8",
        )
        body += f"## {name}\n\n![{name}]({name}.svg)\n\n"
    (tmp_path / "images.md").write_text(body, encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    report = tmp_path / "images.html"
    report.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        page = browser.new_page(viewport={"width": 1920, "height": 1440})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.goto(report.as_uri() + "#images")
        page.evaluate("obsPages.setPaged(false); obsPages.setPaged(true)")
        assert "Page layout failed" not in page.locator("[data-export-status]").inner_text()
        assert page.locator(".paged-reader figure").count() == 2
        assert page.locator(".paged-reader .paper-content").evaluate_all(
            "(areas) => areas.every(area => area.scrollHeight <= "
            "parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--paper-height')) * 96 / 25.4)"
        )
        page.evaluate("window.print = () => {}; obsPages.exportPDF()")
        assert page.locator(".print-book figure").count() == 2
        assert page.pdf(prefer_css_page_size=True).startswith(b"%PDF")
        assert errors == []
        browser.close()


@pytest.fixture
def figure_report(tmp_path):
    (tmp_path / "manifest.md").write_text("- [[figures]]\n", encoding="utf-8")
    (tmp_path / "default.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">'
        '<path d="M0 50L200 50M100 0L100 100" stroke="red"/>'
        '<text x="5" y="20">Default composition</text></svg>', encoding="utf-8",
    )
    (tmp_path / "scene.json").write_text(json.dumps({
        "version": 1, "panels": [
            {"id": "left", "title": "Left panel", "box": [0, 0, 100, 100]},
            {"id": "right", "title": "Right panel", "box": [100, 0, 100, 100]},
        ],
    }), encoding="utf-8")
    (tmp_path / "parameters.json").write_text('{"n": 3}', encoding="utf-8")
    plot = {
        "version": 1, "kind": "plot", "source": "parameters.json", "fallback": "default.svg",
        "caption": "Ordinary plot", "domain": [1, 10], "samples": 11,
        "equations": {"a": "x * n", "b": "x / n"},
        "traces": [{"y": "a", "label": "Primary"}, {"y": "b", "label": "Secondary", "axis": "y2"}],
        "layout": {"xaxis": {"range": [1, 10]}, "yaxis": {"type": "log"},
                   "yaxis2": {"overlaying": "y", "side": "right", "type": "linear"}},
    }
    body = (
        "# Figures\n\n```figure\nversion: 1\nkind: svg\nsource: scene.json\n"
        "fallback: default.svg\ncaption: Complex composition\n```\n\n```figure\n"
        + yaml.safe_dump(plot, sort_keys=False) + "```\n\n"
        "![Content image](default.svg \"Image title\")\n"
    )
    (tmp_path / "figures.md").write_text(body, encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    html = render_report(manifest, parse_manifest(manifest))
    assert html.count('id="plotly-script"') == 1
    assert html.count('id="figure-script"') == 1
    report = tmp_path / "report.html"
    report.write_text(html, encoding="utf-8")
    return report


@pytest.fixture
def sankey_report(tmp_path):
    (tmp_path / "manifest.md").write_text("- [[flow]]\n", encoding="utf-8")
    (tmp_path / "flow.json").write_text(json.dumps({
        "version": 1,
        "nodes": [
            {"id": "in-a", "label": "Input A", "stage": 0},
            {"id": "in-b", "label": "Input B", "stage": 0},
            {"id": "out-a", "label": "Output A", "stage": 1},
            {"id": "out-b", "label": "Output B", "stage": 1},
        ],
        "links": [
            {"source": "in-a", "target": "out-a", "value": 3, "label": "Three paths"},
            {"source": "in-b", "target": "out-b", "value": 1},
        ],
    }), encoding="utf-8")
    (tmp_path / "flow.md").write_text(
        "# Trace flow\n\n```figure\nversion: 1\nkind: sankey\nsource: flow.json\ncaption: Trace paths\n```\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    report = tmp_path / "sankey.html"
    report.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    return report


@pytest.fixture
def dynamic_sankey_report(tmp_path):
    (tmp_path / "manifest.md").write_text(
        "---\nobsHtml: {query: {scope: records, where: [{field: kind, equals: flow-record}]}}\n---\n"
        "- [[flow]]\n- [[record-a]]\n- [[record-b]]\n- [[record-c]]\n",
        encoding="utf-8",
    )
    graph = {
        "version": 1,
        "nodes": [
            {"id": "approved", "label": "Approved", "stage": 1,
             "records": {"where": [{"field": "target", "equals": "approved"}]}, "unique": "target"},
            {"id": "rejected", "label": "Rejected", "stage": 1},
            {"id": "request", "label": "Request", "stage": 0},
        ],
        "links": [
            {"source": "request", "target": "approved", "value": 2, "label": "Approved",
             "where": [{"field": "target", "equals": "approved"}], "series": "requests-approved",
             "originColor": "#123456"},
            {"source": "request", "target": "rejected", "value": 1, "label": "Rejected",
             "where": [{"field": "target", "equals": "rejected"}]},
        ],
        "data": {"where": [{"field": "kind", "equals": "flow-record"}]},
    }
    (tmp_path / "flow.json").write_text(json.dumps(graph), encoding="utf-8")
    (tmp_path / "flow.md").write_text(
        "# Dynamic flow\n\n```figure\nversion: 1\nkind: sankey\n"
        "source: flow.json\ncaption: Approval flow\n```\n",
        encoding="utf-8",
    )
    for name, target in (("record-a", "approved"), ("record-b", "approved"), ("record-c", "rejected")):
        (tmp_path / f"{name}.md").write_text(
            f"---\nkind: flow-record\ntarget: {target}\n---\n# {name}\n",
            encoding="utf-8",
        )
    manifest = tmp_path / "manifest.md"
    report = tmp_path / "dynamic-sankey.html"
    report.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    return report


def test_native_figures_interaction_and_default_print(figure_report):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native figure checks.")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(figure_report.as_uri() + "#figures")
        page.evaluate("obsPages.setPaged(false); obsReport.activateChapter('figures')")
        root = page.locator("[data-active-chapter]")
        svg = root.locator('[data-figure-kind="svg"]')
        image = root.locator(".report-figure")
        assert root.locator("[data-report-figure] .figure-expand").count() == 3
        assert all(
            control.is_visible()
            for control in root.locator("[data-report-figure] .figure-expand").all()
        )
        image_button = image.get_by_role("button", name="Expand figure")
        assert image_button.is_visible()
        assert image.locator(":scope > img").get_attribute("alt") == "Content image"
        assert image.locator(":scope > img").get_attribute("title") == "Image title"
        assert image.locator("figcaption").count() == 0
        image.evaluate("el => window._contentImage = el")
        image_button.click()
        image_dialog = page.get_by_role("dialog", name="Enlarged figure")
        assert image_dialog.is_visible()
        assert image_dialog.evaluate(
            "el => el.getBoundingClientRect().width === innerWidth && "
            "el.getBoundingClientRect().height === innerHeight"
        )
        assert image_dialog.locator(".report-figure").evaluate("el => el === window._contentImage")
        page.keyboard.press("Tab")
        assert image_dialog.evaluate("el => el.contains(document.activeElement)")
        image_dialog.get_by_role("button", name="Close enlarged figure").click()
        assert image.get_by_role("button", name="Expand figure").evaluate(
            "el => el === document.activeElement"
        )
        image_button.click()
        page.evaluate("obsReport.activateChapter('home')")
        assert not image_dialog.is_visible()
        page.evaluate("obsReport.activateChapter('figures')")
        image = root.locator(".report-figure")
        image_button = image.get_by_role("button", name="Expand figure")
        assert image_button.is_visible()
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        page.set_viewport_size({"width": 1440, "height": 1000})
        svg_button = svg.get_by_role("button", name="Expand figure")
        assert svg.locator("select").is_hidden()
        svg.evaluate("el => window._svgFigure = el")
        svg_button.click()
        dialog = page.get_by_role("dialog", name="Enlarged figure")
        assert dialog.is_visible()
        live_svg = dialog.locator('[data-figure-kind="svg"]')
        assert live_svg.evaluate("el => el === window._svgFigure")
        assert live_svg.locator("select[aria-label='Figure panel']").is_visible()
        viewport = live_svg.locator(".figure-viewport")
        geometry_fit = viewport.evaluate("""svg => {
            const box=svg.viewBox.baseVal, matrix=svg.getScreenCTM(), r=svg.getBoundingClientRect();
            const first=new DOMPoint(box.x,box.y).matrixTransform(matrix);
            const last=new DOMPoint(box.x+box.width,box.y+box.height).matrixTransform(matrix);
            return {x:(first.x+last.x)/2,y:(first.y+last.y)/2,cx:r.x+r.width/2,cy:r.y+r.height/2,
                sx:matrix.a,sy:matrix.d,fit:Math.min(r.width/(last.x-first.x),r.height/(last.y-first.y))};
        }""")
        assert geometry_fit["x"] == pytest.approx(geometry_fit["cx"], abs=1)
        assert geometry_fit["y"] == pytest.approx(geometry_fit["cy"], abs=1)
        assert geometry_fit["sx"] == pytest.approx(geometry_fit["sy"])
        assert geometry_fit["fit"] == pytest.approx(1, abs=0.01)
        assert not live_svg.locator(".figure-default").is_visible()
        original = viewport.get_attribute("viewBox")
        viewport.hover()
        page.mouse.wheel(0, -100)
        assert viewport.get_attribute("viewBox") != original
        live_svg.get_by_role("button", name="Reset panel").click()
        live_svg.get_by_role("button", name="Zoom in", exact=True).click()
        zoomed = viewport.get_attribute("viewBox")
        assert zoomed != original
        original_values = list(map(float, original.split()))
        zoomed_values = list(map(float, zoomed.split()))
        assert zoomed_values[2] / zoomed_values[3] == pytest.approx(
            original_values[2] / original_values[3]
        )
        live_svg.get_by_role("combobox").select_option("right")
        assert viewport.get_attribute("viewBox") == "100 0 100 100"
        live_svg.get_by_role("combobox").select_option("left")
        assert viewport.get_attribute("viewBox") == zoomed
        viewport.hover()
        page.mouse.down()
        page.mouse.move(850, 700)
        page.mouse.up()
        assert viewport.get_attribute("viewBox") != zoomed
        live_svg.get_by_role("button", name="Reset panel").click()
        assert viewport.get_attribute("viewBox") == original
        page.keyboard.press("Escape")
        assert not dialog.is_visible()
        assert svg_button.evaluate("el => el === document.activeElement")
        chart = page.locator(".figure-chart")
        page.wait_for_function("document.querySelector('[data-active-chapter] .figure-chart')?._fullLayout")
        assert chart.evaluate("el => el._fullLayout.yaxis.type") == "log"
        assert chart.evaluate("el => el._fullLayout.yaxis2.type") == "linear"
        assert chart.evaluate("el => el._fullLayout.legend.borderwidth") == 1
        assert chart.locator(".modebar").is_hidden()
        chart.locator(".nsewdrag").hover()
        page.mouse.wheel(0, -100)
        page.wait_for_function("document.querySelector('[data-active-chapter] .figure-chart')._fullLayout.xaxis.range[0] !== 1")
        chart.locator(".legendtoggle").first.click()
        page.wait_for_function("document.querySelector('[data-active-chapter] .figure-chart').data[0].visible === 'legendonly'")
        chart.evaluate("el => Plotly.relayout(el, {'xaxis.range': [3, 5]})")
        assert chart.evaluate("el => el._fullLayout.xaxis.range") == [3, 5]
        plot_figure = root.locator('[data-figure-kind="plot"]')
        plot_figure.get_by_role("button", name="Expand figure").click()
        plot_dialog = page.get_by_role("dialog", name="Enlarged figure")
        assert chart.locator(".modebar").is_visible()
        assert plot_dialog.get_by_role("button", name="Close enlarged figure").is_visible()
        chart.locator('.modebar-btn[data-title="Reset axes"]').click()
        plot_dialog.get_by_role("button", name="Close enlarged figure").click()
        page.wait_for_function("document.querySelector('[data-active-chapter] .figure-chart')._fullLayout.xaxis.range[0] === 1")
        assert chart.evaluate("el => el.data[0].visible") == "legendonly"
        chart.evaluate("el => Plotly.relayout(el, {'xaxis.range': [3, 5]})")
        plot_figure.get_by_role("button", name="Expand figure").click()
        page.evaluate("window.print = () => {}; obsPages.exportPDF()")
        assert not page.get_by_role("dialog", name="Enlarged figure").is_visible()
        page.emulate_media(media="print")
        printed = page.locator(".print-book [data-engineering-figure]")
        assert printed.count() == 2
        for figure in printed.all():
            assert figure.locator(".figure-default").is_visible()
            assert not figure.locator(".figure-live").is_visible()
            assert figure.locator(".figure-provenance").count() == 0
            assert figure.locator("figcaption").evaluate(
                "el => getComputedStyle(el).textAlign"
            ) == "center"
        print_image = page.locator(".print-book .report-figure")
        assert print_image.locator("img").is_visible()
        assert print_image.get_by_role("button", name="Expand figure").count() == 0
        assert print_image.locator("figcaption").count() == 0
        pdf = page.pdf(print_background=True)
        assert pdf.startswith(b"%PDF")
        (figure_report.parent / "native-default-print.pdf").write_bytes(pdf)
        assert errors == []
        browser.close()


def test_dynamic_sankey_recomputes_from_canonical_records_and_shared_filter(dynamic_sankey_report):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native figure checks.")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(dynamic_sankey_report.as_uri() + "#flow")
        page.evaluate("obsPages.setPaged(false); obsReport.activateChapter('flow')")
        svg = page.locator("[data-active-chapter] .figure-sankey svg")
        links = svg.locator(".sankey-link")
        assert [links.nth(index).get_attribute("data-flow-value") for index in range(2)] == ["2", "1"]
        assert "2 records" in svg.locator('[data-node-id="approved"]').text_content()
        assert "1 unique" in svg.locator('[data-node-id="approved"]').text_content()
        assert svg.locator(".sankey-origin").get_attribute("stroke") == "#123456"
        page.evaluate("obsFilter.setExpression('target: approved')")
        page.wait_for_function(
            "Array.from(document.querySelectorAll('[data-active-chapter] .sankey-link')).map"
            "(link => link.dataset.flowValue).join(',') === '2'"
        )
        assert links.count() == 1
        assert links.first.get_attribute("data-flow-value") == "2"
        assert svg.locator('[data-node-id="rejected"]').count() == 0
        page.evaluate("obsFilter.setExpression('target: rejected')")
        page.wait_for_function(
            "Array.from(document.querySelectorAll('[data-active-chapter] .sankey-link')).map"
            "(link => link.dataset.flowValue).join(',') === '1'"
        )
        assert links.count() == 1
        assert links.first.get_attribute("data-flow-value") == "1"
        assert svg.locator('[data-node-id="approved"]').count() == 0
        page.evaluate("obsFilter.setExpression('')")
        page.wait_for_function(
            "Array.from(document.querySelectorAll('[data-active-chapter] .sankey-link')).map"
            "(link => link.dataset.flowValue).join(',') === '2,1'"
        )
        assert errors == []
        browser.close()


def test_native_sankey_is_portable_and_prints_as_svg(sankey_report):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native figure checks.")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(sankey_report.as_uri() + "#flow")
        page.evaluate("obsPages.setPaged(false); obsReport.activateChapter('flow')")
        figure = page.locator("[data-active-chapter] .figure-sankey")
        svg = figure.locator("svg[role=img]")
        assert svg.get_attribute("aria-label") == "Trace paths"
        assert svg.locator(".sankey-node").count() == 4
        screen_dimensions = figure.evaluate(
            "figure => ({container:figure.clientWidth, scroll:figure.scrollWidth, svg:figure.querySelector('svg').getBoundingClientRect().width})"
        )
        assert screen_dimensions["scroll"] <= screen_dimensions["container"] + 1
        links = svg.locator(".sankey-link")
        assert links.count() == 2
        assert links.nth(0).locator("title").text_content() == "Input A → Output A: Three paths (3)"
        assert svg.locator(".sankey-link-label").count() == 2
        widths = [float(links.nth(index).get_attribute("stroke-width")) for index in range(2)]
        assert max(widths) / min(widths) == pytest.approx(3)
        assert not page.locator("#plotly-script").count()
        page.screenshot(path=str(sankey_report.parent / "sankey-native.png"), full_page=True)
        page.evaluate("window.print = () => {}; obsPages.exportPDF()")
        page.emulate_media(media="print")
        print_figure = page.locator(".print-book .figure-sankey")
        print_svg = print_figure.locator("svg")
        assert print_svg.is_visible()
        dimensions = print_figure.evaluate(
            "figure => ({container: figure.clientWidth, svg: figure.querySelector('svg').getBoundingClientRect().width})"
        )
        assert dimensions["svg"] <= dimensions["container"] + 1
        assert page.pdf(print_background=True).startswith(b"%PDF")
        assert errors == []
        browser.close()


def test_normal_images_fit_viewport_in_both_reading_modes(tmp_path):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native figure checks.")
    from playwright.sync_api import sync_playwright
    variants = {
        "large-portrait": (1800, 3600), "large-landscape": (3600, 1800),
        "small-portrait": (40, 80), "small-landscape": (80, 40),
    }
    (tmp_path / "manifest.md").write_text("- [[images]]\n", encoding="utf-8")
    body = "# Images\n\n"
    for name, (width, height) in variants.items():
        (tmp_path / f"{name}.svg").write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="gray"/></svg>',
            encoding="utf-8",
        )
        body += f"![{name}]({name}.svg)\n\n"
    (tmp_path / "images.md").write_text(body, encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    report = tmp_path / "images.html"
    report.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(report.as_uri() + "#images")
        for paged in (False, True):
            page.evaluate("paged => { obsPages.setPaged(paged); obsReport.activateChapter('images'); }", paged)
            for name, (width, height) in variants.items():
                image = page.locator(f'[data-active-chapter] img[alt="{name}"]')
                image.wait_for(state="attached")
                page.wait_for_function(
                    "(alt) => document.querySelector(`[data-active-chapter] img[alt=\"${alt}\"]`)?.complete",
                    arg=name,
                )
                box = image.bounding_box()
                assert box["height"] <= 900 * 0.8 + 1, (paged, name, box)
                assert box["width"] <= width + 1, (paged, name, box)
                assert box["height"] <= height + 1, (paged, name, box)
                assert box["width"] / box["height"] == pytest.approx(width / height, rel=0.01)
                assert box["x"] >= -1 and box["x"] + box["width"] <= 1441
            large = page.locator('[data-active-chapter] img[alt="large-portrait"]')
            normal_height = large.bounding_box()["height"]
            large.locator("..").get_by_role("button", name="Expand figure").click()
            dialog = page.get_by_role("dialog", name="Enlarged figure")
            assert dialog.is_visible()
            assert dialog.locator('img[alt="large-portrait"]').bounding_box()["height"] > normal_height
            page.keyboard.press("Escape")
            assert not dialog.is_visible()
        browser.close()


def test_expanded_plot_reflows_and_legend_is_movable(figure_report):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native figure checks.")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(figure_report.as_uri() + "#figures")
        page.evaluate("obsPages.setPaged(false); obsReport.activateChapter('figures')")
        chart = page.locator(".figure-chart")
        page.wait_for_function("document.querySelector('.figure-chart')?._fullLayout")
        normal = chart.bounding_box()
        chart.evaluate("el => Plotly.relayout(el, {'xaxis.range': [3, 5]})")
        figure = page.locator('[data-active-chapter] [data-figure-kind="plot"]')
        figure.get_by_role("button", name="Expand figure").click()
        page.wait_for_function("document.querySelector('.figure-overlay .figure-chart')._fullLayout.height > 800")
        assert chart.bounding_box()["width"] > normal["width"]
        close_box = page.get_by_role("button", name="Close enlarged figure").bounding_box()
        assert close_box["x"] > 1440 * 0.9
        assert close_box["y"] < 60
        assert close_box["y"] + close_box["height"] <= chart.bounding_box()["y"]
        assert chart.evaluate("el => el._fullLayout.xaxis.range") == [3, 5]
        legend = chart.locator("g.legend")
        legend.focus()
        before = chart.evaluate("el => ({x:el.layout.legend.x,y:el.layout.legend.y})")
        page.keyboard.press("ArrowLeft")
        page.wait_for_function(
            "before => document.querySelector('.figure-chart').layout.legend.x !== before",
            arg=before["x"],
        )
        position = chart.evaluate("el => ({x:el.layout.legend.x,y:el.layout.legend.y})")
        background = legend.locator("rect.bg")
        box = background.bounding_box()
        page.mouse.move(box["x"] + 5, box["y"] + 5)
        page.mouse.down()
        page.mouse.move(box["x"] - 75, box["y"] + 45, steps=10)
        page.mouse.up()
        page.wait_for_function(
            "position => document.querySelector('.figure-chart').layout.legend.x !== position.x",
            arg=position,
        )
        moved = chart.evaluate("el => ({x:el.layout.legend.x,y:el.layout.legend.y})")
        assert chart.evaluate("el => el._fullLayout.xaxis.range") == [3, 5]
        legend.locator(".legendtoggle").first.click()
        page.wait_for_function("document.querySelector('.figure-chart').data[0].visible === 'legendonly'")
        page.keyboard.press("Escape")
        page.wait_for_function("document.querySelector('.figure-chart')._fullLayout.height === 450")
        figure.get_by_role("button", name="Expand figure").click()
        page.wait_for_function("document.querySelector('.figure-chart')._fullLayout.height > 800")
        assert chart.evaluate("el => ({x:el.layout.legend.x,y:el.layout.legend.y})") == moved
        assert chart.evaluate("el => el.data[0].visible") == "legendonly"
        page.set_viewport_size({"width": 700, "height": 700})
        page.wait_for_function("document.querySelector('.figure-chart')._fullLayout.height < 700")
        assert chart.bounding_box()["height"] > 500
        legend_box = legend.bounding_box()
        assert legend_box["x"] >= 0 and legend_box["x"] + legend_box["width"] <= 700
        chart.evaluate("el => Plotly.relayout(el, {'legend.x': -1, 'legend.y': 2})")
        page.wait_for_function("""() => {
            const chart=document.querySelector('.figure-chart').getBoundingClientRect();
            const legend=document.querySelector('.figure-chart g.legend').getBoundingClientRect();
            return legend.x>=chart.x-1 && legend.y>=chart.y-1;
        }""")
        page.keyboard.press("Escape")
        browser.close()


def test_expanded_images_are_centered_at_largest_fit(tmp_path):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native figure checks.")
    from playwright.sync_api import sync_playwright
    (tmp_path / "manifest.md").write_text("- [[images]]\n", encoding="utf-8")
    body = "# Images\n\n"
    for name, width, height in (("portrait", 200, 400), ("landscape", 400, 200)):
        (tmp_path / f"{name}.svg").write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="gray"/></svg>',
            encoding="utf-8",
        )
        body += f"![{name}]({name}.svg)\n\n"
    (tmp_path / "images.md").write_text(body, encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    report = tmp_path / "images.html"
    report.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(report.as_uri() + "#images")
        page.evaluate("obsPages.setPaged(false);obsReport.activateChapter('images')")
        for name in ("portrait", "landscape"):
            figure = page.locator("[data-active-chapter] .report-figure").filter(
                has=page.locator(f'img[alt="{name}"]'),
            )
            figure.evaluate("""figure => {
                const caption=document.createElement('figcaption');
                caption.textContent='A caption retained below the full image in the overlay';
                figure.append(caption);
            }""")
            figure.get_by_role("button", name="Expand figure").click()
            for viewport in ({"width": 1440, "height": 1000}, {"width": 390, "height": 844}):
                page.set_viewport_size(viewport)
                page.wait_for_timeout(100)
                metrics = page.locator(".figure-expanded").evaluate("""figure => {
                    const r=figure.getBoundingClientRect(), s=getComputedStyle(figure);
                    const image=figure.querySelector('img'), i=image.getBoundingClientRect();
                    const caption=figure.querySelector('figcaption'), c=getComputedStyle(caption);
                    const captionHeight=caption.getBoundingClientRect().height+parseFloat(c.marginTop)+parseFloat(c.marginBottom);
                    return {left:r.left+parseFloat(s.paddingLeft),top:r.top+parseFloat(s.borderTopWidth)+parseFloat(s.paddingTop),
                        width:figure.clientWidth-parseFloat(s.paddingLeft)-parseFloat(s.paddingRight),
                        height:figure.clientHeight-parseFloat(s.paddingTop)-parseFloat(s.paddingBottom)-captionHeight,
                        x:i.x,y:i.y,w:i.width,h:i.height,ratio:image.naturalWidth/image.naturalHeight};
                }""")
                assert metrics["w"] / metrics["h"] == pytest.approx(metrics["ratio"], rel=0.01)
                assert metrics["x"] + metrics["w"] / 2 == pytest.approx(
                    metrics["left"] + metrics["width"] / 2, abs=1,
                )
                assert metrics["y"] + metrics["h"] / 2 == pytest.approx(
                    metrics["top"] + metrics["height"] / 2, abs=1,
                )
                assert min(metrics["width"] / metrics["w"], metrics["height"] / metrics["h"]) == pytest.approx(1, abs=0.01)
            page.keyboard.press("Escape")
        browser.close()


@pytest.mark.parametrize("paged", [False, True])
def test_native_deferred_figure_binds_counts_on_first_entry_and_reentry(tmp_path, reader_browser, paged):
    from playwright.sync_api import expect

    manifest = _write_reader_fixture(tmp_path)
    chapter = tmp_path / "chapter.md"
    chapter.write_text(chapter.read_text(encoding="utf-8") +
        "\n```figure\nversion: 1\nkind: sankey\nsource: graph.json\nalt: Counted graph\n```\n",
        encoding="utf-8")
    where = [{"field": "status", "equals": "Complete 0"}]
    (tmp_path / "graph.json").write_text(json.dumps({
        "version": 1, "branchLayout": "split",
        "data": {"where": [{"field": "kind", "equals": "relation"}]},
        "nodes": [{"id": name, "label": name.title(), "stage": index,
                   "records": {"where": where}, "unique": "status"}
                  for index, name in enumerate(("source", "target"))],
        "links": [{"source": "source", "target": "target", "value": 1, "where": where}],
    }), encoding="utf-8")
    report = tmp_path / "deferred-figure.html"
    report.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    page = reader_browser.new_page(viewport={"width": 1500, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(report.as_uri())
        page.evaluate("obsHtmlReady")
        page.evaluate("paged => obsPages.setPaged(paged)", paged)
        root = ".paged-reader" if paged else "[data-active-chapter]"
        for _ in range(2):
            page.evaluate("obsReport.activateChapter('chapter')")
            page.evaluate("obsReport.whenChapterReady()")
            figure = page.locator(root + " [data-figure-kind='sankey']")
            expect(figure.locator(".sankey-label tspan")).to_have_text([
                "Source", "1 records", "1 unique", "Target", "1 records", "1 unique",
            ])
            page.evaluate("expression => obsReport.setFilter(obsQuery.compile(expression))",
                "slug:chapter OR status:does-not-exist")
            expect(figure).to_be_visible()
            expect(figure.locator(".sankey-canvas")).to_contain_text("No matching records")
            page.evaluate("obsReport.setFilter(obsQuery.compile(''))")
            expect(figure.locator(".sankey-label tspan")).to_have_text([
                "Source", "1 records", "1 unique", "Target", "1 records", "1 unique",
            ])
            page.evaluate("obsReport.activateChapter('home')")
            page.evaluate("obsReport.whenChapterReady()")
        assert errors == []
    finally:
        page.close()
