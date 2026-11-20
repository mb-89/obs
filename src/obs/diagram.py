"""The diagram door: Mermaid and PlantUML text becomes SVG at build time, in a local browser.

Reader: whoever changes how a diagram figure is drawn, or adds a diagram renderer
(input-model, Figure input direction; capabilities/mermaid and capabilities/plantuml).

Both renderers are JavaScript libraries, pinned in ``diagrams/package-lock.json``; the package's
build installs them from it and ships their files as package data, ``VENDOR``, which this module
reads only through ``importlib.resources`` (hatch_build.py); nothing is fetched while building. They
run in one headless Chromium page (``_launch`` names which) that a Playwright session on its own
thread holds for the whole process (Playwright's sync API allows one session per thread, and a
caller may hold its own), started by the first diagram and closed at exit. The page's origin is a
fake host whose every request this module answers from the installed files; any other request is
refused, so a diagram never reaches the network. A diagram's SVG depends only on its kind and its text: the
same text gives the same SVG, and is drawn once per process.
"""
from __future__ import annotations

import atexit
import hashlib
import json
import queue
import re
import shutil
import threading
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse
from xml.etree import ElementTree


VENDOR = files("obs").joinpath("vendor", "diagrams")
"""The packaged renderers, each file at its path below node_modules (``Renderer.files``)."""
BROWSER_INSTALL = "uv run playwright install chromium"
ORIGIN = "https://obs-diagrams.invalid"


class DiagramError(Exception):
    """A diagram that cannot be drawn: ``problem`` and ``remedy`` complete the caller's message;
    ``line`` is the diagram's 1-based line the renderer names, where it names one."""

    def __init__(self, problem: str, remedy: str, line: int | None = None) -> None:
        super().__init__(problem)
        self.problem, self.remedy, self.line = problem, remedy, line


@dataclass(frozen=True)
class Renderer:
    """One diagram language: the installed files its page loads and how it draws a text."""

    files: dict[str, str]
    """Served path (under ``ORIGIN``) to the file below node_modules; the build packages each one."""
    load: str
    """JavaScript that loads the library into the page, after its classic scripts (``scripts``)."""
    scripts: tuple[str, ...]
    draw: str
    """A JavaScript function of ``[name, text]`` resolving to the SVG markup or rejecting with
    the renderer's message."""
    failed: Callable[[str], DiagramError]
    """The error from the renderer's message, where ``draw`` rejects."""
    drawn_error: Callable[[str], DiagramError | None] = lambda svg: None
    """The error an SVG shows in place of the diagram, where the renderer draws its errors."""


def _mermaid_error(message: str) -> DiagramError:
    match = re.search(r"\bline (\d+)", message)
    lines = [line.strip() for line in message.strip().splitlines() if line.strip()] or ["the renderer gave no message"]
    detail = " ".join(line for line in lines[:4] if line == lines[0] or line.startswith("Expecting"))
    return DiagramError(f"is not a diagram Mermaid can draw: {detail}",
                        "Correct the diagram as Mermaid's message says", int(match[1]) if match else None)


_PLANTUML_ERROR = re.compile(r"\[From \S+ \(line (\d+)\) \]")
"""The line PlantUML names in the drawing it makes of a syntax error instead of the diagram."""


def _plantuml_error(message: str) -> DiagramError:
    first = message.strip().splitlines()[0] if message.strip() else "the renderer gave no message"
    return DiagramError(f"is not a diagram PlantUML can draw: {first}", "Correct the diagram as PlantUML's message says")


def _plantuml_drawn_error(svg: str) -> DiagramError | None:
    match = _PLANTUML_ERROR.search(svg)
    if match is None:
        return None
    texts = [text.strip() for text in re.findall(r">([^<]+)<", svg) if text.strip()]
    message = texts[-1] if texts else "Syntax Error?"
    return DiagramError(f"is not a diagram PlantUML can draw: {message.replace('&gt;', '>').replace('&lt;', '<')}",
                        "Correct the diagram as PlantUML's message says", int(match[1]))


_MERMAID_TYPES = ["sequence", "gantt", "journey", "class", "state", "er", "pie", "quadrantChart", "xyChart",
                  "requirement", "mindmap", "timeline", "gitGraph", "c4", "sankey", "packet", "block",
                  "architecture", "radar", "kanban", "treemap"]
"""Mermaid's diagram types besides the flowchart, each of whose configuration takes useMaxWidth."""


RENDERERS: dict[str, Renderer] = {
    "mermaid": Renderer(
        files={"/mermaid.js": "mermaid/dist/mermaid.min.js"},
        scripts=("/mermaid.js",),
        # Plain SVG text, no HTML labels, so the drawing shows the same as an image and in print;
        # each diagram type at its own size, not stretched to its container.
        load="mermaid.initialize({startOnLoad: false, securityLevel: 'strict', htmlLabels: false,"
             " deterministicIds: true, ...Object.fromEntries(" + json.dumps(_MERMAID_TYPES)
             + ".map(type => [type, {useMaxWidth: false}])), flowchart: {htmlLabels: false, useMaxWidth: false}})",
        draw="async ([name, text]) => (await mermaid.render(name, text)).svg",
        failed=_mermaid_error,
    ),
    "plantuml": Renderer(
        files={"/viz-global.js": "@plantuml/core/viz-global.js", "/plantuml.js": "@plantuml/core/plantuml.js",
               "/themes.js": "@plantuml/core/themes.js"},
        scripts=("/viz-global.js",),
        load="import('/plantuml.js').then(module => { globalThis.obsPlantUml = module; })",
        draw="([name, text]) => new Promise((drawn, failed) =>"
             " obsPlantUml.renderToString(text.split('\\n'), drawn, failed))",
        failed=_plantuml_error,
        drawn_error=_plantuml_drawn_error,
    ),
}
"""The diagram languages, by figure kind; the libraries are in diagrams/package.json."""


