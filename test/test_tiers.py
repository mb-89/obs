"""A bare `pytest` (the complete suite) runs every test except the interim adapter's browser and e2e tests."""
from types import SimpleNamespace

import pytest

import tiers
from obs_html_interim.renderer import render_artifact


def _uses_the_interim_renderer():
    return render_artifact


def _runs_the_interim_command():
    return ["obs-html-interim", "--source", "vault"]


def _needs_only_a_browser():
    return "OBS_HTML_TEST_NATIVE_BROWSER"


def _item(name, function, *marks):
    markers = [getattr(pytest.mark, mark).mark for mark in marks]
    return SimpleNamespace(
        nodeid=f"test/test_example.py::{name}", function=function, markers=markers,
        _fixtureinfo=SimpleNamespace(name2fixturedefs={}),
        get_closest_marker=lambda mark: next((marker for marker in markers if marker.name == mark), None),
        iter_markers=lambda mark: [marker for marker in markers if marker.name == mark],
        add_marker=lambda marker: markers.append(getattr(marker, "mark", marker)))


def _config(source=pytest.Config.ArgsSource.TESTPATHS, gate=False):
    return SimpleNamespace(
        stash=pytest.Stash(), args=[], args_source=source, option=SimpleNamespace(markexpr=""),
        getoption=lambda name: gate if name == "gate" else None,
        hook=SimpleNamespace(pytest_deselected=lambda items: None))


def _items():
    """Helpers named by a test count as its evidence: the tests below are marked unit, as they are."""
    return [_item("interim_unit", _uses_the_interim_renderer),
            _item("interim_browser", _uses_the_interim_renderer, "browser"),
            _item("interim_e2e", _runs_the_interim_command, "e2e"),
            _item("browser", _needs_only_a_browser),
            _item("external", _needs_only_a_browser, "external")]


@pytest.mark.unit
def test_a_bare_run_keeps_every_test_but_the_interim_adapters_browser_and_e2e_tests() -> None:
    items = _items()
    tiers.modify_items(_config(), items)

    assert [item.nodeid.split("::")[1] for item in items] == ["interim_unit", "browser"]


@pytest.mark.unit
def test_the_gate_runs_the_interim_adapters_browser_and_e2e_tests_too() -> None:
    items = _items()
    tiers.modify_items(_config(gate=True), items)

    assert [item.nodeid.split("::")[1] for item in items] == [
        "interim_unit", "interim_browser", "interim_e2e", "browser"]


@pytest.mark.unit
@pytest.mark.parametrize(("function", "reaches"), [
    (_uses_the_interim_renderer, True), (_runs_the_interim_command, True), (_needs_only_a_browser, False)])
def test_a_test_reaches_the_interim_adapter_by_a_name_it_uses_or_its_command(function, reaches) -> None:
    sources = tiers._Sources(tiers.Path(__file__).parent)

    assert tiers.reaches_interim(_item("one", function), sources) is reaches


def _decorated(function):
    return function


@_decorated
def _decorated_helper():
    return "OBS_HTML_TEST_NATIVE_BROWSER"


@pytest.mark.unit
def test_every_worker_parses_each_test_module_once_however_many_tests_it_holds(monkeypatch) -> None:
    """Each xdist worker classifies every collected test; reading each function's source by
    tokenizing it again cost every core worker about 2 s of its collection."""
    read = []
    monkeypatch.setattr(tiers.inspect, "getsource",
                        lambda target, _read=tiers.inspect.getsource: read.append(target) or _read(target))
    items = [*_items(), _item("decorated", _decorated_helper)]
    tiers.modify_items(_config(), items)

    assert read == [tiers.sys.modules[__name__]]
    assert [item.nodeid.split("::")[1] for item in items] == ["interim_unit", "browser", "decorated"]


@pytest.mark.unit
def test_a_functions_source_is_what_inspect_reads_decorators_included() -> None:
    import inspect

    module = tiers._Sources(tiers.Path(__file__).parent).module(tiers.sys.modules[__name__])

    assert module.source(_decorated_helper) == inspect.getsource(_decorated_helper)
    assert module.source(_needs_only_a_browser) == inspect.getsource(_needs_only_a_browser)
