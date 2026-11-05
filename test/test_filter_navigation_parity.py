"""Small public-contract regressions for record filtering and Sankey selection."""
import json
import os
import re
from xml.etree import ElementTree

import pytest
import yaml

from obs_html.cli import main
from obs_html.content import ContentError, parse_manifest, read_chapter_content, read_manifest
from obs_html.figures import render_figure


QUERY = {
    "scope": "records",
    "where": [{"field": "kind", "equals": "path"}],
    "fields": [
        {"field": "subject", "source": "subject.name", "label": "Subject"},
        {"field": "route", "label": "Route"},
    ],
}


def test_record_only_note_profile_is_validated_and_cannot_be_a_chapter(tmp_path):
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n", encoding="utf-8")
    note = tmp_path / "one.md"
    note.write_text("---\nobsHtml: {document: never}\n---\n", encoding="utf-8")
    with pytest.raises(ContentError, match="obsHtml"):
        read_chapter_content(parse_manifest(manifest)[0])
    note.write_text("---\nobsHtml: {document: false}\n---\n", encoding="utf-8")
    with pytest.raises(SystemExit) as failure:
        main(["--source", str(tmp_path), "--check"])
    assert failure.value.code == 2


def _manifest(query: dict, chapters: str) -> str:
    return "---\n" + json.dumps({"obsHtml": {"query": query}}) + "\n---\n" + chapters


def test_record_query_profile_is_declared_in_the_manifest(tmp_path):
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n", encoding="utf-8")
    (tmp_path / "one.md").write_text("# One\n", encoding="utf-8")
    assert read_manifest(manifest).presentation["query"] == {"scope": "chapters"}
    manifest.write_text(_manifest(QUERY, "- [[one]]\n"), encoding="utf-8")
    assert read_manifest(manifest).presentation["query"] == QUERY


@pytest.mark.parametrize("kind", ["sankey", "image", "plot", "svg"])
def test_figures_without_caption_have_accessible_name_and_no_placeholder(tmp_path, kind):
    (tmp_path / "fallback.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100"/>',
        encoding="utf-8",
    )
    (tmp_path / "graph.json").write_text(json.dumps({
        "version": 1,
        "nodes": [
            {"id": "a", "label": "A", "stage": 0},
            {"id": "b", "label": "B", "stage": 1, "placement": "above"},
        ],
        "links": [{"source": "a", "target": "b", "value": 1}],
    }), encoding="utf-8")
    (tmp_path / "values.json").write_text(json.dumps({
        "version": 1, "panels": [{"id": "a", "title": "A", "box": [0, 0, 200, 100]}],
    }), encoding="utf-8")
    spec = {"version": 1, "kind": kind, "source": "values.json", "alt": "Accessible graph"}
    if kind == "sankey":
        spec["source"] = "graph.json"
    elif kind == "image":
        spec["source"] = "fallback.svg"
    else:
        spec["fallback"] = "fallback.svg"
    if kind == "plot":
        (tmp_path / "values.json").write_text("{}", encoding="utf-8")
        spec.update(domain=[0, 1], samples=3, equations={"y": "x"}, traces=[{"y": "y", "label": "Y"}])
    html = render_figure(yaml.safe_dump(spec), tmp_path / "one.md", tmp_path)
    assert "<figcaption" not in html
    assert "Accessible graph" in html


def test_static_sankey_declared_sinks_are_compact_above_and_below_flow(tmp_path):
    graph = {
        "version": 1,
        "nodes": [
            {"id": "source", "label": "Source", "stage": 0},
            {"id": "upper", "label": "Upper", "stage": 1, "placement": "above"},
            {"id": "lower", "label": "Lower", "stage": 1, "placement": "below"},
            {"id": "covered", "label": "Covered", "stage": 1},
        ],
        "links": [{"source": "source", "target": target, "value": 1}
                  for target in ["upper", "lower", "covered"]],
    }
    (tmp_path / "graph.json").write_text(json.dumps(graph), encoding="utf-8")
    html = render_figure(
        "version: 1\nkind: sankey\nsource: graph.json", tmp_path / "one.md", tmp_path,
    )
    svg = ElementTree.fromstring(re.search(r"<svg.*?</svg>", html, re.S)[0])
    rects = {
        node.attrib["data-node-id"]: {key: float(value) for key, value in node[0].attrib.items()
                                     if key in {"x", "y", "width", "height"}}
        for node in svg.findall("{*}g")
    }
    assert rects["upper"]["width"] > rects["upper"]["height"]
    assert rects["lower"]["width"] > rects["lower"]["height"]
    assert rects["upper"]["y"] < rects["source"]["y"]
    assert rects["lower"]["y"] > rects["source"]["y"] + rects["source"]["height"]
    assert rects["covered"]["height"] > rects["covered"]["width"]