def _launch(chromium):
    """The browser that draws: Playwright's headless shell, the one its own launch starts, where
    the installed Playwright starts it; else an installed Chrome, Edge or Chromium (``_executable``).

    The shell drew the fixture diagrams' SVG byte for byte as an installed Chrome did, for less
    CPU: one process drawing test_diagram_figures' Mermaid and PlantUML diagrams took 1.28-1.42 s
    of child CPU with the shell, 1.60-1.66 s with Chrome (Playwright 1.64, three runs each). Python's
    Playwright names no path for its shell, so its launch decides whether that shell exists."""
    from playwright.sync_api import Error as BrowserError

    remedy = f"Use an installed Chrome, Edge or Chromium, or install the Playwright browser with '{BROWSER_INSTALL}'"
    try:
        return chromium.launch()
    except BrowserError as error:
        installed, failed = _executable(), error
    if installed is not None:
        try:
            return chromium.launch(executable_path=installed)
        except BrowserError as error:
            failed = error
    problem = f"cannot be drawn: no browser starts ({str(failed).strip().splitlines()[0]})"
    raise DiagramError(problem, remedy) from failed


def _executable() -> str | None:
    """A local Chrome, Edge or Chromium, or None where none is installed."""
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


class _Session:
    """The one browser page every diagram of this process is drawn in, on its own thread."""

    def __init__(self) -> None:
        self._jobs: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def call(self, job: Callable) -> object:
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="obs-diagrams", daemon=True)
                self._thread.start()
                atexit.register(self.close)
        done: queue.Queue = queue.Queue(maxsize=1)
        self._jobs.put((job, done))
        ok, value = done.get()
        if not ok:
            raise value
        return value

    def close(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._jobs.put(None)
            self._thread.join(timeout=10)

    def _run(self) -> None:
        state: dict[str, object] = {}
        try:
            while (item := self._jobs.get()) is not None:
                job, done = item
                try:
                    done.put((True, job(state)))
                except BaseException as error:  # handed to the caller's thread
                    done.put((False, error))
        finally:
            for name in ("browser", "playwright"):
                try:
                    if name in state:
                        state[name].close() if name == "browser" else state[name].stop()
                except Exception:
                    pass


_SESSION = _Session()


def _page(state: dict[str, object], kind: str):
    """The session's page with ``kind``'s library loaded, started on first use."""
    if "page" not in state:
        # Playwright's own session class, not ``sync_playwright``, which a caller may replace.
        from playwright.sync_api._context_manager import PlaywrightContextManager

        state["playwright"] = PlaywrightContextManager().start()
        state["browser"] = _launch(state["playwright"].chromium)
        page = state["browser"].new_page()
        served = {path: VENDOR.joinpath(*file.split("/"))
                  for renderer in RENDERERS.values() for path, file in renderer.files.items()}

        def answer(route) -> None:
            url = route.request.url
            path = urlparse(url).path
            if url.startswith(ORIGIN + "/") and path == "/":
                route.fulfill(body="<!doctype html><meta charset=utf-8><body>", content_type="text/html")
            elif url.startswith(ORIGIN + "/") and path in served:
                route.fulfill(body=served[path].read_bytes(), content_type="text/javascript")
            else:
                route.abort()

        page.route("**/*", answer)
        page.goto(ORIGIN + "/")
        state["page"], state["loaded"] = page, set()
    page = state["page"]
    if kind not in state["loaded"]:
        renderer = RENDERERS[kind]
        for script in renderer.scripts:
            page.add_script_tag(url=script)
        page.evaluate(f"async () => {{ await {renderer.load}; }}")
        state["loaded"].add(kind)
    return page


XLINK = "http://www.w3.org/1999/xlink"


def _declare_xlink(svg: str) -> str:
    """The SVG with the xlink prefix declared on its root where it uses the prefix undeclared, as
    Mermaid's markup of a ``click`` link does (an ``xlink:href`` it serializes as HTML)."""
    if "xlink:" not in svg or "xmlns:xlink" in svg or not svg.startswith("<svg"):
        return svg
    return f'<svg xmlns:xlink="{XLINK}"{svg[4:]}'


@cache
def render(kind: str, text: str) -> str:
    """The SVG markup of the diagram ``text`` of ``kind`` (a key of ``RENDERERS``)."""
    renderer = RENDERERS[kind]
    name = "diagram-" + hashlib.sha256(f"{kind}\n{text}".encode("utf-8")).hexdigest()[:12]

    def draw(state: dict[str, object]) -> str:
        from playwright.sync_api import Error as BrowserError

        page = _page(state, kind)
        try:
            return page.evaluate(renderer.draw, [name, text])
        except BrowserError as error:
            raise renderer.failed(str(error).split("Error: ", 1)[-1]) from None

    svg = _SESSION.call(draw)
    error = renderer.drawn_error(svg)
    if error is not None:
        raise error
    svg = _declare_xlink(svg)
    try:
        root = ElementTree.fromstring(svg)
    except ElementTree.ParseError:
        root = None
    if root is None or root.tag != "{http://www.w3.org/2000/svg}svg":
        raise DiagramError(f"cannot be drawn: the {kind} renderer gave no SVG drawing",
                           "Rebuild the obs package, whose build installs the renderers from "
                           "src/obs/diagrams/package-lock.json")
    return svg
