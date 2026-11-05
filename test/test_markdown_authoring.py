import json
import os
import subprocess
from pathlib import Path

import pytest

from obs_html.content import parse_manifest
from obs_html.renderer import render_report
from obs_html.report_data import decode_report_data


def test_home_contains_only_authored_tables_and_preserves_placement(tmp_path):
    manifest = tmp_path / "manifest.md"
    (tmp_path / "chapter.md").write_text("---\nproject status: Kept.\n---\n# Chapter\n", encoding="utf-8")
    manifest.write_text("- [[chapter]]\n\nBefore.\n\nAfter.\n", encoding="utf-8")
    data = decode_report_data(render_report(manifest, parse_manifest(manifest)))
    assert data["notes"][0]["tables"] == []
    fence = '```base\nfilters: \'note["project status"] != null\'\nviews:\n  - type: table\n    order: [chapter, project status]\n```\n'
    manifest.write_text("- [[chapter]]\n\nBefore.\n\n" + fence + "\nAfter.\n", encoding="utf-8")
    home = decode_report_data(render_report(manifest, parse_manifest(manifest)))["notes"][0]
    assert len(home["tables"]) == 1
    assert home["html"].index("Before.") < home["html"].index("data-base-table") < home["html"].index("After.")
    manifest.write_text("- [[chapter]]\n\nBefore.\n\nAfter.\n", encoding="utf-8")
    assert decode_report_data(render_report(manifest, parse_manifest(manifest)))["notes"][0]["tables"] == []


def test_bases_comparisons_are_typed_and_ignore_case_with_note_prefix():
    root = Path(__file__).resolve().parents[1]
    script = r"""
const fs = require("node:fs"), vm = require("node:vm");
globalThis.document = {querySelector: () => ({textContent: fs.readFileSync("src/obs_html/base.schema.json", "utf8")})};
for (const name of ["query.js", "base.js"]) vm.runInThisContext(fs.readFileSync(`src/obs_html/${name}`, "utf8"));
const rows = [
  {frontmatter: {kind: "Item", empty: ""}},
  {frontmatter: {kind: "item", empty: null}},
  {frontmatter: {kind: ["Item"]}},
];
const value = (row, field) => obsBases.recordValue(row, field);
console.log(JSON.stringify({
  exact: rows.map(row => obsBases.compileFilter('note.kind == "Item"', value).match(row)),
  nulls: rows.map(row => obsBases.compileFilter('empty == null', value).match(row)),
}));
"""
    result = subprocess.run(["node", "-e", script], cwd=root, capture_output=True, text=True, check=True)
    # capabilities/bases#Comparisons: text ignores case; a list never equals a single literal.
    assert json.loads(result.stdout) == {"exact": [True, True, False], "nulls": [False, True, True]}


def test_standard_not_means_none_and_grouping_is_one_property(tmp_path):
    from obs_html.content import ContentError, compile_base_filter, read_chapter_content, Chapter
    predicates = compile_base_filter({"not": ['left == true', 'right == true']})
    assert [predicates(row.get) for row in [
        {"left": False, "right": False}, {"left": True, "right": False},
        {"left": False, "right": True}, {"left": True, "right": True},
    ]] == [True, False, False, False]
    source = tmp_path / "chapter.md"
    source.write_text(
        "```base\nviews:\n  - type: table\n    order: [kind]\n"
        "    groupBy: [{property: kind}, {property: status}]\n```\n", encoding="utf-8",
    )
    with pytest.raises(ContentError, match="base"):
        read_chapter_content(Chapter(0, "Chapter", "chapter", source, "chapter"))


def test_yaml_frontmatter_preserves_safe_types_and_rejects_python_tags(tmp_path):
    from obs_html.content import ContentError, _split_frontmatter
    metadata, body = _split_frontmatter(
        '---\ntext: "true"\nflag: true\nnumber: 12.5\nempty: null\n'
        'day: 2026-10-28\nnested: {values: [0, false, ""]}\n---\nKept.\n', tmp_path / "note.md",
    )
    assert metadata == {"text": "true", "flag": True, "number": 12.5, "empty": None,
                        "day": "2026-10-28", "nested": {"values": [0, False, ""]}}
    assert body == "Kept.\n"
    with pytest.raises(ContentError, match="Invalid frontmatter"):
        _split_frontmatter('---\nvalue: !!python/object/apply:os.system ["echo unsafe"]\n---\n',
                           tmp_path / "note.md")


