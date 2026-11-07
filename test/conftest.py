import json
import os
import shutil
from pathlib import Path

import pytest

import bounds
import network_guard
import spec_build
import suite
import tiers


network_guard.install()


def pytest_sessionstart(session):
    """In a run of the complete suite the controller starts the run's shared build of obs's spec
    before its workers collect (test/spec_build.py, start). A focused run installs the suite's Node
    test packages where they are missing or stale; the JUnit report, where the run writes one,
    names the part's worker count."""
    spec_build.start(session.config)
    suite.set_up_focused_run(session.config)
    suite.record_workers(session.config)


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    tiers.modify_items(config, items)
    bounds.mark(items)
    group_by_module(items)
    suite.keep_shard(config, items, bounds)
    suite.heaviest_first(suite.ROOT, items)


def group_by_module(items) -> None:
    """Keep a module's tests on one xdist worker (`--dist loadgroup`), so its module fixtures are
    built once per run; a test with its own ``xdist_group`` mark runs where that group runs."""
    for item in items:
        if not item.get_closest_marker("xdist_group"):
            item.add_marker(pytest.mark.xdist_group(item.nodeid.split("::")[0]))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item, nextitem):
    with network_guard.running(item.nodeid), bounds.running(item, os.environ.get(spec_build.RUN_FOLDER)):
        return (yield)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    network_guard.fail(report)
    bounds.explain(item, report)
    tiers.make_report(item, report)
    return report


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    tiers.terminal_summary(terminalreporter, config)


def pytest_sessionfinish(session, exitstatus):
    tiers.worker_finish(session.config)
    spec_build.finish()


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node, error):
    tiers.node_down(node.config, node)


class UnreachableNetwork(OSError):
    """The default fake's refusal: no test reaches the network."""


@pytest.fixture(autouse=True)
def remote_images(monkeypatch):
    """Replace the core's one network read; a test maps a URL to (bytes, media type) to fetch it.

    An unmapped URL fails as an unreachable host does, so no test reaches the network.
    """
    from obs import vault

    served: dict[str, tuple[bytes, str | None]] = {}
    fetched: list[str] = []

    def fetch(url: str) -> tuple[bytes, str | None]:
        fetched.append(url)
        if url not in served:
            raise UnreachableNetwork(f"no network in tests for {url}")
        return served[url]

    monkeypatch.setattr(vault, "fetch_remote", fetch)
    return served, fetched


SPEC_MANIFEST = Path(__file__).parents[1] / "spec" / "manifest.md"
# What the spec's producers write (spec/appendix/references/obs-html-specification.md builds the
# HTML adapter's specification into it); a test that reads the spec without running them gets a
# stand-in there.
SPEC_PRODUCED = ("design_output/obs-html-specification.html",)


@pytest.fixture
def spec_vault(tmp_path) -> Path:
    """A copy of the spec vault, without its generated design_output, holding a stand-in for each
    file its producers write; its manifest is `<copy>/manifest.md`. A test that reads the spec
    without running commands reads this copy, so it never depends on an earlier build."""
    vault = tmp_path / "spec"
    shutil.copytree(SPEC_MANIFEST.parent, vault, ignore=shutil.ignore_patterns("design_output"))
    for produced in SPEC_PRODUCED:
        (vault / produced).parent.mkdir(parents=True, exist_ok=True)
        (vault / produced).write_text("<!doctype html>\n", encoding="utf-8")
    return vault


@pytest.fixture(scope="session")
def spec_document_file(tmp_path_factory) -> Path:
    """obs's spec as the core's Document JSON: the run's one shared build (test/spec_build.py)."""
    return spec_build.built(spec_build.base(tmp_path_factory), "document") / spec_build.DOCUMENT


@pytest.fixture
def spec_document(spec_document_file: Path) -> dict:
    """obs's spec as the core's Document, built once per run; each test gets its own copy."""
    return json.loads(spec_document_file.read_text(encoding="utf-8"))
