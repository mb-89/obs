import importlib
import json
from importlib.resources import files
from pathlib import Path

import pytest

from obs_html.bars import discover_bars
from obs_html.content import parse_manifest
from obs_html.renderer import render_report
from test_browser import run_report_dom_contract
from test_reader_controls import _write_reader_fixture, reader_browser  # noqa: F401


def test_adding_one_module_is_enough_to_discover_a_bar(
    tmp_path: Path, monkeypatch
) -> None:
    package = tmp_path / "example_bars"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "notes.py").write_text(
        "from obs_html.bars import BarDefinition\n"
        "BAR = BarDefinition(key='notes', label='Notes', icon='N', "
        "help='Read notes', order=5, render=lambda chapters: '<p>Notes</p>')\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    bars = discover_bars("example_bars")

    assert [(bar.key, bar.label) for bar in bars] == [("notes", "Notes")]
    assert bars[0].render([]) == "<p>Notes</p>"
    assert bars[0].script == ""


def test_a_bar_runtime_is_discovered_from_its_sibling_script(tmp_path: Path, monkeypatch) -> None:
    package = tmp_path / "scripted_bars"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "notes.py").write_text(
        "from obs_html.bars import BarDefinition\n"
        "BAR = BarDefinition(key='notes', label='Notes', icon='N', "
        "help='Read notes', order=5, render=lambda chapters: '')\n",
        encoding="utf-8",
    )
    (package / "notes.js").write_text("globalThis.notes = 1;\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    assert discover_bars("scripted_bars")[0].script == "globalThis.notes = 1;\n"


def test_a_bar_cannot_carry_its_runtime_as_a_python_string(tmp_path: Path, monkeypatch) -> None:
    package = tmp_path / "inline_bars"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "notes.py").write_text(
        "from obs_html.bars import BarDefinition\n"
        "BAR = BarDefinition(key='notes', label='Notes', icon='N', "
        "help='Read notes', order=5, render=lambda chapters: '', script='alert(1)')\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    with pytest.raises(TypeError, match="notes.js"):
        discover_bars("inline_bars")


def test_shipped_bar_runtimes_are_their_sibling_scripts() -> None:
    package = files("obs_html.bars")
    scripted = {bar.key: bar.script for bar in discover_bars() if bar.script}

    assert set(scripted) == {"comments", "filter", "search", "settings"}
    for key, script in scripted.items():
        assert script == package.joinpath(f"{key}.js").read_text(encoding="utf-8")


def test_renderer_infers_menu_and_content_from_discovered_bars(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("# One", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n", encoding="utf-8")

    report = render_report(manifest, parse_manifest(manifest))

    for bar in discover_bars():
        assert f'data-dock-bar="{bar.key}"' in report
        assert f'data-bar="{bar.key}"' in report
        assert bar.icon in report


def test_filter_and_search_are_separate_discovered_bars(tmp_path: Path) -> None:
    bars = {bar.key: bar for bar in discover_bars()}

    assert bars["filter"].icon == "filter"
    assert bars["search"].icon == "search"
    search_markup = bars["search"].render([])
    filter_markup = bars["filter"].render([])
    assert "data-search-results" in search_markup
    assert "search-submit" not in search_markup
    assert 'aria-label="Query language help" data-hover-help="Bare terms' in search_markup
    assert 'aria-label="Query language help" data-hover-help="Bare terms' in filter_markup
    assert 'role="tooltip"' not in search_markup + filter_markup
    assert "data-filter-presets" in filter_markup
    assert "data-filter-selections" in filter_markup
    assert "data-filter-fields" in filter_markup
    names = [f"chapter-{index}" for index in range(6)]
    manifest = tmp_path / "manifest.md"
    manifest.write_text("".join(f"- [[{name}]]\n" for name in names), encoding="utf-8")
    for index, name in enumerate(names):
        (tmp_path / f"{name}.md").write_text(
            f"---\nstatus: {'draft' if index < 3 else 'final'}\n---\n"
            f"# {name}\n\n{'Draft' if index < 3 else 'Final'} prose.\n",
            encoding="utf-8",
        )
    report = tmp_path / "report.html"
    report.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    runtimes = [files("obs_html.bars") / f"{key}.js" for key in ("filter", "search")]
    run_report_dom_contract(report, "--discovered-query-controls-only", *runtimes)


def test_comments_is_a_discovered_review_bar() -> None:
    comments = {bar.key: bar for bar in discover_bars()}["comments"]
    content = comments.render([])

    assert comments.label == "Comments"
    assert "data-comment-add" in content
    assert 'data-storage-warning="reviewer"' in content
    assert "globalThis.obsStorage.read" in comments.script
    assert "globalThis.obsStorage.write" in comments.script
    assert 'data-comment-add disabled' in content
    assert "data-comment-text" not in content
    assert "comment-compose" not in content
    assert "comment-query-row" in content
    assert "data-comment-add-chapter" not in content
    assert "data-comment-save" in content
    assert "data-comment-load" in content
    assert "data-comment-files" in content
    assert "multiple" in content
    assert "data-comment-filter-input" in content
    assert "globalThis.obsQuery.compile" in comments.script
    assert 'text: ""' in comments.script
    assert "comment-toggle" not in comments.script
    assert "collapsed" not in comments.script
    assert "No comments yet" not in comments.script
    assert "No comments match" not in comments.script
    assert "comment-reply-editor" not in comments.script
    assert "Add reply" not in comments.script
    assert 'chapterBody.addEventListener("mousemove"' in comments.script
    assert 'openBar?.("comments", "right")' in comments.script
    assert 'CSS.highlights.set("obs-comments-hover"' in comments.script
    assert "const quote = rangeText(range)" in comments.script
    assert "range.toString() === target.quote" not in comments.script
    assert "data-review-summary" in content
    assert "data-review-summary-count" in content
    assert 'querySelectorAll("p, li, tr, pre, figure")' in comments.script
    assert 'element.matches("tr")' in comments.script
    assert 'document.addEventListener("obs-table-change"' in comments.script
    assert '"--review-rail-offset"' in comments.script
    assert "aggregateState" in comments.script
    assert "reviewerState" in comments.script
    assert 'requestedState === "rejected"' in comments.script
    assert "syncReviewFields" in comments.script
    assert 'openBar("filter", "right")' in comments.script
    assert "obs-filter-change" in comments.script
    assert "data-review-gutter" in comments.script
    assert "reviewers" in comments.script
    assert "data-comment-island" in comments.script
    assert "CSS.highlights" in comments.script
    assert "showSaveFilePicker" in comments.script
    assert "innerHTML" not in comments.script


def test_settings_is_discovered_and_owns_appearance_selection() -> None:
    settings = {bar.key: bar for bar in discover_bars()}["settings"]
    content = settings.render([])

    assert settings.label == "Settings + exports"
    assert 'aria-label="Appearance"' in content
    assert '<option value="system">System</option>' in content
    assert '<option value="light">Light</option>' in content
    assert '<option value="dark">Dark</option>' in content
    assert "data-theme-icon" in content
    assert 'globalThis.obsAssets.replace' in settings.script
    assert "data-pages-toggle" in content
    assert "data-export-pdf" in content
    assert 'class="settings-page-export"' in content
    assert "notes.</p>" not in content
    assert "data-theme-status" not in content
    assert 'data-storage-warning="appearance"' not in content
    assert "obsStorage" not in settings.script
    assert "localStorage" not in settings.script
    assert 'root.dataset.theme = value' in settings.script


def test_dock_buttons_use_left_right_top_bottom_order(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("# One", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n", encoding="utf-8")

    report = render_report(manifest, parse_manifest(manifest))
    positions = [report.index(f'data-dock-direction="{direction}"') for direction in (
        "left",
        "right",
        "top",
        "bottom",
    )]

    assert positions == sorted(positions)


@pytest.mark.parametrize("edge", ["left", "right", "top", "bottom"])
def test_native_splitter_anchors_and_neighbor_only_geometry(tmp_path, reader_browser, edge):
    manifest = _write_reader_fixture(tmp_path)
    report = tmp_path / "dock.html"
    report.write_text(render_report(manifest, parse_manifest(manifest)), encoding="utf-8")
    page = reader_browser.new_page(viewport={"width": 1800, "height": 1200})
    horizontal = edge in ("top", "bottom")
    axis, size = ("x", "width") if horizontal else ("y", "height")
    try:
        page.goto(report.as_uri())
        page.evaluate("edge => ['toc','filter','search'].forEach(bar => obsReport.openBar(bar,edge))", edge)
        region = page.locator(f"[data-dock-region='{edge}']")
        dividers = region.locator(":scope > [data-bar-resize]")
        panes = region.locator(":scope > .dock-bar")
        page.wait_for_timeout(100)
        initial = [pane.bounding_box()[size] for pane in panes.all()]
        assert max(initial) - min(initial) < 1
        before = [divider.bounding_box()[axis] for divider in dividers.all()]
        bounds = dividers.first.bounding_box()
        x, y = bounds["x"] + bounds["width"] / 2, bounds["y"] + bounds["height"] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + (36 if horizontal else 0), y + (0 if horizontal else 36), steps=3)
        page.mouse.up()
        moved = [divider.bounding_box()[axis] for divider in dividers.all()]
        assert moved[0] - before[0] == pytest.approx(36, abs=1)
        assert moved[1] == pytest.approx(before[1], abs=1)
        page.evaluate("edge => obsReport.openBar('settings',edge)", edge)
        page.wait_for_timeout(100)
        added = [divider.bounding_box()[axis] for divider in dividers.all()]
        assert added[0] == pytest.approx(moved[0], abs=1)
        tail = [pane.bounding_box()[size] for pane in panes.all()[1:]]
        assert max(tail) - min(tail) < 1
        dividers.nth(1).press("ArrowRight" if horizontal else "ArrowDown")
        keyed = [divider.bounding_box()[axis] for divider in dividers.all()]
        assert keyed[0] == pytest.approx(added[0], abs=1)
        assert keyed[1] - added[1] == pytest.approx(16, abs=1)
        assert keyed[2] == pytest.approx(added[2], abs=1)
        dividers.nth(1).dblclick()
        reset = [divider.bounding_box()[axis] for divider in dividers.all()]
        assert reset[0] == pytest.approx(keyed[0], abs=1)
        tail = [pane.bounding_box()[size] for pane in panes.all()[1:]]
        assert max(tail) - min(tail) < 1
        dividers.first.dblclick()
        all_sizes = [pane.bounding_box()[size] for pane in panes.all()]
        assert max(all_sizes) - min(all_sizes) < 1
        page.screenshot(path=str(tmp_path / f"dock-{edge}.png"))
        (tmp_path / f"dock-{edge}.json").write_text(json.dumps({
            "edge": edge, "initialSizes": initial, "before": before, "pointer": moved,
            "added": added, "keyboard": keyed, "localReset": reset, "allReset": all_sizes,
        }, indent=2), encoding="utf-8")
    finally:
        page.close()