@pytest.fixture
def parity_artifact(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text(_manifest(QUERY, "- [[flow]]\n- [[results]]\n"), encoding="utf-8")
    # Route is near-unique (4 values / 4 records); the project ratio override keeps it a facet.
    (vault / "cfg.json").write_text(
        json.dumps({"schemaVersion": 1, "artifact": {"facetDistinctRatio": 1}}),
        encoding="utf-8",
    )
    nodes = [
        {"id": "in", "label": "Input", "stage": 0},
        {"id": "out", "label": "Output", "stage": 1},
        {"id": "stop", "label": "Stopped", "stage": 1, "placement": "above"},
        {"id": "down", "label": "Other stop", "stage": 1, "placement": "below"},
    ]
    links = []
    for route, target in [("A.1", "out"), ("A.10", "out"), ("B", "stop"), ("C", "down")]:
        links.append({
            "source": "in", "target": target, "value": 1, "series": route,
            "where": [{"field": "route", "equals": route}],
        })
        if route == "B":
            links[-1]["where"].append({"field": "subject.name", "exists": True})
        (vault / f"path-{route}.md").write_text(
            yaml.safe_dump({
                "kind": "path", "route": route, "subject": {"name": "Shared source"},
                "obsHtml": {"document": False},
                "internal": [{"storage": route}],
            }).join(["---\n", "---\n"]) + "Path paragraph.\n", encoding="utf-8",
        )
    graph = {"version": 1, "nodes": nodes, "links": links,
             "data": {"where": [{"field": "kind", "equals": "path"}]}}
    (vault / "graph.json").write_text(json.dumps(graph), encoding="utf-8")
    (vault / "flow.md").write_text(
        "# Flow\n\nA prose paragraph. [[path-A.1.md|Projection reference]]\n\n"
        "```figure\nversion: 1\nkind: sankey\n"
        "source: graph.json\nalt: Path graph\n```\n", encoding="utf-8",
    )
    (vault / "results.md").write_text(
        "# Results\n\nResults paragraph.\n\nSecond results paragraph.\n\n"
        "```base\nfilters: 'kind == \"path\"'\nviews:\n"
        "  - type: table\n    order: [route, subject.name]\n```\n", encoding="utf-8",
    )
    artifact = tmp_path / "artifact.html"
    args = ["--source", str(vault), "--output", str(artifact)]
    assert main([*args, "--check"]) == 0
    assert not artifact.exists()
    assert main(args) == 0
    return artifact, vault


@pytest.fixture
def parity_browser(parity_artifact):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native filter/navigation checks.")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        page.set_default_timeout(5000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(parity_artifact[0].as_uri() + "#flow")
        page.evaluate("obsPages.setPaged(false)")
        try:
            yield page, parity_artifact
            assert errors == []
        finally:
            browser.close()


def test_native_sankey_selection_is_exact_visible_editable_and_clearable(parity_browser, tmp_path):
    from playwright.sync_api import expect
    page, _ = parity_browser
    graph = page.locator("[data-active-chapter] .sankey-canvas")
    expect(graph.locator(".sankey-node")).to_have_count(4)
    geometry = graph.locator(".sankey-node").evaluate_all("""nodes=>Object.fromEntries(nodes.map(node=>{
        const r=node.querySelector('rect');return [node.dataset.nodeId,
        Object.fromEntries(['x','y','width','height'].map(key=>[key,Number(r.getAttribute(key))]))]}))""")
    assert geometry["stop"]["width"] > geometry["stop"]["height"]
    assert geometry["down"]["width"] > geometry["down"]["height"]
    assert geometry["stop"]["y"] < geometry["in"]["y"]
    assert geometry["down"]["y"] > geometry["in"]["y"] + geometry["in"]["height"]
    graph.locator('[data-node-id="out"]').click()
    input_box = page.locator("[data-filter-input]")
    expect(input_box).to_be_visible()
    expression = input_box.input_value()
    assert "route:" in expression and "OR" in expression
    assert page.evaluate(
        "obsArtifact.records.filter(obsArtifact.matchesFilter).filter(r=>r.fields.kind?.includes('path')).length"
    ) == 2
    expect(graph.locator(".sankey-node")).to_have_count(2)
    assert page.evaluate("obsArtifact.exportChapters().map(r=>r.slug)") == ["flow", "results"]
    fields = page.locator(".filter-field-button").evaluate_all(
        "buttons => buttons.map(button => button.firstChild.nodeValue)")
    assert fields == ["Route"]  # constant Subject is not discriminative
    graph.locator('.sankey-link[data-series="A.1"]').focus()
    page.keyboard.press("Enter")
    expression = input_box.input_value()
    assert page.evaluate(
        "obsArtifact.records.filter(obsArtifact.matchesFilter).filter(r=>r.fields.kind?.includes('path'))"
        ".map(r=>r.frontmatter.route)"
    ) == ["A.1"]
    token = page.locator("[data-filter-warning]")
    expect(token).to_be_visible()
    expect(token).to_contain_text("Filtered view")
    expect(token).to_contain_text("2/2 chapters")
    expect(token).to_contain_text("3/3 paragraphs")
    expect(token).to_contain_text("1/4 records")
    page.evaluate("obsArtifact.activateChapter('results')")
    expect(page.locator("[data-chapter-body] tbody tr[data-row-key]")).to_have_count(1)
    page.locator('[data-step="-1"]').click()
    expect(page.locator("[data-active-chapter]")).to_have_attribute("data-chapter", "flow")
    input_box.fill("route: /[")
    expect(token).to_contain_text("1/4 records")
    saved = tmp_path / "reviewed.html"
    saved.write_text(page.evaluate("obsComments.reviewedHtml()"), encoding="utf-8")
    page.goto(saved.as_uri() + "#flow")
    page.evaluate("obsPages.setPaged(false)")
    expect(input_box).to_have_value(expression)
    expect(token).to_contain_text("1/4 records")
    token.get_by_role("button", name="Clear filter").click()
    expect(input_box).to_have_value("")
    expect(token).to_be_hidden()
    expect(graph.locator(".sankey-node")).to_have_count(4)
    input_box.fill("route: /nothing/")
    expect(graph.locator(".sankey-node")).to_have_count(0)
    expect(graph).to_contain_text("No matching records")
    expect(token).to_contain_text("0/4 records")
    token.get_by_role("button", name="Clear filter").click()
    expect(graph.locator(".sankey-node")).to_have_count(4)


def test_native_default_chapter_filter_keeps_home_navigation(parity_artifact, parity_browser, tmp_path):
    from playwright.sync_api import expect
    page, (artifact, vault) = parity_browser
    (vault / "cfg.json").write_text('{"schemaVersion":1}', encoding="utf-8")
    (vault / "manifest.md").write_text("- [[flow]]\n- [[results]]\n", encoding="utf-8")
    chapter_artifact = tmp_path / "chapter-artifact.html"
    assert main(["--source", str(vault), "--output", str(chapter_artifact)]) == 0
    page.goto(chapter_artifact.as_uri() + "#flow")
    page.evaluate("obsPages.setPaged(false); obsFilter.setExpression('title: /^Results$/')")
    expect(page.locator("[data-active-chapter]")).to_have_attribute("data-chapter", "home")
    assert page.url.endswith("#home")
    expect(page.locator("[data-filter-warning]")).to_contain_text("1/2 chapters")
    expect(page.locator("[data-filter-warning]")).to_contain_text("2/3 paragraphs")
    page.locator('[data-step="1"]').click()
    expect(page.locator("[data-active-chapter]")).to_have_attribute("data-chapter", "results")
    assert page.locator('.chapter-breadcrumb-menu a[href="#flow"]').evaluate("(link)=>link.hidden")
    page.locator('[aria-label="Clear filter"]').click()
    assert not page.locator('.chapter-breadcrumb-menu a[href="#flow"]').evaluate("(link)=>link.hidden")
    page.evaluate("obsFilter.setExpression('title: /^Results$/')")
    assert page.locator('.chapter-breadcrumb-menu a[href="#flow"]').evaluate("(link)=>link.hidden")
    page.locator('[data-step="-1"]').click()
    expect(page.locator("[data-active-chapter]")).to_have_attribute("data-chapter", "home")
    page.evaluate("obsArtifact.openBar('toc')")
    assert page.locator('[data-toc-link="home"]').count() == 0
    page.evaluate("obsFilter.setExpression('title: /^Absent$/')")
    assert page.evaluate("obsArtifact.exportChapters().length") == 0
    expect(page.locator("[data-active-chapter]")).to_have_attribute("data-chapter", "home")
    assert page.locator('[data-step="-1"]').is_disabled()
    assert page.locator('[data-step="1"]').is_disabled()
    page.evaluate("obsPages.setPaged(true)")
    assert page.locator('.page-contents a[href="#home"]').count() == 0
    assert page.locator('.page-contents a[href="#results"]').count() == 0


def test_native_canonical_reference_alias_union_facets_and_edits(parity_artifact, parity_browser, tmp_path):
    from playwright.sync_api import expect
    page, (_, vault) = parity_browser
    query = {
        **QUERY,
        "fields": [{"field": "discipline", "source": [
            "roles.origin.disciplines", "roles.target.disciplines",
        ], "label": "Discipline"}],
    }
    manifest = vault / "manifest.md"
    manifest.write_text(_manifest(query, manifest.read_text(encoding="utf-8").split("---\n", 2)[2]),
                        encoding="utf-8")
    (vault / "cfg.json").write_text(json.dumps({"artifact": {}}), encoding="utf-8")
    for role, discipline in [("origin", "Design"), ("target", "Safety")]:
        (vault / f"{role}.md").write_text(
            f"---\nkind: subject\ndisciplines: [{discipline}]\n---\n", encoding="utf-8",
        )
    for path in vault.glob("path-*.md"):
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("kind: path", "kind: path\nroles:\n"
            "  origin: '[[origin]]'\n  target: ['[[target]]']"), encoding="utf-8")
    artifact = tmp_path / "references.html"
    assert main(["--source", str(vault), "--output", str(artifact)]) == 0
    page.goto(artifact.as_uri() + "#flow")
    page.evaluate("obsPages.setPaged(false); obsArtifact.openBar('filter')")
    assert page.locator(".filter-field-button").evaluate_all(
        "buttons => buttons.map(button => button.firstChild.nodeValue)") == ["Discipline"]
    assert page.evaluate(
        "obsArtifact.records.find(r=>r.frontmatter.kind==='path').fields.discipline"
    ) == ["Design", "Safety"]
    page.locator(".filter-field-button").click()
    page.locator('[role="menuitemcheckbox"][data-filter-value="Safety"]').click()
    expect(page.locator("[data-filter-warning]")).to_contain_text("4/4 records")
    assert "discipline:" in page.locator("[data-filter-input]").input_value()
    page.evaluate("""obsArtifact.commitCanonicalProjection([{
        slug:'target',fields:{disciplines:['Assurance']}
    }])""")
    expect(page.locator("[data-filter-warning]")).to_contain_text("0/4 records")
    expect(page.locator("[data-filter-status]")).to_have_text("0/4 records.")
    assert page.evaluate(
        "obsArtifact.records.find(r=>r.frontmatter.kind==='path').fields.discipline"
    ) == ["Design", "Assurance"]
    assert page.locator(".filter-value span").all_text_contents() == ["Assurance", "Design"]
    page.evaluate("obsFilter.setExpression('discipline: /^Assurance$/')")
    expect(page.locator("[data-filter-warning]")).to_contain_text("4/4 records")
    state = json.loads(page.evaluate("obsArtifact.serializeModel()"))
    assert all("discipline" not in note["frontmatter"]
               for note in state["notes"] if note["frontmatter"].get("kind") == "path")


