"""Browser and PDF door: PDF export, source attachment and the rendered check."""
from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
import shutil
from typing import Iterator, NamedTuple

from playwright.sync_api import (
    ConsoleMessage, Error as BrowserError, Page, TimeoutError as BrowserTimeoutError, sync_playwright,
)
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError
from pypdf.generic import create_string_object, NameObject

from obs_html.content import ContentError
from obs_html.reproduction import ARCHIVE_NAME, embedded_archive
from obs_html.timings import stage


@stage("attach")
def attach_archive(pdf: bytes, archive: bytes) -> bytes:
    try:
        reader = PdfReader(BytesIO(pdf), strict=True)
        if reader.is_encrypted:
            raise ContentError("Cannot attach sources to an encrypted PDF.")
        if reader.trailer["/Root"].get("/Perms") or any(
            field.get("/FT") == "/Sig" for field in (reader.get_fields() or {}).values()
        ):
            raise ContentError("Cannot modify a signed PDF.")
        if ARCHIVE_NAME in reader.attachments:
            raise ContentError(f"PDF already contains {ARCHIVE_NAME}.")
        writer = PdfWriter(clone_from=reader)
        attachment = writer.add_attachment(ARCHIVE_NAME, archive)
        attachment.subtype = NameObject("/application/zip")
        attachment.description = create_string_object("Source inputs and generator for this document")
        output = BytesIO()
        writer.write(output)
        return output.getvalue()
    except PdfReadError as error:
        raise ContentError(f"Cannot read PDF: {error}") from error


class RenderedCheck(NamedTuple):
    status: str
    console_errors: tuple[str, ...]
    pages: int


@contextmanager
def _browser_page(operation: str) -> Iterator[Page]:
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ]
    executable = next((str(path) for path in candidates if path.is_file()), None)
    executable = executable or next(
        (found for name in ("chromium", "chromium-browser", "google-chrome", "msedge")
         if (found := shutil.which(name))), None,
    )
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=executable)
            try:
                yield browser.new_page()
            finally:
                browser.close()
    except BrowserError as error:
        raise ContentError(
            f"{operation} failed. Use installed Chrome/Edge/Chromium or install the Playwright "
            f"browser with 'uv run playwright install chromium'. Details: {error}"
        ) from error


def _print(page: Page) -> bytes:
    page.evaluate("window.print = () => {}; globalThis.obsPages.exportPDF()")
    page.emulate_media(media="print")
    return page.pdf(print_background=True, prefer_css_page_size=True)


@stage("print")
def export_pdf(html: Path) -> bytes:
    archive = embedded_archive(html.read_text(encoding="utf-8"))
    with _browser_page("PDF export") as page:
        page.goto(html.resolve().as_uri(), wait_until="load")
        page.wait_for_function("!!globalThis.obsPages")
        pdf = _print(page)
    return attach_archive(pdf, archive) if archive is not None else pdf


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
