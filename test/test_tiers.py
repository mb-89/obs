"""A bare `pytest` (the complete suite) runs every test except the external tier's."""
from types import SimpleNamespace

import pytest

import tiers


def _needs_nothing():
    return "unit"


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


def _config(args=()):
    return SimpleNamespace(
        stash=pytest.Stash(), args=list(args), option=SimpleNamespace(markexpr=""),
        hook=SimpleNamespace(pytest_deselected=lambda items: None))


def _items():
    """Helpers named by a test count as its evidence: the tests below are marked as they are."""
    return [_item("unit", _needs_nothing),
            _item("browser", _needs_only_a_browser),
            _item("external", _needs_only_a_browser, "external")]


@pytest.mark.unit
def test_a_bare_run_keeps_every_test_but_the_external_ones() -> None:
    items = _items()
    tiers.modify_items(_config(), items)

    assert [item.nodeid.split("::")[1] for item in items] == ["unit", "browser"]
    assert [name for item in items for name in (getattr(marker, "name", marker) for marker in item.markers)
            if name in tiers.TIERS] == [
        "unit", "browser"]


@pytest.mark.unit
def test_an_external_test_named_by_its_node_id_runs() -> None:
    items = _items()
    tiers.modify_items(_config(["test/test_example.py::external"]), items)

    assert [item.nodeid.split("::")[1] for item in items] == ["unit", "browser", "external"]


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
    assert [item.nodeid.split("::")[1] for item in items] == ["unit", "browser", "decorated"]


@pytest.mark.unit
def test_a_functions_source_is_what_inspect_reads_decorators_included() -> None:
    import inspect

    module = tiers._Sources(tiers.Path(__file__).parent).module(tiers.sys.modules[__name__])

    assert module.source(_decorated_helper) == inspect.getsource(_decorated_helper)
    assert module.source(_needs_only_a_browser) == inspect.getsource(_needs_only_a_browser)