@pytest.mark.parametrize("width", [320, 390, 1440])
def test_native_filter_warning_counts_do_not_depend_on_clones_or_overlap_controls(parity_browser, width):
    from playwright.sync_api import expect
    page, _ = parity_browser
    page.set_viewport_size({"width": width, "height": 900})
    page.evaluate("obsFilter.selectExpression('route: /^A\\\\.1$/')")
    token = page.locator("[data-filter-warning]")
    expect(token).to_contain_text("3/3 paragraphs")
    warning = token.evaluate(
        "item=>{const r=item.getBoundingClientRect();return "
        "{left:r.left,right:r.right,top:r.top,bottom:r.bottom}}"
    )
    boxes = page.locator(
        "[data-menu-button], [data-step], [data-filter-input], .chapter-breadcrumbs",
    ).evaluate_all(
        "(items)=>items.map(item=>{const r=item.getBoundingClientRect();return "
        "{left:r.left,right:r.right,top:r.top,bottom:r.bottom}})"
    )
    for other in boxes:
        assert warning["right"] <= other["left"] or warning["left"] >= other["right"] or \
            warning["bottom"] <= other["top"] or warning["top"] >= other["bottom"]
    assert warning["left"] >= 0 and warning["right"] <= width
    page.screenshot(path=str(parity_browser[1][0].parent / f"filter-warning-{width}.png"))
    page.locator("[data-menu-button]").click()
    menu = page.locator("[data-bars-menu]").bounding_box()
    assert menu["y"] >= warning["bottom"]
    page.keyboard.press("Escape")
    page.evaluate("obsPages.setPaged(true); obsPages.setPaged(false)")
    expect(token).to_contain_text("3/3 paragraphs")


