"""Authored Bases control tables: page size, query catalog, views, .base files and groups.

Owner: spec/design_input/generic-tables.md; the manifest query profile is owned by
spec/design_input/input-model.md (global query profile).
"""
import json
import os

import pytest

from obs_html.cli import main
from obs_html.artifact_data import decode_artifact_data

QUERY = {
    "scope": "records", "where": [{"field": "kind", "equals": "item"}],
    "fields": [{"field": "grade", "label": "Grade"}, {"field": "lead", "label": "Lead", "source": "team.lead"}],
}
ITEMS = 12
REGISTERS = (
    "properties:\n  label: {displayName: Label}\n  term: {displayName: Term}\n"
    "views:\n  - type: table\n    name: Open points\n    filters: 'type == \"open_point\"'\n"
    "    order: [label, text]\n    obsHtml: {records: tag}\n"
    "  - type: table\n    name: Glossary\n    filters: 'kind == \"glossary\"'\n"
    "    order: [term, definition]\n    obsHtml: {records: glossary}\n"
)
VIEWS = (
    "filters: 'kind == \"item\"'\nproperties:\n  team.lead: {displayName: Lead}\n"
    "views:\n  - type: table\n    name: Grades\n    order: [file.name, grade]\n"
    "  - type: table\n    name: Leads of A\n    order: [team.lead, file.name]\n"
    "    filters: 'grade == \"A\"'\n"
)


def _fence(view: str, top: str = "") -> str:
    return (f"```base\nfilters: 'kind == \"item\"'\n{top}views:\n  - type: table\n"
            f"    order: [file.name, grade]\n{view}```\n\n")


@pytest.fixture(scope="module")
def document(tmp_path_factory):
    vault = tmp_path_factory.mktemp("bases-authoring") / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text(
        "---\n" + json.dumps({"obsHtml": {"query": QUERY}}) + "\n---\n- [[paged]]\n- [[views]]\n- [[embed-a]]\n- [[embed-b]]\n- [[groups]]\n- [[risks]]\n- [[terms]]\n- [[marked]]\n- [[sized]]\n", encoding="utf-8",
    )
    (vault / "paged.md").write_text(
        "# Paged\n\n" + _fence("    obsHtml: {pageSize: 5}\n") + _fence(""), encoding="utf-8",
    )
    (vault / "views.md").write_text("# Views\n\n```base\n" + VIEWS + "```\n", encoding="utf-8")
    (vault / "groups.md").write_text(
        "# Groups\n\n```base\nfilters: 'kind == \"item\"'\nproperties:\n  team.lead: {displayName: Lead}\n"
        "views:\n  - type: table\n    order: [file.name]\n    groupBy: {property: team.lead}\n"
        "    obsHtml: {groupOrder: [Cy, Ann]}\n```\n\n"
        "```base\nfilters: 'kind == \"item\"'\nproperties:\n  grade: {displayName: ''}\n"
        "views:\n  - type: table\n    order: [file.name]\n    groupBy: {property: grade, direction: DESC}\n```\n",
        encoding="utf-8",
    )
    (vault / "registers.base").write_text(REGISTERS, encoding="utf-8")
    (vault / "risks.md").write_text("# Risks\n\n![[registers.base#Open points]]\n", encoding="utf-8")
    (vault / "terms.md").write_text("# Terms\n\n![[registers.base#Glossary]]\n", encoding="utf-8")
    (vault / "marked.md").write_text(
        "# Marked\n\nFirst question. #mark/open_point/first_question\n\n"
        "Second question. #mark/open_point/second_question\n\nA risk. #mark/risk/some_risk\n",
        encoding="utf-8",
    )
    (vault / "datum.md").write_text(
        "---\nkind: glossary\nterm: Datum\ndefinition: A reference.\n---\n", encoding="utf-8",
    )
    (vault / "sized.md").write_text(
        "# Sized\n\n```base\nfilters: 'kind == \"item\"'\n"
        "views:\n  - type: table\n    order: [file.name, team.lead, grade]\n"
        "    columnSize: {file.name: 300, note.grade: 100}\n```\n\n"
        "```base\nfilters: 'kind == \"item\"'\n"
        "views:\n  - type: table\n    order: [file.name, team.lead, grade]\n```\n",
        encoding="utf-8",
    )
    (vault / "shared").mkdir()
    (vault / "shared" / "items.base").write_text(VIEWS, encoding="utf-8")
    (vault / "embed-a.md").write_text("# Embed A\n\nBefore.\n\n![[items.base]]\n\nAfter.\n", encoding="utf-8")
    (vault / "embed-b.md").write_text("# Embed B\n\n![[shared/items.base#Leads of A]]\n", encoding="utf-8")
    for index in range(ITEMS):
        (vault / f"item-{index:02d}.md").write_text(
            "---\n" + json.dumps({
                "kind": "item", "grade": "AB"[index % 2], "team": {"lead": ["Ann", "Bob", "Cy"][index % 3]},
            }) + "\n---\n", encoding="utf-8",
        )
    output = vault.parent / "document.html"
    assert main(["--source", str(vault), "--output", str(output)]) == 0
    return output


