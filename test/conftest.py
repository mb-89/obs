import json
import os
from pathlib import Path

import pytest

import browser_pool
import tiers


_close_browser_pool = browser_pool.install()


def pytest_addoption(parser):
    parser.addoption("--gate", action="store_true",
                     help="Run every tier except external: unit, dom, browser and e2e.")


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    tiers.modify_items(config, items)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    tiers.make_report(item, report)
    return report


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    tiers.terminal_summary(terminalreporter, config)


def pytest_sessionfinish(session, exitstatus):
    _close_browser_pool()


@pytest.fixture(autouse=True, scope="session")
def remembered_schema_validation():
    """Validate each distinct (instance, schema) pair once per session.

    Every render validates the bundled asset index and configuration against their
    schemas; the answer never changes, yet ``jsonschema.validate`` re-checks the schema and
    collects all errors each time. Successes are remembered; failures always re-run.
    """
    from obs_html import config, semantic_assets

    valid = set()

    def remembered(original):
        def validate(*args, **kwargs):
            instance = kwargs["instance"] if "instance" in kwargs else args[0]
            schema = kwargs["schema"] if "schema" in kwargs else args[1]
            key = json.dumps([instance, schema], sort_keys=True, default=repr)
            if key not in valid:
                original(*args, **kwargs)
                valid.add(key)
        return validate

    with pytest.MonkeyPatch.context() as patch:
        for module in (config, semantic_assets):
            patch.setattr(module, "validate", remembered(module.validate))
        yield


@pytest.fixture(autouse=True, scope="session")
def remembered_generator_provenance():
    """Describe this checkout with git once per session instead of three git calls per build.

    Other paths (the vaults tests create and modify) are still asked every time.
    """
    from obs_html import cli

    describe = cli._repository_provenance
    checkout = cli.PROJECT_ROOT.resolve()
    remembered = {}

    def provenance(path):
        if Path(path).resolve() != checkout:
            return describe(path)
        if "value" not in remembered:
            remembered["value"] = describe(path)
        return dict(remembered["value"])

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(cli, "_repository_provenance", provenance)
        yield


@pytest.fixture(autouse=True, scope="session")
def remembered_written_artifacts():
    """Serve a just-built artifact from memory while its file is unchanged.

    On the managed Windows machines the first read of each freshly written HTML file is
    held for an on-access antivirus scan of the embedded scripts (about 0.75 s for a small
    artifact). Tests read the artifact they just built, so the bytes are already known.
    The file stays the source of truth: any change in size or mtime falls back to disk.
    """
    import io
    from collections import OrderedDict

    from obs_html import cli

    written: OrderedDict[str, tuple[int, int, bytes]] = OrderedDict()
    write_if_changed = cli._write_if_changed
    read_bytes = Path.read_bytes
    read_text = Path.read_text

    def write(output_path, content, *args, **kwargs):
        if not write_if_changed(output_path, content, *args, **kwargs):
            return False
        stat = Path(output_path).stat()
        data = content if isinstance(content, bytes) else content.encode("utf-8")
        key = os.path.normcase(os.path.abspath(output_path))
        written[key] = (stat.st_size, stat.st_mtime_ns, data)
        written.move_to_end(key)
        while len(written) > 24:
            written.popitem(last=False)
        return True

    def remembered(path):
        entry = written.get(os.path.normcase(os.path.abspath(path)))
        if entry is None:
            return None
        try:
            stat = os.stat(path)
        except OSError:
            return None
        return entry[2] if (stat.st_size, stat.st_mtime_ns) == entry[:2] else None

    def cached_read_bytes(self):
        data = remembered(self)
        return read_bytes(self) if data is None else data

    def cached_read_text(self, encoding=None, errors=None, newline=None):
        data = remembered(self)
        if data is None:
            return read_text(self, encoding=encoding, errors=errors, newline=newline)
        if encoding is None:
            encoding = io.text_encoding(None)
        return io.TextIOWrapper(io.BytesIO(data), encoding=encoding, errors=errors, newline=newline).read()

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(cli, "_write_if_changed", write)
        patch.setattr(Path, "read_bytes", cached_read_bytes)
        patch.setattr(Path, "read_text", cached_read_text)
        yield


@pytest.fixture(autouse=True)
def native_artifact_readiness(monkeypatch):
    """The native navigation adapter includes the artifact's async startup boundary."""
    if not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"):
        return
    from playwright.sync_api import Page

    def ready(navigate):
        def wrapped(page, *args, **kwargs):
            response = navigate(page, *args, **kwargs)
            if page.evaluate("Boolean(globalThis.obsHtmlReady)"):
                page.wait_for_function(
                    "['ready', 'error'].includes(document.documentElement.dataset.artifactStatus)",
                )
            return response

        return wrapped

    monkeypatch.setattr(Page, "goto", ready(Page.goto))
    monkeypatch.setattr(Page, "reload", ready(Page.reload))


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
