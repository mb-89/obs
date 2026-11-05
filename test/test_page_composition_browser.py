"""Small native proofs of explicit columns and mixed physical paper boxes."""
from io import BytesIO
import json
import os
import re

import pytest

from obs_html.content import parse_manifest
from obs_html.renderer import render_artifact
from obs_html.artifact_data import decode_artifact_data, encode_artifact_data


@pytest.fixture(scope="module")
def composition_browser():
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for native page composition checks.")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        try:
            yield browser
        finally:
            browser.close()


def _artifact(tmp_path, *, wide=False, print_profile="", wrapper=False):
    cards = {"version": 1, "cards": [{
        "title": "Coverage", "body": "See [[chapter#Matrix]].", "metrics": [
            {"label": label, "where": []} for label in ["All items", "Much longer item label", "Ready"]
        ],
    }]}
    evidence = {"version": 1, "cards": [{
        "title": "Evidence", "body": "Canonical evidence.\n\n| Item | Status |\n|---|---|\n| E1 | Ready |",
    }]}
    manifest = tmp_path / "manifest.md"
    manifest.write_text(
        (f"---\nobsHtml: {{print: {print_profile}}}\n---\n" if print_profile else "")
        + "- [[chapter]]\n\n||| 1:2\n```cards\n" + json.dumps(cards)
        + "\n```\n|||\n```cards\n" + json.dumps(evidence) + "\n```\n|||\n",
        encoding="utf-8",
    )
    (tmp_path / "chapter.md").write_text(
        "---\nbottom line: Compact overview.\n---\n"
        "# Chapter\n\nPORTRAIT-BEFORE\n\n## Matrix\n\n"
        "| ID | Title | Evidence | Status |\n|---|---|---|---|\n"
        + "\n".join(
            f"| ID-{index:03d} | Visible title {index:03d} | Evidence {index:03d} | Ready |"
            for index in range(90)
        )
        + "\n\n## After matrix\n\nPORTRAIT-AFTER\n",
        encoding="utf-8",
    )
    html = render_artifact(manifest, parse_manifest(manifest))
    if wide:
        # Supply the table owner's rendered hint at the consumer boundary. The
        # input/schema producer has its own tests in the table-owner work package.
        match = re.search(r'(<script id="artifact-data"[^>]*>)(.*?)(</script>)', html, re.S)
        data = decode_artifact_data(html)
        record = next(note for note in data["notes"] if note["slug"] == "chapter")
        if wrapper:
            record["html"] = record["html"].replace(
                "<table>", '<section class="table-figure" data-table-wide="true">'
                '<div class="table-caption">Canonical matrix caption</div><table>', 1,
            ).replace("</table>", "</table></section>", 1)
        else:
            record["html"] = record["html"].replace("<table>", '<table data-table-wide="true">', 1)
        html = html[:match.start()] + encode_artifact_data(data, "gzip") + html[match.end():]
    output = tmp_path / "artifact.html"
    output.write_text(html, encoding="utf-8")
    return output