@pytest.fixture(scope="module")
def page(document):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for authored table checks.")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(document.as_uri())
        page.wait_for_function("document.documentElement.dataset.artifactStatus === 'ready'")
        page.evaluate("obsPages.setPaged(false)")
        try:
            yield page
            assert errors == []
        finally:
            browser.close()


def _table(page, chapter: str, index: int):
    page.evaluate("slug => obsArtifact.activateChapter(slug)", chapter)
    return page.locator(f'[data-active-chapter] [data-data-table="{chapter}-base-{index}"]')


def test_view_page_size_overrides_the_document_default(page):
    from playwright.sync_api import expect

    sized, default = _table(page, "paged", 1), _table(page, "paged", 2)
    expect(sized.locator("tbody tr[data-row-key]:visible")).to_have_count(5)
    expect(sized.locator(".data-table-page")).to_have_text("Page 1 of 3")
    expect(default.locator("tbody tr[data-row-key]:visible")).to_have_count(ITEMS)


def test_manifest_declares_the_global_query_catalog(document, page):
    assert decode_artifact_data(document.read_text(encoding="utf-8"))["query"] == QUERY
    page.evaluate("obsArtifact.openBar('filter', 'left')")
    pills = page.locator('[data-bar="filter"] .filter-pill').all_text_contents()
    assert any(pill.startswith("Lead") for pill in pills), pills


@pytest.mark.parametrize(("declared", "error"), [
    (QUERY, ""), ("[[one]]", "must declare obsHtml.query"),
])
def test_manifest_query_profile_may_be_declared_by_one_linked_note(tmp_path, declared, error):
    from obs_html.content import ContentError, parse_manifest
    from obs_html.renderer import render_artifact

    manifest = tmp_path / "manifest.md"
    manifest.write_text('---\nobsHtml: {query: "[[profile]]"}\n---\n- [[one]]\n', encoding="utf-8")
    (tmp_path / "one.md").write_text("# One\n", encoding="utf-8")
    (tmp_path / "profile.md").write_text(
        "---\n" + json.dumps({"obsHtml": {"document": False, "query": declared}}) + "\n---\n",
        encoding="utf-8",
    )
    if error:
        with pytest.raises(ContentError, match=error):
            render_artifact(manifest, parse_manifest(manifest))
    else:
        assert decode_artifact_data(render_artifact(manifest, parse_manifest(manifest)))["query"] == QUERY


def test_project_configuration_rejects_the_moved_query_profile(tmp_path, capsys):
    (tmp_path / "manifest.md").write_text("- [[one]]\n", encoding="utf-8")
    (tmp_path / "one.md").write_text("# One\n", encoding="utf-8")
    (tmp_path / "cfg.json").write_text(json.dumps({"schemaVersion": 1, "artifact": {"query": QUERY}}),
                                       encoding="utf-8")
    with pytest.raises(SystemExit, match="2"):
        main(["--source", str(tmp_path), "--output", str(tmp_path / "out.html")])
    assert "obsHtml: {query" in capsys.readouterr().err


@pytest.mark.parametrize("view", [{"pageSize": 0}, {"pageSize": 2.5}, {"pageSize": 5, "pagination": False}])
def test_page_size_must_be_a_positive_whole_number_with_pagination(tmp_path, view):
    from obs_html.content import ContentError, validate_base_definition

    with pytest.raises(ContentError):
        validate_base_definition({"views": [{"type": "table", "order": ["x"], "obsHtml": view}]},
                                 tmp_path / "x.md")