def test_inline_rendering_reuses_note_context_without_reusing_tokens(tmp_path, monkeypatch):
    from obs_html import content
    chapter = content.Chapter(0, "Chapter", "chapter", tmp_path / "chapter.md", "chapter")
    index = content.NoteReferenceIndex({}, {})
    create = content._markdown
    calls = []

    def counted(*args, **kwargs):
        calls.append(args[0].source_path)
        return create(*args, **kwargs)

    monkeypatch.setattr(content, "_markdown", counted)
    notes = [chapter]
    assert content.render_inline("**One**", chapter, notes, tmp_path, reference_index=index) == "<strong>One</strong>"
    assert content.render_inline("*Two*", chapter, notes, tmp_path, reference_index=index) == "<em>Two</em>"
    assert calls == [chapter.source_path]


def test_expansion_and_metric_series_discover_their_declared_sources(tmp_path):
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "catalog.md").write_text(
        '---\nkind: catalog\ncolumns: [{key: value}]\nmetrics: [{label: Values, field: value}]\n---\n',
        encoding="utf-8",
    )
    (tmp_path / "chapter.md").write_text(
        '```base\nfilters: \'kind == "datum"\'\nviews: [{type: table, order: [fields]}]\n'
        'obsHtml:\n  expandProperties:\n    fields: {sourceNote: catalog, property: columns, keyProperty: key}\n```\n\n'
        '```cards\nversion: 1\ncards:\n  - title: Counts\n    body: ""\n'
        '    obsHtml:\n      metricsFrom:\n        sourceNote: catalog\n        property: metrics\n'
        '        labelProperty: label\n        distinctProperty: field\n        where: []\n```\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    data = decode_report_data(render_report(manifest, parse_manifest(manifest)))
    assert "catalog.md" in {note["sourcePath"] for note in data["notes"]}


def test_native_query_closure_traverses_dotted_properties_through_arrays(tmp_path):
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "chapter.md").write_text(
        "```base\nfilters: 'runs.result != null'\n"
        "views: [{type: table, order: [file.name, runs.result]}]\n```\n",
        encoding="utf-8",
    )
    (tmp_path / "matching.md").write_text(
        "---\nruns: [{result: pass}, {result: fail}]\n---\n", encoding="utf-8",
    )
    (tmp_path / "missing.md").write_text("---\nruns: [{status: pending}]\n---\n", encoding="utf-8")
    (tmp_path / "absent.md").write_text("---\nstatus: pending\n---\n", encoding="utf-8")
    data = decode_report_data(render_report(tmp_path / "manifest.md", parse_manifest(tmp_path / "manifest.md")))
    source_paths = {note["sourcePath"] for note in data["notes"]}
    assert "matching.md" in source_paths
    assert "missing.md" in source_paths
    assert "absent.md" not in source_paths
    (tmp_path / "chapter.md").write_text(
        "```base\nfilters: 'runs.result == null'\n"
        "views: [{type: table, order: [file.name, runs.result]}]\n```\n",
        encoding="utf-8",
    )
    data = decode_report_data(render_report(tmp_path / "manifest.md", parse_manifest(tmp_path / "manifest.md")))
    source_paths = {note["sourcePath"] for note in data["notes"]}
    assert "matching.md" not in source_paths
    assert "missing.md" not in source_paths
    assert "absent.md" in source_paths