def test_native_explicit_columns_align_metrics_in_pages_and_stack_on_mobile(
    tmp_path, composition_browser,
):
    page = composition_browser.new_page(viewport={"width": 1600, "height": 1000})
    try:
        page.goto(_artifact(tmp_path).as_uri())
        columns = page.locator(".paged-reader .markdown-columns")
        assert columns.count() == 1
        positions = columns.locator(":scope > .markdown-column").evaluate_all(
            "nodes => nodes.map(node => node.getBoundingClientRect().toJSON())",
        )
        assert positions[0]["top"] == pytest.approx(positions[1]["top"], abs=1)
        assert positions[0]["right"] < positions[1]["left"]
        assert positions[0]["width"] < positions[1]["width"]
        assert columns.locator(".record-metric").evaluate_all(
            "nodes => nodes.every(node => node.scrollWidth <= node.clientWidth + 1)",
        )
        assert columns.locator(".record-metrics").bounding_box()["height"] < 100
        assert page.locator('.paged-reader [data-page-chapter="@abstract"]').count() == 1
        assert columns.locator('a[href="#chapter/matrix"]').count() == 1
        for paged in (True, False):
            page.set_viewport_size({"width": 390, "height": 844})
            page.evaluate("enabled => obsPages.setPaged(enabled)", paged)
            columns = page.locator("[data-active-chapter] .markdown-columns")
            positions = columns.locator(":scope > .markdown-column").evaluate_all(
                "nodes => nodes.map(node => node.getBoundingClientRect().toJSON())",
            )
            assert positions[1]["top"] >= positions[0]["bottom"]
            assert page.locator(".chapter-scroll").evaluate(
                "node => node.scrollWidth <= node.clientWidth + 1",
            )
        assert page.locator("[data-export-status]").is_hidden()
    finally:
        page.close()


