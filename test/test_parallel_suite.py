"""The complete suite runs in parallel workers without losing its tier summary or module sharing."""
from collections import Counter
from types import SimpleNamespace

import pytest

import tiers
from conftest import group_by_module


def _config(**attributes):
    return SimpleNamespace(stash=pytest.Stash(), **attributes)


def test_the_controller_summarises_the_tiers_and_skips_its_workers_saw() -> None:
    controller = _config()
    for skips in ([("test/a.py::one", "no browser")], [("test/b.py::two", "no browser")]):
        worker = _config(workeroutput={})
        worker.stash[tiers._TIER_KEY] = {"test/a.py::one": "unit", "test/b.py::two": "browser"}
        worker.stash[tiers._DESELECTED_KEY] = Counter({"browser": 1})
        worker.stash[tiers._SKIPS_KEY] = skips
        tiers.worker_finish(worker)
        tiers.node_down(controller, SimpleNamespace(workeroutput=worker.workeroutput))

    assert controller.stash[tiers._TIER_KEY] == {"test/a.py::one": "unit", "test/b.py::two": "browser"}
    assert controller.stash[tiers._DESELECTED_KEY] == Counter({"browser": 1})
    assert controller.stash[tiers._SKIPS_KEY] == [("test/a.py::one", "no browser"),
                                                 ("test/b.py::two", "no browser")]


def test_a_module_runs_on_one_worker_unless_a_test_names_its_own_group() -> None:
    class Item:
        def __init__(self, nodeid, group=None):
            self.nodeid = nodeid
            self.marks = [pytest.mark.xdist_group(group).mark] if group else []

        def get_closest_marker(self, name):
            return next((mark for mark in self.marks if mark.name == name), None)

        def add_marker(self, marker):
            self.marks.append(marker.mark)

    items = [Item("test/test_a.py::one"), Item("test/test_a.py::two[x]"), Item("test/test_b.py::three", "own")]
    group_by_module(items)

    assert [item.get_closest_marker("xdist_group").args[0] for item in items] == [
        "test/test_a.py", "test/test_a.py", "own"]
