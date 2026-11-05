import json
import os
import re
import shutil
from pathlib import Path

import pytest
from filelock import FileLock

import browser_pool
import network_guard
import tiers


_close_browser_pool = browser_pool.install()
network_guard.install()


def pytest_addoption(parser):
    parser.addoption("--gate", action="store_true",
                     help="Run every tier except external: unit, dom, browser and e2e.")


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    tiers.modify_items(config, items)
    group_by_module(items)


def group_by_module(items) -> None:
    """Keep a module's tests on one xdist worker (`--dist loadgroup`), so its module fixtures are
    built once per run; a test with its own ``xdist_group`` mark runs where that group runs."""
    for item in items:
        if not item.get_closest_marker("xdist_group"):
            item.add_marker(pytest.mark.xdist_group(item.nodeid.split("::")[0]))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item, nextitem):
    with network_guard.running(item.nodeid):
        return (yield)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    network_guard.fail(report)
    tiers.make_report(item, report)
    return report


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    tiers.terminal_summary(terminalreporter, config)


def pytest_sessionfinish(session, exitstatus):
    _close_browser_pool()
    tiers.worker_finish(session.config)


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node, error):
    tiers.node_down(node.config, node)


@pytest.fixture(autouse=True, scope="session")
def remembered_schema_validation():
    """Validate each distinct (instance, schema) pair once per session.

    Every render validates the bundled asset index and configuration against their
    schemas; the answer never changes, yet ``jsonschema.validate`` re-checks the schema and
    collects all errors each time. Successes are remembered; failures always re-run.
    """
    from obs_html_interim import config, semantic_assets

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
    from obs_html_interim import cli

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

    from obs_html_interim import cli

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


def built_once(tmp_path_factory, name: str, build) -> Path:
    """The folder ``build(folder)`` fills, built once per run and shared by every xdist worker.

    Workers' temporary folders sit side by side in the run's folder; the first worker to ask
    builds there under a lock and the others wait for it and read what it built.
    """
    root = tmp_path_factory.getbasetemp()
    if os.environ.get("PYTEST_XDIST_WORKER"):
        root = root.parent
    folder = root / name
    with FileLock(f"{folder}.lock"):
        if not (folder / ".built").is_file():
            shutil.rmtree(folder, ignore_errors=True)
            folder.mkdir()
            build(folder)
            (folder / ".built").touch()
    return folder


SPEC_MANIFEST = Path(__file__).parents[1] / "spec" / "manifest.md"
REMOTE_IMAGE = (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml")


@pytest.fixture(scope="session")
def spec_document_file(tmp_path_factory) -> Path:
    """obs's spec as the core's Document JSON, built once per run.

    The remote images its manifest shows are served as a small SVG; any other URL is
    unreachable, as in every test.
    """
    def build(folder: Path) -> None:
        from obs import vault
        from obs.capabilities import build_capability_reference
        from obs.document import build_document

        capabilities = SPEC_MANIFEST.parent / "capabilities"
        served = dict.fromkeys(re.findall(r"!\[[^\]]*\]\((https://[^)]+)\)",
                                          SPEC_MANIFEST.read_text(encoding="utf-8")), REMOTE_IMAGE)

        def fetch(url: str) -> tuple[bytes, str | None]:
            if url not in served:
                raise UnreachableNetwork(f"no network in tests for {url}")
            return served[url]

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(vault, "fetch_remote", fetch)
            document = build_document(SPEC_MANIFEST, build_capability_reference(
                capabilities, capabilities / "coverage.json"))
        (folder / "spec.json").write_text(json.dumps(document), encoding="utf-8")

    return built_once(tmp_path_factory, "spec-document", build) / "spec.json"


@pytest.fixture
def spec_document(spec_document_file: Path) -> dict:
    """obs's spec as the core's Document, built once per run; each test gets its own copy."""
    return json.loads(spec_document_file.read_text(encoding="utf-8"))
