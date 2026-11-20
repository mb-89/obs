"""The browser that draws diagrams: Playwright's headless shell where the installed Playwright
starts it, else an installed Chrome, Edge or Chromium (src/obs/diagram.py, ``_launch``;
input-model, Figure input direction).

Reader: whoever changes which browser draws a diagram. The fake stands for Playwright's
``chromium``: it records each launch and refuses the ones the case says it refuses.
"""
import pytest
from playwright.sync_api import Error as BrowserError

from obs import diagram

INSTALLED = "/usr/bin/installed-chrome"


class Chromium:
    """Playwright's ``chromium``: ``refused`` are the executables (None, its shell) it cannot start."""

    def __init__(self, *refused: str | None) -> None:
        self.refused, self.launched = refused, []

    def launch(self, executable_path: str | None = None) -> str:
        self.launched.append(executable_path)
        if executable_path in self.refused:
            raise BrowserError(f"BrowserType.launch: Executable doesn't exist at {executable_path or 'its shell'}")
        return f"browser {executable_path}"


@pytest.mark.parametrize("installed", [INSTALLED, None])
def test_the_shell_draws_where_the_installed_playwright_starts_it(monkeypatch, installed) -> None:
    monkeypatch.setattr(diagram, "_executable", lambda: installed)
    chromium = Chromium()

    assert diagram._launch(chromium) == "browser None"
    assert chromium.launched == [None]


def test_an_installed_browser_draws_where_the_shell_does_not_start(monkeypatch) -> None:
    monkeypatch.setattr(diagram, "_executable", lambda: INSTALLED)
    chromium = Chromium(None)

    assert diagram._launch(chromium) == f"browser {INSTALLED}"
    assert chromium.launched == [None, INSTALLED]


@pytest.mark.parametrize("refused", [(None,), (None, INSTALLED)], ids=["no installed browser", "neither starts"])
def test_no_browser_that_starts_names_the_remedy(monkeypatch, refused) -> None:
    monkeypatch.setattr(diagram, "_executable", lambda: INSTALLED if INSTALLED in refused else None)

    with pytest.raises(diagram.DiagramError) as failure:
        diagram._launch(Chromium(*refused))

    assert diagram.BROWSER_INSTALL in failure.value.remedy