def test_several_views_render_a_selector_that_switches_columns_and_rows(page):
    from playwright.sync_api import expect

    table = _table(page, "views", 1)
    selector = table.locator("[data-table-views]")
    expect(selector.get_by_role("button")).to_have_text(["Grades", "Leads of A"])
    expect(selector.get_by_role("button", name="Grades")).to_have_attribute("aria-pressed", "true")
    expect(table.locator("thead th > span:first-child")).to_have_text(["file.name", "grade"])
    expect(table.locator("tbody tr[data-row-key]")).to_have_count(ITEMS)
    selector.get_by_role("button", name="Leads of A").click()
    table = _table(page, "views", 1)
    expect(table.locator("[data-table-views] button[aria-pressed='true']")).to_have_text("Leads of A")
    expect(table.locator("thead th > span:first-child")).to_have_text(["Lead", "file.name"])
    expect(table.locator("tbody tr[data-row-key]")).to_have_count(ITEMS // 2)
    assert page.evaluate("obsArtifact.readerState().tables")["views-base-1"] == {"view": "Leads of A"}
    page.evaluate("obsArtifact.activateChapter('paged'); obsArtifact.activateChapter('views')")
    expect(_table(page, "views", 1).locator("thead th > span:first-child")).to_have_text(["Lead", "file.name"])


def test_any_view_filter_includes_its_notes(tmp_path):
    from obs_html.content import parse_manifest
    from obs_html.renderer import render_artifact

    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n", encoding="utf-8")
    (tmp_path / "one.md").write_text(
        "# One\n\n```base\nviews:\n  - type: table\n    name: First\n    order: [file.name]\n"
        "    filters: 'kind == \"first\"'\n  - type: table\n    name: Second\n    order: [file.name]\n"
        "    filters: 'kind == \"second\"'\n```\n", encoding="utf-8",
    )
    for kind in ("first", "second", "third"):
        (tmp_path / f"{kind}.md").write_text(f"---\nkind: {kind}\n---\n", encoding="utf-8")
    notes = decode_artifact_data(render_artifact(manifest, parse_manifest(manifest)))["notes"]
    assert {note["sourcePath"] for note in notes} == {"manifest.md", "one.md", "first.md", "second.md"}


@pytest.mark.parametrize("names", [[None, "Second"], ["Same", "Same"], ["", "Second"]])
def test_several_views_need_unique_names(tmp_path, names):
    from obs_html.content import ContentError, validate_base_definition

    views = [{"type": "table", "order": ["x"], **({} if name is None else {"name": name})} for name in names]
    with pytest.raises(ContentError, match="unique nonempty names"):
        validate_base_definition({"views": views}, tmp_path / "x.md")


def test_one_base_file_embedded_in_two_notes_renders_twice(document, page):
    from playwright.sync_api import expect

    notes = {note["slug"]: note for note in decode_artifact_data(document.read_text(encoding="utf-8"))["notes"]}
    first, second = notes["embed-a"]["tables"][0], notes["embed-b"]["tables"][0]
    assert first["definition"] == notes["views"]["tables"][0]["definition"]
    assert second["definition"] == {**first["definition"], "views": first["definition"]["views"][1:]}
    assert notes["embed-a"]["html"].index("Before.") < notes["embed-a"]["html"].index("data-base-table") \
        < notes["embed-a"]["html"].index("After.")
    table = _table(page, "embed-a", 1)
    expect(table.locator("[data-table-views] button[aria-pressed='true']")).to_have_text("Grades")
    expect(table.locator("tbody tr[data-row-key]")).to_have_count(ITEMS)
    table = _table(page, "embed-b", 1)
    expect(table.locator("thead th > span:first-child")).to_have_text(["Lead", "file.name"])
    expect(table.locator("tbody tr[data-row-key]")).to_have_count(ITEMS // 2)
    expect(table.locator("[data-table-views]")).to_have_count(0)


@pytest.mark.parametrize(("files", "embed", "message"), [
    ({}, "![[missing.base]]", "does not resolve"),
    ({"a/x.base": VIEWS, "b/x.base": VIEWS}, "![[x.base]]", "is ambiguous"),
    ({"x.base": VIEWS}, "![[x.base#Unknown]]", "x.base has no view 'Unknown'"),
    ({"x.base": "views: []\n"}, "![[x.base]]", r"x\.base, base file.*embedded in .*one\.md"),
])
def test_embedded_base_errors_name_the_file_and_note(tmp_path, files, embed, message):
    from obs_html.content import ContentError

    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    (tmp_path / "manifest.md").write_text("- [[one]]\n", encoding="utf-8")
    (tmp_path / "one.md").write_text(f"# One\n\n{embed}\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--source", str(tmp_path), "--check"])
    from obs_html.content import parse_manifest, read_chapter_content
    with pytest.raises(ContentError, match=message):
        read_chapter_content(parse_manifest(tmp_path / "manifest.md")[0])


def _captions(table):
    return [text.replace("\u25be", "").replace("\u25b8", "").strip()
            for text in table.locator(".data-table-group-row").all_inner_texts()]


def test_group_captions_use_display_names_and_follow_the_declared_order(page):
    from playwright.sync_api import expect

    ordered = _table(page, "groups", 1)
    expect(ordered.locator(".data-table-group-row")).to_have_count(3)
    assert _captions(ordered) == ["Lead: Cy (4)", "Lead: Ann (4)", "Lead: Bob (4)"]
    assert _captions(_table(page, "groups", 2)) == ["B (6)", "A (6)"]
    ordered = _table(page, "groups", 1)
    ordered.locator("th[data-column-key='file.name']").click()
    assert _captions(ordered) == ["Lead: Cy (4)", "Lead: Ann (4)", "Lead: Bob (4)"]


@pytest.mark.parametrize(("view", "message"), [
    ({"obsHtml": {"groupOrder": ["A"]}}, "groupOrder requires groupBy"),
    ({"groupBy": {"property": "x"}, "obsHtml": {"groupOrder": []}}, "groupOrder"),
])
def test_group_order_needs_a_grouped_view(tmp_path, view, message):
    from obs_html.content import ContentError, validate_base_definition

    with pytest.raises(ContentError, match=message):
        validate_base_definition({"views": [{"type": "table", "order": ["x"], **view}]}, tmp_path / "x.md")


@pytest.mark.parametrize("filters", ['recordType == "tag"', {"and": ['kind == "x"', 'recordType != null']}])
def test_bare_record_type_filters_are_rejected_with_a_migration_message(tmp_path, filters):
    from obs_html.content import ContentError, validate_base_definition

    with pytest.raises(ContentError, match=r"recordType filters were removed; .*obsHtml: \{records: note \|"):
        validate_base_definition({"filters": filters, "views": [{"type": "table", "order": ["x"]}]},
                                 tmp_path / "x.md")

def test_register_views_of_one_base_file_render_their_own_projections(page):
    from playwright.sync_api import expect

    points = _table(page, "risks", 1)
    expect(points.locator("[data-table-views]")).to_have_count(0)
    expect(points.locator("thead th > span:first-child")).to_have_text(["Label", "text"])
    expect(points.locator("tbody tr[data-row-key]")).to_have_count(2)
    expect(points.locator("tbody tr[data-row-key] td:first-child")).to_have_text(
        ["first_question", "second_question"])
    terms = _table(page, "terms", 1)
    expect(terms.locator("tbody tr[data-row-key]")).to_have_attribute("data-row-key", "glossary:datum")


def test_register_views_are_bases_yaml_without_their_obshtml_keys(tmp_path):
    import yaml
    from obs_html.content import validate_base_definition

    definition = yaml.safe_load(REGISTERS)
    for view in definition["views"]:
        del view["obsHtml"]
    validate_base_definition(definition, tmp_path / "registers.base")


def test_macros_are_rejected_with_a_migration_message(tmp_path):
    from obs_html.content import ContentError, parse_manifest, read_chapter_content

    (tmp_path / "manifest.md").write_text("- [[one]]\n", encoding="utf-8")
    (tmp_path / "one.md").write_text("---\nobsHtml: {macros: [{macro: glossary}]}\n---\n# One\n", encoding="utf-8")
    with pytest.raises(ContentError, match=r"obsHtml.macros was removed.*registers.base#Glossary"):
        read_chapter_content(parse_manifest(tmp_path / "manifest.md")[0])


def test_column_size_weights_columns_and_leaves_the_others_content_sized(page):
    widths = lambda table: table.locator("thead th").evaluate_all(
        "cells => cells.map(cell => cell.getBoundingClientRect().width)")
    sized = _table(page, "sized", 1)
    page.wait_for_function("() => document.querySelector('[data-data-table=sized-base-1] col')?.style.width")
    name, lead, grade = widths(sized)
    reference = widths(_table(page, "sized", 2))[1]
    assert abs(name / grade - 3) < 0.05, (name, grade)
    assert abs(lead - reference) <= 3, (lead, reference)
    scroller = sized.locator(".data-table-scroll")
    assert scroller.evaluate("node => node.scrollWidth <= node.clientWidth")


def test_column_size_cannot_combine_with_equal_column_sizing(tmp_path):
    from obs_html.content import ContentError, validate_base_definition

    view = {"type": "table", "order": ["x"], "columnSize": {"x": 100}, "obsHtml": {"columnSizing": "equal"}}
    with pytest.raises(ContentError, match="columnSize cannot be combined"):
        validate_base_definition({"views": [view]}, tmp_path / "x.md")


def test_weighted_columns_share_the_rest_and_keep_their_label_minimum(page):
    fit = "([specs, available]) => obsDataTable.fitColumns(specs, available, specs.length - 1)"
    content = {"max": 80, "floor": 40}
    assert page.evaluate(fit, [[{"weight": 300, "max": 300, "floor": 50}, content,
                                {"weight": 100, "max": 100, "floor": 50}], 500]) == [315, 80, 105]
    assert page.evaluate(fit, [[{"weight": 300, "max": 300, "floor": 50}, content,
                                {"weight": 10, "max": 60, "floor": 60}], 300]) == [160, 80, 60]
