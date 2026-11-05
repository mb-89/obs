"""Browser door: PDF printing and the rendered check, through Playwright Chromium."""
from __future__ import annotations

import shutil
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import Iterator, NamedTuple

from playwright.sync_api import (
    ConsoleMessage, Error as BrowserError, Page, TimeoutError as BrowserTimeoutError, sync_playwright,
)
from pypdf import PdfReader

from obs_html.timings import stage


class BrowserFailure(RuntimeError):
    """Raised when no browser can open the HTML."""


class RenderedCheck(NamedTuple):
    status: str
    console_errors: tuple[str, ...]
    pages: int


def _executable() -> str | None:
    """Local Chrome/Edge/Chromium, or None for Playwright's own Chromium."""
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ]
    executable = next((str(path) for path in candidates if path.is_file()), None)
    return executable or next(
        (found for name in ("chromium", "chromium-browser", "google-chrome", "msedge")
         if (found := shutil.which(name))), None,
    )


@contextmanager
def _browser_page(operation: str) -> Iterator[Page]:
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=_executable())
            try:
                yield browser.new_page()
            finally:
                browser.close()
    except BrowserError as error:
        raise BrowserFailure(
            f"{operation} failed. Use installed Chrome/Edge/Chromium or install the Playwright "
            f"browser with 'uv run playwright install chromium'. Details: {error}"
        ) from error


def _print(page: Page) -> bytes:
    """Print through the report runtime's own print book when the page has one."""
    page.evaluate("window.print = () => {}; globalThis.obsPages?.exportPDF()")
    page.emulate_media(media="print")
    return page.pdf(print_background=True, prefer_css_page_size=True)


@stage("print")
def export_pdf(html: Path) -> bytes:
    with _browser_page("PDF export") as page:
        page.goto(html.resolve().as_uri(), wait_until="load")
        page.wait_for_function("!!globalThis.obsPages")
        return _print(page)


def check_rendered(html: Path, timeout_seconds: int) -> RenderedCheck:
    """Open HTML headless as a reader would; count the pages its print path produces."""
    errors: list[str] = []

    def console(message: ConsoleMessage) -> None:
        if message.type == "error":
            location = message.location
            where = f" ({location['url']}:{location['lineNumber']})" if location.get("url") else ""
            errors.append(message.text + where)

    with _browser_page("Rendered check") as page:
        page.on("console", console)
        page.on("pageerror", lambda error: errors.append(f"Uncaught {error}"))
        with stage("open"):
            page.goto(html.resolve().as_uri(), wait_until="load")
            try:
                page.wait_for_function(
                    "['ready', 'error'].includes(document.documentElement.dataset.reportStatus)",
                    timeout=timeout_seconds * 1000,
                )
                status = page.evaluate("document.documentElement.dataset.reportStatus")
            except BrowserTimeoutError:
                status = "timeout"
        pages = 0
        if status == "ready":
            with stage("print"):
                pages = len(PdfReader(BytesIO(_print(page))).pages)
    return RenderedCheck(status, tuple(errors), pages)