@pytest.mark.parametrize("width", [1600, 390])
def test_native_pdf_destination_hint_is_compact_accessible_and_print_excluded(
    tmp_path, composition_browser, width,
):
    from pypdf import PdfReader

    page = composition_browser.new_page(viewport={"width": width, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(_artifact(tmp_path).as_uri())
        page.evaluate("obsArtifact.openBar('settings', 'right')")
        button = page.locator("[data-export-pdf]")
        hint = page.get_by_text("Choose Save as PDF, not Microsoft Print to PDF.", exact=True)
        assert hint.count() == 1
        assert hint.is_visible()
        assert button.get_attribute("aria-describedby") == hint.get_attribute("id")
        assert hint.evaluate("""node => {
            const button = node.previousElementSibling;
            return button.matches('[data-export-pdf]') &&
                button.parentElement.matches('.settings-page-export') &&
                !node.closest('.content-card, [role="dialog"], [role="alert"]');
        }""")
        bounds = hint.bounding_box()
        action = button.bounding_box()
        assert bounds["y"] >= action["y"] + action["height"] - 1
        assert bounds["x"] == pytest.approx(action["x"], abs=1)
        assert bounds["x"] + bounds["width"] <= action["x"] + action["width"] + 1
        assert hint.evaluate("node => node.scrollWidth <= node.clientWidth + 1")
        page.evaluate("window.print = () => { globalThis.pdfHintPrintCalls = 1; }")
        button.click()
        page.wait_for_function("globalThis.pdfHintPrintCalls === 1")
        assert page.locator(".print-book").get_by_text(
            "Choose Save as PDF, not Microsoft Print to PDF.", exact=True,
        ).count() == 0
        page.emulate_media(media="print")
        assert hint.is_hidden()
        pdf = PdfReader(BytesIO(page.pdf(prefer_css_page_size=True, print_background=True)))
        assert "Microsoft Print to PDF" not in "\n".join(p.extract_text() for p in pdf.pages)
        assert errors == []
    finally:
        page.close()


def test_native_home_sections_follow_authored_headings_without_implicit_pages(
    tmp_path, composition_browser,
):
    manifest = tmp_path / "manifest.md"
    (tmp_path / "chapter.md").write_text("# Chapter\n", encoding="utf-8")
    manifest.write_text(
        "- [[chapter]]\n\nOpening prose.\n\n## Decisions\n\nRetained decision.\n\n"
        "## Other evidence\n\nRetained evidence.\n", encoding="utf-8",
    )
    output = tmp_path / "artifact.html"
    output.write_text(render_artifact(manifest, parse_manifest(manifest)), encoding="utf-8")
    page = composition_browser.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(output.as_uri())
        page.wait_for_function("document.documentElement.dataset.artifactStatus === 'ready'")
        assert page.locator(".paged-reader .paper-sheet").evaluate_all(
            "nodes => nodes.map(node => node.dataset.pageChapter)"
        ) == ["home", "@abstract", "@decisions", "@other-evidence", "@contents"]
        assert page.locator(".paged-reader [data-page-chapter='@decisions']").inner_text().count(
            "Retained decision."
        ) == 1
        assert page.locator("[data-export-status]").is_hidden()
        assert errors == []
    finally:
        page.close()


def test_native_compact_heading_opens_the_only_page_of_a_home_only_document(
    tmp_path, composition_browser,
):
    manifest = tmp_path / "manifest.md"
    manifest.write_text(
        "---\ntitle: Summary\norganization: Org\nproduct: {name: Product}\ndocument type: Artifact\n"
        "obsHtml: {heading: compact, pages: [{page: abstract}]}\n---\n"
        "| Item | Status |\n|---|---|\n"
        + "\n".join(f"| ROW-{index:03d} | Ready |" for index in range(80)) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "artifact.html"
    output.write_text(render_artifact(manifest, parse_manifest(manifest)), encoding="utf-8")
    page = composition_browser.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(output.as_uri())
        page.wait_for_function("document.documentElement.dataset.artifactStatus === 'ready'")
        assert page.locator("[data-step]").evaluate_all("nodes => nodes.every(node => node.disabled)")
        for view in (".paged-reader", ".print-book"):
            if view == ".print-book":
                page.evaluate("window.print = () => {}; obsPages.exportPDF()")
                page.wait_for_function("document.querySelector('.print-book .paper-sheet')")
            sheets = page.locator(f"{view} .paper-sheet")
            assert set(sheets.evaluate_all("nodes => nodes.map(node => node.dataset.pageChapter)")) == {
                "@abstract"}
            assert page.locator(f"{view} .title-page, {view} .cover-frame").count() == 0
            first = sheets.first.locator(".paper-content")
            assert first.evaluate(
                "node => node.querySelector('.document-heading--compact') === "
                "node.querySelector('.document-heading--compact, table')"
            )
            assert first.locator(".compact-heading").inner_text().split("\n") == [
                "Org", "Product", "Artifact", "Summary"]
            assert first.locator("tbody tr").count() > 0
            assert page.locator(f"{view} .document-heading").count() == 1
        assert page.locator(".print-book .paper-sheet").count() > 1
        assert page.locator(".print-book tbody tr").count() == 80
        assert errors == []
    finally:
        page.close()


@pytest.mark.parametrize("print_profile,paper,wrapper", [
    ("", {"widthMillimeters": 210, "heightMillimeters": 297, "marginMillimeters": 20}, False),
    ("{paper: Letter, margin: 14mm}",
     {"widthMillimeters": 215.9, "heightMillimeters": 279.4, "marginMillimeters": 14}, True),
])
def test_native_wide_table_continuations_and_real_mixed_pdf_boxes(
    tmp_path, composition_browser, print_profile, paper, wrapper,
):
    from pypdf import PdfReader

    page = composition_browser.new_page(viewport={"width": 1600, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(_artifact(tmp_path, wide=True, print_profile=print_profile, wrapper=wrapper).as_uri() + "#chapter")
        tables = page.locator(".paged-reader [data-table-wide='true']")
        assert tables.count() > 1
        assert tables.evaluate_all("""nodes => nodes.every(node =>
            node.closest('.paper-sheet').dataset.pageOrientation === 'landscape' &&
            node.querySelectorAll('thead th').length === 4 &&
            node.querySelector('tbody tr'))""")
        assert page.locator(".paged-reader p").filter(has_text="PORTRAIT-BEFORE").evaluate(
            "node => node.closest('.paper-sheet').dataset.pageOrientation",
        ) == "portrait"
        assert page.locator(".paged-reader p").filter(has_text="PORTRAIT-AFTER").evaluate(
            "node => node.closest('.paper-sheet').dataset.pageOrientation",
        ) == "portrait"
        page.evaluate("window.print = () => {}; obsPages.exportPDF()")
        page.emulate_media(media="print")
        sheets = page.locator(".print-book .paper-sheet").evaluate_all("""nodes => nodes.map(node => ({
            orientation: node.dataset.pageOrientation,
            width: node.getBoundingClientRect().width, height: node.getBoundingClientRect().height,
            fits: node.scrollWidth <= node.clientWidth + 1 &&
                node.querySelector('.paper-content').scrollHeight <=
                node.querySelector('.paper-content').clientHeight + 1,
        }))""")
        assert all(sheet["fits"] for sheet in sheets)
        assert page.locator(".print-book [data-table-wide='true']").count() > 1
        assert page.locator(".print-book [data-table-wide='true']").evaluate_all("""nodes =>
            nodes.every(node => node.querySelectorAll('thead th').length === 4 &&
                node.querySelector('tbody tr') &&
                [...node.querySelectorAll('th,td')].every(cell => {
                    const box = cell.getBoundingClientRect();
                    const area = cell.closest('.paper-content').getBoundingClientRect();
                    return box.left >= area.left - 1 && box.right <= area.right + 1;
                }))""")
        assert page.locator(".print-book h2").filter(has_text=re.compile("^Matrix$")).evaluate(
            "node => node.closest('.paper-sheet').querySelector('[data-table-wide] tbody tr') !== null",
        )
        if wrapper:
            assert page.locator(".print-book .table-caption").evaluate(
                "node => node.closest('.paper-sheet').querySelector('[data-table-wide] tbody tr') !== null",
            )
        pdf_bytes = page.pdf(prefer_css_page_size=True, print_background=True)
        (tmp_path / "mixed-orientation.pdf").write_bytes(pdf_bytes)
        pdf = PdfReader(BytesIO(pdf_bytes))
        assert len(pdf.pages) == len(sheets)
        width, height = paper["widthMillimeters"], paper["heightMillimeters"]
        assert page.evaluate("obsPages.printMediaBoxes") == [
            {"widthMillimeters": height if sheet["orientation"] == "landscape" else width,
             "heightMillimeters": width if sheet["orientation"] == "landscape" else height}
            for sheet in sheets
        ]
        landscape = []
        for index, (physical, sheet) in enumerate(zip(pdf.pages, sheets)):
            expected = (height, width) if sheet["orientation"] == "landscape" else (width, height)
            assert float(physical.mediabox.width) == pytest.approx(expected[0] * 72 / 25.4, abs=1)
            assert float(physical.mediabox.height) == pytest.approx(expected[1] * 72 / 25.4, abs=1)
            if expected[0] > expected[1]:
                landscape.append(index)
                assert "ID" in physical.extract_text() and "Title" in physical.extract_text()
                labels = []

                def position(text, cm, tm, _font, size):
                    if "ID-" in text or "Visible title" in text:
                        labels.append((
                            text, tm[4] * cm[0] + tm[5] * cm[2] + cm[4],
                            tm[4] * cm[1] + tm[5] * cm[3] + cm[5],
                            size * abs(cm[0]),
                        ))

                physical.extract_text(visitor_text=position)
                margin = paper["marginMillimeters"] * 72 / 25.4
                assert min(x for text, x, _y, _size in labels if "ID-" in text) == pytest.approx(
                    margin + 5, abs=2,
                )
                assert all(
                    margin <= x <= float(physical.mediabox.width) - margin
                    and margin <= y <= float(physical.mediabox.height) - margin
                    and size >= 8.9
                    for _text, x, y, size in labels
                )
            glyph_scales = []

            def glyph_geometry(text, cm, tm, _font, _size):
                if text.strip():
                    x = (cm[0] * tm[0] + cm[2] * tm[1],
                         cm[1] * tm[0] + cm[3] * tm[1])
                    y = (cm[0] * tm[2] + cm[2] * tm[3],
                         cm[1] * tm[2] + cm[3] * tm[3])
                    glyph_scales.append((sum(v * v for v in x) /
                                         sum(v * v for v in y)) ** 0.5)

            physical.extract_text(visitor_text=glyph_geometry)
            assert glyph_scales and all(
                scale == pytest.approx(1, abs=0.01) for scale in glyph_scales
            ), glyph_scales
        assert len(landscape) > 1
        assert landscape == list(range(min(landscape), max(landscape) + 1))
        assert any("PORTRAIT-BEFORE" in p.extract_text() for p in pdf.pages[:min(landscape)])
        assert any("PORTRAIT-AFTER" in p.extract_text() for p in pdf.pages[max(landscape) + 1:])
        text = "\n".join(p.extract_text() for p in pdf.pages)
        assert all(f"ID-{index:03d}" in text and f"Visible title {index:03d}" in text for index in range(90))
        assert errors == []
    finally:
        page.close()


@pytest.mark.parametrize("paged", [True, False])
def test_native_nested_print_tables_reflow_inside_weighted_cards(
    tmp_path, composition_browser, paged,
):
    definition = {
        "filters": 'kind == "evidence"',
        "obsHtml": {"records": "note"},
        "properties": {
            "label": {"displayName": "Item"},
            "description": {"displayName": "Description"},
            "actions": {"displayName": "Actions", "obsHtml": {"icons": [
                {"name": "snapshot", "label": "Download snapshot", "linkProperty": "snapshot",
                 "unavailable": "No snapshot"},
                {"name": "link", "label": "Open source", "linkProperty": "source",
                 "unavailable": "No source"},
            ]}},
        },
        "views": [{"type": "table", "name": "Evidence", "order": [
            "label", "description", "actions",
        ], "obsHtml": {"pagination": False, "compact": True, "columnSizing": "equal"}}],
    }
    cards = {"version": 1, "cards": [{
        "title": "Evidence", "body": "```base\n" + json.dumps(definition) + "\n```",
    }]}
    manifest = tmp_path / "manifest.md"
    manifest.write_text(
        "- [[chapter]]\n\n||| 3:4\n\nLeft column.\n\n|||\n\n```cards\n"
        + json.dumps(cards) + "\n```\n\n|||\n", encoding="utf-8",
    )
    (tmp_path / "chapter.md").write_text("# Chapter\n\nBody text.", encoding="utf-8")
    (tmp_path / "snapshot.txt").write_text("Included source snapshot.", encoding="utf-8")
    for index in range(7):
        (tmp_path / f"evidence-{index}.md").write_text(
            "---\nkind: evidence\n"
            f"label: ROW-{index}\ndescription: Version {index} plus small updates\n"
            "snapshot: '![Snapshot](snapshot.txt)'\n"
            f"source: https://example.invalid/source-{index}\n---\n",
            encoding="utf-8",
        )
    output = tmp_path / "weighted.html"
    output.write_text(render_artifact(manifest, parse_manifest(manifest), embed_attachments=True),
                      encoding="utf-8")
    page = composition_browser.new_page(viewport={"width": 1600, "height": 1000})
    try:
        page.goto(output.as_uri())
        page.evaluate("enabled => obsPages.setPaged(enabled)", paged)
        page.evaluate("window.print = () => {}; obsPages.exportPDF()")
        page.emulate_media(media="print")
        geometry = page.locator(".print-book .record-card table").evaluate_all("""tables =>
            tables.map(table => {
                const card = table.closest('.record-card').getBoundingClientRect();
                const box = table.getBoundingClientRect();
                return {width: box.width, available: card.width,
                    contained: [...table.querySelectorAll('th,td')].every(cell => {
                        const rect = cell.getBoundingClientRect();
                        return rect.left >= card.left && rect.right <= card.right;
                    }), columns: [...table.querySelectorAll('thead th')].map(cell =>
                        cell.getBoundingClientRect().width)};
            })""")
        assert geometry and all(item["contained"] for item in geometry), geometry
        assert all(item["columns"][0] == pytest.approx(item["columns"][1], abs=1)
                   for item in geometry), geometry
        assert page.locator(".print-book .record-card table a").count() == 14
        pdf_bytes = page.pdf(prefer_css_page_size=True, print_background=True)
        (tmp_path / "weighted.pdf").write_bytes(pdf_bytes)
        from pypdf import PdfReader

        pdf = PdfReader(BytesIO(pdf_bytes))
        text = "\n".join(p.extract_text() for p in pdf.pages)
        assert all(f"ROW-{index}" in text for index in range(7))
        uris = [str(annotation.get_object().get("/A", {}).get("/URI", ""))
                for physical in pdf.pages for annotation in physical.get("/Annots", [])]
        assert all(any(f"weighted.html?#evidence-{index}" in uri for uri in uris)
                   for index in range(7)), uris
    finally:
        page.close()


def test_native_physical_print_glyphs_are_not_squeezed(tmp_path, composition_browser):
    from pypdf import PdfReader

    page = composition_browser.new_page(viewport={"width": 1600, "height": 1000})
    try:
        page.goto(_artifact(tmp_path, wide=True).as_uri())
        page.evaluate("window.print = () => {}; obsPages.exportPDF()")
        page.emulate_media(media="print")
        pdf_bytes = page.pdf(prefer_css_page_size=True, print_background=True)
        (tmp_path / "glyphs.pdf").write_bytes(pdf_bytes)
        ratios = []
        for physical in PdfReader(BytesIO(pdf_bytes)).pages:
            def geometry(text, cm, tm, _font, _size):
                if text.strip():
                    x = (cm[0] * tm[0] + cm[2] * tm[1],
                         cm[1] * tm[0] + cm[3] * tm[1])
                    y = (cm[0] * tm[2] + cm[2] * tm[3],
                         cm[1] * tm[2] + cm[3] * tm[3])
                    ratios.append((sum(v * v for v in x) /
                                   sum(v * v for v in y)) ** 0.5)
            physical.extract_text(visitor_text=geometry)
        assert ratios and all(ratio == pytest.approx(1, abs=0.01) for ratio in ratios), ratios
    finally:
        page.close()


@pytest.mark.parametrize("paged", [True, False])
def test_native_static_findings_preserve_population_values_and_pdf_links(
    tmp_path, composition_browser, paged,
):
    from pypdf import PdfReader

    def physical_pdf(data, companion, items=(2, 3)):
        pdf = PdfReader(BytesIO(data))
        links = [annotation.get_object() for physical in pdf.pages
                 for annotation in physical.get("/Annots", [])
                 if annotation.get_object().get("/Subtype") == "/Link"]
        uris = [str(link.get("/A", {}).get("/URI", "")) for link in links]
        assert any(f"{companion}?#other/details" in uri for uri in uris), uris
        assert all(f"https://example.invalid/item-{index}" in uris for index in items)
        assert "https://example.invalid/source" in uris
        assert any("/Dest" in link for link in links)
        assert all(str(link["/Dest"]) in pdf.named_destinations
                   for link in links if "/Dest" in link)
        assert not any(uri.startswith(("obs-", "blob:", "data:", "javascript:")) for uri in uris)
        return pdf

    definition = {
        "filters": {"and": [
            'kind == "path"', 'findingKey != null', 'findingKey != ""',
        ]},
        "obsHtml": {"records": "note"},
        "properties": {
            "subject": {"displayName": "ID + title", "obsHtml": {
                "reference": {"label": ["item.id", "title"], "linkProperty": "item.url"},
                "detail": True,
            }},
            "explanation": {"displayName": "Explanation", "obsHtml": {
                "editable": True, "editor": "singleLine",
            }},
        },
        "views": [{"type": "table", "name": "Findings", "order": ["subject", "explanation"]}],
    }
    manifest = tmp_path / "manifest.md"
    manifest.write_text("---\n" + json.dumps({"obsHtml": {"query": {
        "scope": "records", "where": [{"field": "kind", "equals": "path"}],
        "fields": [{"field": "explanation"}],
    }}}) + "\n---\n- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "chapter.md").write_text(
        "# Chapter\n\n## Findings\n\n```base\n" + json.dumps(definition) + "\n```\n"
        "\n| Internal | Companion | Source |\n|---|---|---|\n"
        "| [[chapter#Findings]] | [[other#Details]] | [Source](https://example.invalid/source) |\n",
        encoding="utf-8",
    )
    (tmp_path / "other.md").write_text("# Other\n\n## Details\n\nPrivate note.", encoding="utf-8")
    for index, key in enumerate(["", None, "MATCH-2", "MATCH-3"]):
        (tmp_path / f"path-{index}.md").write_text(
            "---\n" + json.dumps({
                "kind": "path", "findingKey": key, "subject": f"[[subject-{index}]]",
                "explanation": f"Explanation {index}",
            }) + "\n---\n", encoding="utf-8",
        )
        (tmp_path / f"subject-{index}.md").write_text(
            "---\n" + json.dumps({
                "title": f"Subject title {index}",
                "item": {"id": f"ITEM-{index}", "url": f"https://example.invalid/item-{index}"},
            }) + "\n---\n", encoding="utf-8",
        )
    output = tmp_path / "findings.html"
    output.write_text(render_artifact(manifest, parse_manifest(manifest)), encoding="utf-8")
    page = composition_browser.new_page(viewport={"width": 1600, "height": 1000})
    page.add_init_script("delete window.showSaveFilePicker")
    try:
        page.goto(output.as_uri())
        page.evaluate("enabled => obsPages.setPaged(enabled)", paged)
        page.evaluate("window.print = () => {}; obsPages.exportPDF()")
        rows = page.locator('.print-book [data-review-table="chapter-base-1"] tr[data-row-key]')
        assert rows.count() == 2, rows.all_text_contents()
        assert rows.all_text_contents() == [
            "ITEM-2 — Subject title 2Explanation 2",
            "ITEM-3 — Subject title 3Explanation 3",
        ]
        page.emulate_media(media="print")
        pdf_bytes = page.pdf(prefer_css_page_size=True, print_background=True)
        (tmp_path / "findings.pdf").write_bytes(pdf_bytes)
        pdf = physical_pdf(pdf_bytes, "findings.html")
        text = "\n".join(p.extract_text() for p in pdf.pages)
        assert "Explanation 2" in text and "Explanation 3" in text
        assert "Explanation 0" not in text and "Explanation 1" not in text
        page.emulate_media(media="screen")
        page.evaluate("""() => obsArtifact.commitCanonicalProjection([
            {slug: 'path-3', fields: {explanation: 'UPDATED explanation 3'}},
        ])""")
        assert page.evaluate("""async () => {
            const first = obsPages.exportPDF();
            const second = obsPages.exportPDF();
            await first;
            return first === second;
        }""")
        assert rows.all_text_contents() == [
            "ITEM-2 — Subject title 2Explanation 2",
            "ITEM-3 — Subject title 3UPDATED explanation 3",
        ]
        page.emulate_media(media="print")
        changed_pdf = page.pdf(prefer_css_page_size=True, print_background=True)
        (tmp_path / "findings-edited.pdf").write_bytes(changed_pdf)
        changed_text = "\n".join(
            p.extract_text() for p in physical_pdf(changed_pdf, "findings.html").pages
        )
        assert "UPDATED explanation 3" in changed_text
        page.emulate_media(media="screen")
        page.evaluate("obsArtifact.setFilter(obsQuery.compile('explanation: UPDATED'))")
        page.evaluate("obsPages.exportPDF()")
        assert rows.count() == 1
        page.emulate_media(media="print")
        filtered = page.pdf(prefer_css_page_size=True, print_background=True)
        (tmp_path / "findings-filtered.pdf").write_bytes(filtered)
        filtered_text = "\n".join(
            p.extract_text() for p in physical_pdf(filtered, "findings.html", (3,)).pages
        )
        assert "UPDATED explanation 3" in filtered_text and "Explanation 2" not in filtered_text
        page.emulate_media(media="screen")
        page.evaluate("obsArtifact.setFilter(obsQuery.compile(''))")
        page.evaluate("obsArtifact.openBar('comments')")
        with page.expect_download() as download:
            page.locator("[data-comment-save]").click()
        saved = tmp_path / "reviewed.html"
        download.value.save_as(saved)
        page.goto(saved.as_uri())
        page.evaluate("window.print = () => {}; obsPages.exportPDF()")
        assert rows.all_text_contents() == [
            "ITEM-2 — Subject title 2Explanation 2",
            "ITEM-3 — Subject title 3UPDATED explanation 3",
        ]
        page.emulate_media(media="print")
        reopened = page.pdf(prefer_css_page_size=True, print_background=True)
        (tmp_path / "findings-reopened.pdf").write_bytes(reopened)
        assert "UPDATED explanation 3" in "\n".join(
            p.extract_text() for p in physical_pdf(reopened, "reviewed.html").pages
        )
    finally:
        page.close()


def test_live_wide_rows_keep_identity_and_recompose_after_owner_mutation(tmp_path, composition_browser):
    page = composition_browser.new_page(viewport={"width": 1600, "height": 1000})
    try:
        page.goto(_artifact(tmp_path, wide=True).as_uri() + "#chapter")
        assert page.locator(".paged-reader [data-table-wide='true']").count() > 1
        page.evaluate("""() => {
            const table = document.querySelector('.paged-reader [data-table-wide]');
            window.originalTable = table;
            window.originalRow = table.querySelector('tbody tr');
            window.rowClicks = 0;
            originalRow.addEventListener('click', () => rowClicks++);
            // Exercise the table adapter's synchronous lifecycle contract.
            table.dispatchEvent(new CustomEvent('obs-table-before-change', {bubbles: true}));
            const rows = [...table.querySelectorAll('tbody tr')];
            rows.slice(5).forEach(row => row.remove());
            table.dispatchEvent(new CustomEvent('obs-table-change', {bubbles: true}));
        }""")
        assert page.locator(".paged-reader [data-table-wide] tbody tr").count() == 5
        assert page.locator(".paged-reader [data-table-wide]").count() == 1
        assert page.evaluate(
            "originalTable === document.querySelector('.paged-reader [data-table-wide]')",
        )
        page.locator(".paged-reader [data-table-wide] tbody tr").first.click()
        assert page.evaluate("rowClicks") == 1
        page.evaluate("obsPages.setPaged(false); obsPages.setPaged(true)")
        assert page.locator(".paged-reader [data-table-wide] tbody tr").count() == 5
        assert page.evaluate(
            "originalRow === document.querySelector('.paged-reader [data-table-wide] tbody tr')",
        )
        page.evaluate("""() => {
            originalTable.dispatchEvent(new CustomEvent('obs-table-before-change', {bubbles: true}));
            originalRow.children[1].textContent = 'Expanded detail. '.repeat(350);
            originalTable.dispatchEvent(new CustomEvent('obs-table-change', {bubbles: true}));
        }""")
        assert page.locator(".paged-reader h2").filter(has_text=re.compile("^Matrix$")).evaluate(
            "node => node.closest('.paper-sheet').querySelector('[data-table-wide] tbody tr') !== null",
        )
        assert page.locator(
            ".paged-reader .paper-sheet-flexible[data-page-orientation='landscape']",
        ).count() >= 1
    finally:
        page.close()