def test_native_facet_selection_uses_applied_query_not_invalid_draft(parity_browser):
    from playwright.sync_api import expect
    page, _ = parity_browser
    page.evaluate("obsFilter.selectExpression('route: /^A\\\\.1$/')")
    input_box = page.locator("[data-filter-input]")
    input_box.fill("route: /[")
    page.get_by_role("button", name="Route; 4 unique values").click()
    page.locator('[role="menuitemcheckbox"][data-filter-value="B"]').click()
    assert "/[" not in input_box.input_value()
    assert page.evaluate("obsQuery.compile(document.querySelector('[data-filter-input]').value).empty") is False
    expect(page.locator("[data-filter-warning]")).to_contain_text("0/4 records")
    page.get_by_role("button", name="Remove route: B").click()
    expect(page.locator("[data-filter-warning]")).to_contain_text("1/4 records")


def test_native_programmatic_filter_updates_the_same_editable_owner_but_reapply_retains_draft(parity_browser):
    from playwright.sync_api import expect
    page, _ = parity_browser
    source = "route: /^A\\.1$/"
    page.evaluate("source=>obsArtifact.setFilter(obsQuery.compile(source))", source)
    input_box = page.locator("[data-filter-input]")
    expect(input_box).to_be_visible()
    expect(input_box).to_have_value(source)
    input_box.fill("route: /[")
    page.evaluate("source=>obsArtifact.setFilter(obsQuery.compile(source))", source)
    expect(input_box).to_have_value("route: /[")
    expect(page.locator("[data-filter-warning]")).to_contain_text("1/4 records")
    page.evaluate("obsArtifact.setFilter(obsQuery.compile('route: /^B$/'))")
    expect(input_box).to_have_value("route: /^B$/")
    expect(page.locator("[data-filter-status]")).to_have_text("1/4 records.")


