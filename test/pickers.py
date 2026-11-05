"""In-page stand-ins for the browser's file pickers.

The browser's file chooser is a trusted platform API. Tests only need to know that the
document asked for a file and what it does with the file it gets, so the shared browser
pool installs ``STUB_SCRIPT`` in every context:

- ``showOpenFilePicker``/``showSaveFilePicker``/``showDirectoryPicker`` reject at once
  with ``AbortError`` (as if the user cancelled) instead of opening a native dialog;
- while armed by ``choose_files``/``dismiss_file_choice``, clicking a file input records
  the request instead of opening a chooser, and the files are then handed over in-page
  through ``DataTransfer`` with the same ``input``/``change`` (or ``cancel``) events the
  browser fires.

A request that never comes fails within ``timeout`` ms instead of waiting out a chooser
timeout. The real chooser stays covered once, in the e2e tier
(test_guided_card_browser.py::test_inline_fallback_stages_then_applies_atomically).
"""

from __future__ import annotations

import base64
import mimetypes
import time
from pathlib import Path


STUB_SCRIPT = r"""
(() => {
  if (globalThis.__obsHtmlPickers) return;
  const state = globalThis.__obsHtmlPickers = {armed: false, requests: []};
  for (const name of ["showOpenFilePicker", "showSaveFilePicker", "showDirectoryPicker"]) {
    if (typeof globalThis[name] !== "function") continue;
    Object.defineProperty(globalThis, name, {configurable: true, writable: true, value() {
      return Promise.reject(new DOMException(name + " is stubbed by the test harness", "AbortError"));
    }});
  }
  const proto = HTMLInputElement.prototype;
  for (const method of ["click", "showPicker"]) {
    const original = proto[method];
    if (typeof original !== "function") continue;
    Object.defineProperty(proto, method, {configurable: true, writable: true, value(...args) {
      if (state.armed && this.type === "file") {
        state.armed = false;
        state.requests.push(this);
        return undefined;
      }
      return original.apply(this, args);
    }});
  }
})();
"""

_ARM = "() => { __obsHtmlPickers.armed = true; __obsHtmlPickers.requests = []; }"
_PENDING = "() => globalThis.__obsHtmlPickers?.requests.length || 0"
_DISARM = "() => { if (globalThis.__obsHtmlPickers) __obsHtmlPickers.armed = false; }"

_DELIVER = r"""files => {
  const input = __obsHtmlPickers.requests.shift();
  const transfer = new DataTransfer();
  for (const file of files) {
    const binary = atob(file.data), bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    transfer.items.add(new File([bytes], file.name, {type: file.mimeType, lastModified: Date.now()}));
  }
  input.files = transfer.files;
  input.dispatchEvent(new Event("input", {bubbles: true, composed: true}));
  input.dispatchEvent(new Event("change", {bubbles: true}));
}"""

_CANCEL = r"""() => {
  const input = __obsHtmlPickers.requests.shift();
  input.dispatchEvent(new Event("cancel", {bubbles: true}));
}"""


def install(context) -> None:
    """Install the stub in ``context`` (already done for every pooled browser context)."""
    context.add_init_script(STUB_SCRIPT)


def _windows(page):
    # A helper window or Picture-in-Picture card may create the input in another realm.
    pages = [page, *[other for other in page.context.pages if other is not page]]
    return [window for window in pages if not window.is_closed()]


def _requested(page, trigger, timeout: float):
    windows = _windows(page)
    for window in windows:
        window.evaluate(STUB_SCRIPT)
        window.evaluate(_ARM)
    try:
        trigger()
        deadline = time.monotonic() + timeout / 1000
        while True:
            for window in _windows(page):
                if window.evaluate(_PENDING):
                    return window
            if time.monotonic() > deadline:
                raise AssertionError(f"No file input was activated within {timeout} ms.")
            page.wait_for_timeout(10)
    finally:
        for window in _windows(page):
            window.evaluate(_DISARM)


def _payload(item) -> dict:
    if isinstance(item, dict):
        buffer = item["buffer"]
        name, mime = item["name"], item.get("mimeType") or "application/octet-stream"
    else:
        path = Path(item)
        buffer, name = path.read_bytes(), path.name
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return {"name": name, "mimeType": mime, "data": base64.b64encode(buffer).decode("ascii")}


def choose_files(page, trigger, files, *, timeout: float = 2000) -> None:
    """Run ``trigger`` and answer the file input it activates with ``files``.

    ``files`` takes what Playwright's ``FileChooser.set_files`` takes: a path, a
    ``{"name", "mimeType", "buffer"}`` payload, or a list of those.
    """
    items = files if isinstance(files, (list, tuple)) else [files]
    window = _requested(page, trigger, timeout)
    window.evaluate(_DELIVER, [_payload(item) for item in items])


def dismiss_file_choice(page, trigger, *, timeout: float = 2000) -> None:
    """Run ``trigger`` and dismiss the file input it activates, as Escape in the dialog does."""
    window = _requested(page, trigger, timeout)
    window.evaluate(_CANCEL)
