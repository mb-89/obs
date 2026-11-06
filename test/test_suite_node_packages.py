"""The complete suite's setup (`test/suite.py --setup`, se.toml's `[tests] setup`) installs its Node
test packages, only when a package's `node_modules` is missing or was installed from another
lockfile, and the browser tests' engine where Playwright's browsers folder holds none; the suite
itself installs nothing and refuses to run without its packages. npm and Playwright are faked: no
test reaches the network."""
import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import suite


def _package(root: Path, name: str, lockfile: str = '{"lockfileVersion": 3}') -> Path:
    package = root / name / "test" / "browser"
    package.mkdir(parents=True)
    (package / "package-lock.json").write_text(lockfile, encoding="utf-8")
    return package


@pytest.fixture(autouse=True)
def npm_on_path(monkeypatch) -> None:
    monkeypatch.setattr(suite.shutil, "which", lambda name: f"/fake/bin/{name}")


@pytest.fixture
def browsers(tmp_path, monkeypatch) -> Path:
    """Playwright's browsers folder, empty, as the setup finds it."""
    folder = tmp_path / "ms-playwright"
    folder.mkdir()
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(folder))
    return folder


def _shell(browsers: Path, revision: int = 1248) -> Path:
    revision_folder, platform, executable = suite.HEADLESS_SHELL
    path = browsers / revision_folder.replace("*", str(revision)) / platform.replace("*", "linux64") / executable
    path.parent.mkdir(parents=True)
    path.write_text("", encoding="utf-8")
    return path


class FakePlaywright:
    """Records each `playwright install` and, where it succeeds, installs the shell."""

    def __init__(self, browsers: Path, returncode: int = 0) -> None:
        self.browsers, self.returncode = browsers, returncode
        self.calls: list[list[str]] = []

    def __call__(self, command, **_):
        self.calls.append(command)
        if self.returncode == 0:
            _shell(self.browsers)
        return subprocess.CompletedProcess(command, self.returncode, stdout="playwright said why\n")


class FakeNpm:
    """Records each `npm ci` and does what it does to `node_modules`: replaces it."""

    def __init__(self, returncode: int = 0) -> None:
        self.calls: list[tuple[list[str], Path]] = []
        self.returncode = returncode

    def __call__(self, command, cwd, **_):
        self.calls.append((command, Path(cwd)))
        if self.returncode == 0:
            (Path(cwd) / "node_modules").mkdir(exist_ok=True)
        return subprocess.CompletedProcess(command, self.returncode, stdout="npm said why\n")


def test_the_suite_checks_every_part_lockfile_it_depends_on() -> None:
    assert suite.NODE_PACKAGES == [suite.ROOT / "adapters" / "html" / "test" / "browser"]


def test_a_missing_node_modules_is_installed_and_remembers_its_lockfile(tmp_path) -> None:
    package = _package(tmp_path, "core")
    npm = FakeNpm()

    assert suite.install_node_packages([package], run=npm) == [package]

    assert [cwd for _, cwd in npm.calls] == [package]
    assert npm.calls[0][0] == ["/fake/bin/npm", "ci"]
    lockfile_hash = hashlib.sha256((package / "package-lock.json").read_bytes()).hexdigest()
    assert (package / "node_modules" / suite.INSTALLED_LOCKFILE).read_text(encoding="utf-8") == lockfile_hash


def test_a_package_installed_from_the_same_lockfile_is_not_installed_again(tmp_path) -> None:
    package = _package(tmp_path, "core")
    suite.install_node_packages([package], run=FakeNpm())
    npm = FakeNpm()

    assert suite.install_node_packages([package], run=npm) == []
    assert npm.calls == []


@pytest.mark.parametrize("stale", ["changed lockfile", "no marker"])
def test_a_package_installed_from_another_lockfile_is_installed_again(tmp_path, stale) -> None:
    package = _package(tmp_path, "core")
    suite.install_node_packages([package], run=FakeNpm())
    if stale == "changed lockfile":
        (package / "package-lock.json").write_text('{"lockfileVersion": 3, "x": 1}', encoding="utf-8")
    else:
        (package / "node_modules" / suite.INSTALLED_LOCKFILE).unlink()
    npm = FakeNpm()

    assert suite.install_node_packages([package], run=npm) == [package]
    assert [cwd for _, cwd in npm.calls] == [package]


def test_a_failed_install_names_the_lockfile_and_the_command_to_run_by_hand(tmp_path) -> None:
    package = _package(tmp_path, "core")

    with pytest.raises(suite.InstallError) as raised:
        suite.install_node_packages([package], run=FakeNpm(returncode=1))

    message = str(raised.value)
    assert str(package / "package-lock.json") in message
    assert f"npm --prefix {package} ci" in message
    assert not (package / "node_modules" / suite.INSTALLED_LOCKFILE).exists()


def test_without_npm_the_install_names_the_lockfile_and_the_command(tmp_path, monkeypatch) -> None:
    package = _package(tmp_path, "core")
    monkeypatch.setattr(suite.shutil, "which", lambda name: None)

    with pytest.raises(suite.InstallError) as raised:
        suite.install_node_packages([package], run=FakeNpm())

    assert str(package / "package-lock.json") in str(raised.value)
    assert f"npm --prefix {package} ci" in str(raised.value)


def test_a_missing_browser_is_installed_with_playwright(browsers) -> None:
    playwright = FakePlaywright(browsers)

    assert suite.install_browser(browsers, run=playwright) is True

    assert playwright.calls == [suite.BROWSER_INSTALL]
    assert suite.BROWSER_INSTALL[-2:] == ["install", "chromium-headless-shell"]
    assert suite.headless_shell(browsers) is not None