@pytest.mark.parametrize("expression", [
    'file.mtime == null', 'formula.total == null', 'this.title == null',
    'note.file.name == null', 'note["file.name"] == null',
])
def test_unsupported_standard_namespaces_do_not_silently_match_missing_values(tmp_path, expression):
    from obs_html.content import ContentError
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "chapter.md").write_text(
        "```base\nfilters: '" + expression + "'\nviews: [{type: table, order: [file.name]}]\n```\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    with pytest.raises(ContentError, match="Unsupported Bases property"):
        render_report(manifest, parse_manifest(manifest))


def test_unsupported_filter_is_rejected_even_when_an_earlier_operand_is_false(tmp_path):
    from obs_html.content import ContentError
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "chapter.md").write_text(
        '```base\nfilters:\n  and: [\'status == "not-present"\', "formula.total == null"]\n'
        'views: [{type: table, order: [file.name]}]\n```\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    with pytest.raises(ContentError, match="Unsupported Bases property"):
        render_report(manifest, parse_manifest(manifest))


def test_native_base_validator_rejects_unsupported_properties_and_empty_expansion():
    import json
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the native Bases compiler.")
    root = Path(__file__).resolve().parents[1]
    script = """
        const fs = require('fs');
        const root = process.argv[1];
        const path = require('path');
        global.document = {querySelector: () => ({textContent:
            fs.readFileSync(path.join(root, 'src', 'obs_html', 'base.schema.json'), 'utf8')})};
        eval(fs.readFileSync(path.join(root, 'src', 'obs_html', 'base.js'), 'utf8'));
        const cases = [
            {filters: 'file.mtime == null', views: [{type: 'table', order: ['file.name']}]},
            {filters: 'formula.total == null', views: [{type: 'table', order: ['file.name']}]},
            {views: [{type: 'table', order: ['this.title']}]},
            {filters: 'note.file.name == null', views: [{type: 'table', order: ['file.name']}]},
            {filters: 'note["file.name"] == null', views: [{type: 'table', order: ['file.name']}]},
            {obsHtml: {expandProperties: [{}]}, views: [{type: 'table', order: ['file.name']}]},
        ];
        console.log(JSON.stringify(cases.map(value => {
            try { obsBases.validate(value); return null; } catch (error) { return error.message; }
        })));
    """
    result = subprocess.run([node, "-e", script, str(root)], check=True, capture_output=True, text=True)
    failures = json.loads(result.stdout)
    assert all(failures), failures
    assert all("Unsupported Bases property" in failure for failure in failures[:-1])


def test_archived_empty_cover_title_preserves_native_property(tmp_path):
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "chapter.md").write_text(
        '```base\nfilters: \'note.title == ""\'\n'
        'views: [{type: table, order: [file.name, title]}]\n```\n',
        encoding="utf-8",
    )
    (tmp_path / "archive").mkdir()
    (tmp_path / "archive" / "manifest.md").write_text('---\ntitle: ""\n---\n', encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    data = decode_report_data(render_report(manifest, parse_manifest(manifest)))
    archived = next(note for note in data["notes"] if note["sourcePath"] == "archive/manifest.md")
    assert archived["frontmatter"]["title"] == ""
    assert archived["title"] == "Manifest"


@pytest.mark.skipif(not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"), reason="Native Bases semantics")
def test_native_authored_standard_filters_columns_groups_and_multiple_fences(tmp_path):
    from playwright.sync_api import sync_playwright, expect
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n", encoding="utf-8")
    chapter = tmp_path / "chapter.md"
    query = (
        "```base\nfilters: 'kind == \"datum\"'\nproperties:\n"
        "  file.name: {displayName: File}\n  note.value: {displayName: Value}\n"
        "views:\n  - type: table\n    order: [file.name, note.value]\n"
        "    filters:\n      not: ['disabled == true', 'excluded == true']\n"
        "    groupBy: {property: note.bucket, direction: DESC}\n"
        "    sort: [{property: note.value, direction: DESC}]\n```\n"
    )
    native_only = query.replace(
        'filters: \'kind == "datum"\'',
        'filters:\n  and:\n    - \'kind == "datum"\'\n'
        '    - \'note.title == null\'\n    - \'note.recordType == null\'',
    )
    chapter.write_text("# Chapter\n\nBefore.\n\n" + query + "\nBetween.\n\n" + native_only, encoding="utf-8")
    for name, metadata in {
        "one": {"kind": "datum", "value": 2, "bucket": "Z"},
        "two": {"kind": "datum", "value": 12, "bucket": "Z"},
        "three": {"kind": "datum", "value": 3, "bucket": "A", "disabled": True},
        "four": {"kind": "datum", "value": 4, "bucket": "A", "excluded": True},
    }.items():
        (tmp_path / f"{name}.md").write_text("---\n" + json.dumps(metadata) + "\n---\n", encoding="utf-8")
    report = tmp_path / "report.html"
    report.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"])
        page = browser.new_page()
        try:
            page.goto(report.as_uri())
            page.wait_for_function("document.documentElement.dataset.reportStatus === 'ready'")
            page.evaluate("obsPages.setPaged(false); obsReport.activateChapter('chapter')")
            page.evaluate("obsReport.whenChapterReady()")
            tables = page.locator("[data-active-chapter] [data-data-table]")
            expect(tables).to_have_count(2)
            for table in tables.all():
                expect(table.locator("thead th > span:first-child")).to_have_text(["File", "Value"])
                assert "bucket: Z (2)" in table.inner_text()
                expect(table.locator("tbody tr[data-row-key] td:first-child")).to_contain_text(["two", "one"])
            assert page.locator("[data-export-status]").is_hidden()
        finally:
            browser.close()


@pytest.mark.skipif(not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"), reason="Native Bases semantics")
def test_native_chapter_records_omit_absent_bottom_lines(tmp_path):
    from playwright.sync_api import sync_playwright, expect
    (tmp_path / "plain.md").write_text("# Plain\n\nNo summary.\n", encoding="utf-8")
    (tmp_path / "summary.md").write_text("---\nbottom line: Kept.\n---\n# Summary\n", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text(
        "- [[plain]]\n- [[summary]]\n\n```base\nfilters: 'note[\"bottom line\"] != null'\n"
        "views:\n  - type: table\n    order: [chapter, bottom line]\nobsHtml: {records: chapter}\n```\n",
        encoding="utf-8",
    )
    report = tmp_path / "report.html"
    report.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"])
        page = browser.new_page()
        try:
            page.goto(report.as_uri())
            page.wait_for_function("document.documentElement.dataset.reportStatus === 'ready'")
            page.evaluate("obsPages.setPaged(false); obsReport.activateChapter('home')")
            page.evaluate("obsReport.whenChapterReady()")
            rows = page.locator("[data-active-chapter] [data-data-table] tbody tr[data-row-key]")
            expect(rows).to_have_count(1)
            expect(rows.first).to_contain_text("Summary")
            expect(rows.first).to_contain_text("Kept.")
        finally:
            browser.close()


@pytest.mark.skipif(not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"), reason="Native Bases semantics")
def test_native_note_filters_keep_explicit_members(tmp_path):
    from playwright.sync_api import sync_playwright, expect
    for name, label in {"first": "One", "second": "Two"}.items():
        (tmp_path / f"{name}.md").write_text(
            f"---\nkind: reference\ndocument: {label}\n---\n", encoding="utf-8",
        )
    (tmp_path / "chapter.md").write_text(
        "# Chapter\n\n```base\nfilters: 'kind == \"reference\"'\n"
        "views:\n  - type: table\n    order: [obsHtml.label, document]\n"
        "obsHtml:\n  members:\n    - {path: second.md, label: B}\n    - {path: first.md, label: A}\n```\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n", encoding="utf-8")
    report = tmp_path / "report.html"
    report.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"])
        page = browser.new_page()
        try:
            page.goto(report.as_uri())
            page.wait_for_function("document.documentElement.dataset.reportStatus === 'ready'")
            page.evaluate("obsPages.setPaged(false); obsReport.activateChapter('chapter')")
            page.evaluate("obsReport.whenChapterReady()")
            rows = page.locator("[data-active-chapter] [data-data-table] tbody tr[data-row-key]")
            expect(rows).to_have_count(2)
            expect(rows).to_contain_text(["BTwo", "AOne"])
        finally:
            browser.close()