def test_native_record_filter_print_preserves_chapters_and_projects_figures_tables(parity_browser, tmp_path):
    from playwright.sync_api import expect
    page, _ = parity_browser
    page.evaluate("obsFilter.selectExpression('route: /^A\\\\.1$/')")
    page.evaluate("window.print=()=>{}; obsPages.exportPDF()")
    book = page.locator(".print-book")
    expect(book.locator('[data-page-chapter="flow"] .sankey-node')).to_have_count(2)
    expect(book.locator('[data-page-chapter="results"] tbody tr[data-row-key]')).to_have_count(1)
    assert book.locator('.page-contents [data-contents-chapter="home"]').count() == 0
    for slug in ["flow", "results"]:
        assert book.locator(f'.page-contents [data-contents-chapter="{slug}"]').count() == 1
    pdf = tmp_path / "filtered.pdf"
    assert page.pdf(path=str(pdf), prefer_css_page_size=True).startswith(b"%PDF")
    assert pdf.stat().st_size > 1000


def test_native_pointer_strand_and_existence_node_selection_use_ordinary_query(parity_browser):
    from playwright.sync_api import expect
    page, _ = parity_browser
    graph = page.locator("[data-active-chapter] .sankey-canvas")
    # Click near the strand's origin; its bounding-box centre lies where other strands cross.
    strand = graph.locator('.sankey-link[data-series="A.1"]')
    strand.scroll_into_view_if_needed()
    origin = strand.evaluate("""path => {
        const point = path.getPointAtLength(path.getTotalLength() * 0.05);
        const screen = new DOMPoint(point.x, point.y).matrixTransform(path.getScreenCTM());
        return {x: screen.x, y: screen.y, hit: document.elementFromPoint(screen.x, screen.y) === path};
    }""")
    assert origin["hit"]
    page.mouse.click(origin["x"], origin["y"])
    expect(page.locator("[data-filter-warning]")).to_contain_text("1/4 records")
    page.locator('[aria-label="Clear filter"]').click()
    graph.locator('[data-node-id="stop"]').click()
    expression = page.locator("[data-filter-input]").input_value()
    assert "subject.name" in expression and r"/\S/" in expression
    assert page.evaluate(
        "obsArtifact.records.filter(obsArtifact.matchesFilter).filter(r=>r.frontmatter.kind==='path')"
        ".map(r=>r.frontmatter.route)"
    ) == ["B"]