def test_an_installed_browser_is_not_downloaded_again(browsers) -> None:
    _shell(browsers, revision=1243)
    playwright = FakePlaywright(browsers)

    assert suite.install_browser(browsers, run=playwright) is False
    assert playwright.calls == []


def test_a_failed_browser_install_names_the_command_and_the_folder(browsers) -> None:
    with pytest.raises(suite.InstallError) as raised:
        suite.install_browser(browsers, run=FakePlaywright(browsers, returncode=1))

    assert " ".join(suite.BROWSER_INSTALL) in str(raised.value)
    assert str(browsers) in str(raised.value)


def test_setup_installs_the_browser_into_playwrights_folder(monkeypatch, browsers, capsys) -> None:
    monkeypatch.setattr(suite, "install_node_packages", lambda packages: [])
    installed = []
    monkeypatch.setattr(suite, "install_browser", lambda folder: installed.append(folder) or True)

    assert suite.main(["--setup"]) == 0

    assert installed == [browsers]
    assert str(browsers) in capsys.readouterr().out


def test_setup_installs_the_node_packages_and_runs_no_part(monkeypatch, capsys) -> None:
    ticks = iter([0.0, 7.0])
    monkeypatch.setattr(suite, "install_node_packages", lambda packages: list(packages))
    monkeypatch.setattr(suite, "install_browser", lambda browsers: False)
    monkeypatch.setattr(suite, "run_part", lambda part, arguments, run_folder: pytest.fail("a part ran"))

    assert suite.main(["--setup"], clock=lambda: next(ticks)) == 0

    assert ("installed Node test packages adapters/html/test/browser in 7.0 s") in capsys.readouterr().out


def test_setup_takes_no_other_arguments(monkeypatch, capsys) -> None:
    monkeypatch.setattr(suite, "install_node_packages", lambda packages: pytest.fail("installed"))

    assert suite.main(["--setup", "-x"]) == 2
    assert "test/suite.py --setup" in capsys.readouterr().err


def test_a_failed_setup_names_the_lockfile(monkeypatch, capsys) -> None:
    monkeypatch.setattr(suite, "install_browser", lambda browsers: pytest.fail("installed a browser"))
    def install(packages):
        raise suite.InstallError("npm ci failed for /x/package-lock.json")

    monkeypatch.setattr(suite, "install_node_packages", install)

    assert suite.main(["--setup"]) == 1
    assert "/x/package-lock.json" in capsys.readouterr().err


def test_the_suite_installs_nothing_and_runs_its_parts_when_set_up(monkeypatch) -> None:
    order = []
    monkeypatch.setattr(suite, "is_installed", lambda package: True)
    monkeypatch.setattr(suite, "install_node_packages", lambda packages: pytest.fail("installed"))
    monkeypatch.setattr(suite, "run_part", lambda part, arguments, run_folder: order.append("part") or (0, ""))

    assert suite.main([]) == 0
    assert order == ["part"] * len(suite.PARTS)


def test_the_suite_without_setup_runs_no_part_and_names_the_setup_command(monkeypatch, capsys) -> None:
    stale = suite.NODE_PACKAGES[-1]
    monkeypatch.setattr(suite, "is_installed", lambda package: package != stale)
    monkeypatch.setattr(suite, "install_node_packages", lambda packages: pytest.fail("installed"))
    monkeypatch.setattr(suite, "run_part", lambda part, arguments, run_folder: pytest.fail("a part ran"))

    assert suite.main([]) == 1
    error = capsys.readouterr().err
    assert str(stale / "package-lock.json") in error
    assert "uv run python test/suite.py --setup" in error
    assert "[tests] setup" in error


def test_se_runs_the_setup_command_before_the_suite() -> None:
    import tomllib

    tests = tomllib.loads((suite.ROOT / "se.toml").read_text(encoding="utf-8"))["tests"]
    assert tests["setup"] == ["uv", "run", "python", "test/suite.py", "--setup"]


def test_a_focused_run_installs_the_packages_not_installed_from_their_lockfiles(tmp_path) -> None:
    fresh, stale = _package(tmp_path, "fresh"), _package(tmp_path, "stale")
    suite.install_node_packages([fresh], run=FakeNpm())
    npm = FakeNpm()

    assert suite.set_up_focused_run(SimpleNamespace(), [fresh, stale], run=npm) == [stale]
    assert [cwd for _, cwd in npm.calls] == [stale]


def test_an_xdist_worker_leaves_the_setup_to_its_controller(tmp_path) -> None:
    npm = FakeNpm()

    assert suite.set_up_focused_run(SimpleNamespace(workerinput={}), [_package(tmp_path, "core")], run=npm) == []
    assert npm.calls == []


def test_a_focused_run_whose_install_fails_stops_naming_the_lockfile(tmp_path) -> None:
    package = _package(tmp_path, "core")

    with pytest.raises(pytest.exit.Exception) as stopped:
        suite.set_up_focused_run(SimpleNamespace(), [package], run=FakeNpm(returncode=1))

    assert str(package / "package-lock.json") in str(stopped.value)


def test_the_cores_session_start_sets_up_a_focused_run(monkeypatch) -> None:
    import conftest

    seen = []
    monkeypatch.setattr(suite, "set_up_focused_run", lambda config: seen.append(("set up", config)))
    monkeypatch.setattr(suite, "record_workers", lambda config: seen.append(("workers", config)))
    config = SimpleNamespace()
    conftest.pytest_sessionstart(SimpleNamespace(config=config))

    assert seen == [("set up", config), ("workers", config)]
