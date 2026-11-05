"""Declared leading lines inside a Base table cell."""
import copy
from pathlib import Path

import pytest

from obs_html.content import ContentError, validate_base_definition
from test_browser import run_browser_script
from test_reader_controls import _write_reader_artifact, reader_browser  # noqa: F401


def _lead_status(spec):
    spec["properties"]["status"]["obsHtml"] = {"leadingLines": ["stamp"]}
    spec["views"][0]["obsHtml"]["pagination"] = False


def test_leading_lines_schema_matches_browser():
    valid = {
        "filters": 'kind == "relation"',
        "properties": {"status": {"obsHtml": {"leadingLines": ["stamp", "item.date"]}}},
        "views": [{"type": "table", "order": ["status"]}],
    }
    validate_base_definition(valid, Path("example.md"))
    invalid = []
    for options in [
        {"leadingLines": []},
        {"leadingLines": ["stamp", "stamp"]},
        {"leadingLines": [" "]},
        {"leadingLines": "stamp"},
        {"leadingLines": ["stamp"], "icon": {"name": "help", "label": "Help", "help": "x"}},
        {"leadingLines": ["stamp"], "reference": {"label": ["item.id"]}},
        {"leadingLines": ["stamp"], "editable": True},
    ]:
        definition = copy.deepcopy(valid)
        definition["properties"]["status"]["obsHtml"] = options
        invalid.append(definition)
    for definition in invalid:
        with pytest.raises(ContentError, match=r"Invalid base definition|; see capabilities/bases\."):
            validate_base_definition(definition, Path("example.md"))
    run_browser_script("""
        context.obsBases.validate(payload.valid);
        for (const definition of payload.invalid) {
            assert.throws(() => context.obsBases.validate(definition));
        }
    """, {"valid": valid, "invalid": invalid})


def _leading_artifact(tmp_path):
    def configure(spec):
        _lead_status(spec)
        first = tmp_path / "relation-000.md"
        first.write_text(first.read_text(encoding="utf-8").replace(
            "status: Complete 0\n", "status: Complete 0\nstamp: '2026-10-12'\n"), encoding="utf-8")
        blank = tmp_path / "relation-002.md"
        blank.write_text(blank.read_text(encoding="utf-8").replace(
            "status: Complete 2\n", "status: Complete 2\nstamp: '  '\n"), encoding="utf-8")

    return _write_reader_artifact(tmp_path, configure)


def test_native_leading_line_precedes_value_on_screen_and_in_pdf(tmp_path, reader_browser):
    from io import BytesIO

    from playwright.sync_api import expect
    from pypdf import PdfReader

    output = _leading_artifact(tmp_path)
    page = reader_browser.new_page(viewport={"width": 1500, "height": 1000})
    try:
        page.goto(output.as_uri())
        page.evaluate("obsHtmlReady")
        page.evaluate("obsPages.setPaged(false); obsArtifact.activateChapter('chapter')")
        page.evaluate("obsArtifact.whenChapterReady()")
        table = page.locator("[data-active-chapter] [data-data-table='chapter-base-1']")
        expect(table.locator("tbody tr[data-row-key]")).to_have_count(65)
        cells = table.locator("tbody tr[data-row-key]").evaluate_all("""rows => rows.map(row => {
            const cell = row.cells[1];
            return {lines: cell.innerText.split('\\n').map(line => line.trim()).filter(Boolean),
                    leads: [...cell.querySelectorAll('[data-table-leading-line]')].map(line => [
                        line.dataset.tableLeadingLine, line === cell.firstElementChild])};
        })""")
        by_status = {cell["lines"][-1]: cell for cell in cells}
        assert by_status["Complete 0"] == {"lines": ["2026-10-12", "Complete 0"], "leads": [["stamp", True]]}
        assert by_status["Complete 1"] == {"lines": ["Complete 1"], "leads": []}
        assert by_status["Complete 2"] == {"lines": ["Complete 2"], "leads": []}, "blank renders no line"

        page.evaluate("obsPages.setPaged(true)")
        pdf = PdfReader(BytesIO(page.pdf(prefer_css_page_size=True, print_background=True)))
        text = "\n".join(page.extract_text() for page in pdf.pages)
        assert "2026-10-12\nComplete 0" in text, "the leading line prints above the value"
        assert text.count("2026-10-12") == 1
    finally:
        page.close()