def test_native_record_only_notes_stay_queryable_without_document_search_or_navigation(parity_browser):
    from playwright.sync_api import expect
    page, (artifact, _) = parity_browser
    page.evaluate("obsArtifact.openBar('search')")
    page.locator("[data-search-input]").fill('"Path paragraph"')
    expect(page.locator("[data-search-status]")).to_have_text("0 results.")
    assert page.evaluate("obsArtifact.documentRecords().map(r=>r.slug)") == ["home", "flow", "results"]
    assert page.evaluate("obsArtifact.records.filter(r=>r.frontmatter.kind==='path').length") == 4
    page.evaluate("obsArtifact.activateChapter('results')")
    expect(page.locator("[data-chapter-body] .data-table-tree-toggle")).to_have_count(0)
    page.evaluate("obsArtifact.activateChapter('flow')")
    page.evaluate("obsArtifact.openBar('search')")
    link = page.get_by_role("link", name="Projection reference", exact=True)
    # A record-only note has a hover card and opens as context, never as a page
    # (input-model.md "Reference notes and link text").
    link.hover()
    expect(page.locator("#hover-card .hover-card-title")).to_be_visible()
    page.keyboard.press("Escape")
    chapter = page.locator("[data-active-chapter]").get_attribute("data-chapter")
    page.evaluate("delete window.documentPictureInPicture; window.open = () => null")
    link.click()
    expect(page.locator("[data-guided-card] [data-guided-card-use]")).to_have_text("Context")
    expect(page.locator("[data-active-chapter]")).to_have_attribute("data-chapter", chapter)
    page.locator("[data-guided-card] [data-guided-card-close]").click()
    slug = page.evaluate("obsArtifact.records.find(r=>r.frontmatter.kind==='path').slug")
    page.evaluate("slug=>obsArtifact.activateChapter(slug)", slug)
    expect(page.locator("[data-active-chapter]")).to_have_attribute("data-chapter", "home")
    page.goto(artifact.as_uri() + "#" + slug)
    expect(page.locator("[data-active-chapter]")).to_have_attribute("data-chapter", "home")
