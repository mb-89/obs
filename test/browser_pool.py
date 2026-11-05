"""One Playwright driver and one native browser per test session.

Starting the Playwright driver and launching Chrome costs seconds; tests only need an
isolated profile, which a fresh browser context already provides. ``install()`` replaces
``playwright.sync_api.sync_playwright`` with a lease on the shared session browser, so
existing ``with sync_playwright() as p: p.chromium.launch(...)`` code keeps working while
``launch``/``close`` only open and close that test's own contexts.
"""

from __future__ import annotations

import os
import sys

import pickers


# Waits fail in seconds instead of Playwright's 30 s default; explicit timeouts still win.
DEFAULT_TIMEOUT_MS = int(os.environ.get("OBS_HTML_TEST_TIMEOUT_MS", "5000"))
NAVIGATION_TIMEOUT_MS = int(os.environ.get("OBS_HTML_TEST_NAVIGATION_TIMEOUT_MS", "15000"))
# Opening yields two animation frames per runtime script; headless Chrome otherwise caps
# frames at 60 Hz, which alone costs about half a second per artifact load.
FAST_FRAME_ARGS = ["--disable-frame-rate-limit", "--disable-gpu-vsync"]
BROWSER_VARIABLE = "OBS_HTML_TEST_NATIVE_BROWSER"


class BrowserTierLaunchError(RuntimeError):
    """The browser tier could not start its browser; the message names the remedy."""


def _launch_error(options: dict, error: Exception) -> BrowserTierLaunchError:
    executable = options.get("executable_path")
    source = f"{BROWSER_VARIABLE}={executable!r}" if executable else f"{BROWSER_VARIABLE} is not set"
    detail = str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__
    return BrowserTierLaunchError(
        f"test/browser_pool.py: the browser tier cannot launch a browser ({source}): {detail}\n"
        f"Remedy: set {BROWSER_VARIABLE} to the absolute path of a Chromium or Chrome executable "
        f"(see 'Testing boundaries' in spec/design_input/quality.md), or unset it to skip the browser tier."
    )


class _Pool:
    def __init__(self, factory):
        self._factory = factory
        self._manager = None
        self._playwright = None
        self._browsers = {}

    def playwright(self):
        if self._playwright is None:
            self._manager = self._factory()
            self._playwright = self._manager.start()
        return self._playwright

    def browser(self, kind: str, options: dict):
        key = (kind, tuple(sorted((name, repr(value)) for name, value in options.items())))
        browser = self._browsers.get(key)
        if browser is None or not browser.is_connected():
            launch = dict(options)
            if kind == "chromium" and os.environ.get("OBS_HTML_TEST_FAST_FRAMES", "1") == "1":
                launch["args"] = [*launch.get("args", []), *FAST_FRAME_ARGS]
            from playwright.sync_api import Error as PlaywrightError

            try:
                browser = getattr(self.playwright(), kind).launch(**launch)
            except PlaywrightError as error:
                raise _launch_error(launch, error) from error
            self._browsers[key] = browser
        return browser

    def close(self) -> None:
        for browser in self._browsers.values():
            try:
                browser.close()
            except Exception:
                pass
        self._browsers.clear()
        if self._playwright is not None:
            self._playwright.stop()
        self._manager = self._playwright = None


def _configure(context) -> None:
    context.set_default_timeout(DEFAULT_TIMEOUT_MS)
    context.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
    pickers.install(context)


class BrowserLease:
    """A test's view of the shared browser: closing it closes only its own contexts."""

    def __init__(self, browser):
        self._browser = browser
        self._contexts = []
        self._page_owned = set()

    def new_context(self, **options):
        # Like Browser.new_page, a page-owned context ends with its page.
        for context in [item for item in self._contexts
                        if id(item) in self._page_owned and not item.pages]:
            self._contexts.remove(context)
            self._page_owned.discard(id(context))
            _close_quietly(context)
        context = self._browser.new_context(**options)
        _configure(context)
        self._contexts.append(context)
        return context

    def new_page(self, **options):
        context = self.new_context(**options)
        self._page_owned.add(id(context))
        return context.new_page()

    @property
    def contexts(self):
        return list(self._contexts)

    def close(self, **_options) -> None:
        contexts, self._contexts = self._contexts, []
        self._page_owned.clear()
        for context in contexts:
            _close_quietly(context)

    def __getattr__(self, name):
        return getattr(self._browser, name)


def _close_quietly(context) -> None:
    try:
        context.close()
    except Exception:
        pass


class _BrowserType:
    def __init__(self, pool, playwright, kind, leases):
        self._pool, self._playwright, self._kind, self._leases = pool, playwright, kind, leases

    def launch(self, **options):
        lease = BrowserLease(self._pool.browser(self._kind, options))
        self._leases.append(lease)
        return lease

    def __getattr__(self, name):
        return getattr(getattr(self._playwright, self._kind), name)


class _PlaywrightLease:
    def __init__(self, pool):
        self._pool = pool
        self._leases = []

    def __getattr__(self, name):
        playwright = self._pool.playwright()
        if name in {"chromium", "firefox", "webkit"}:
            return _BrowserType(self._pool, playwright, name, self._leases)
        return getattr(playwright, name)

    def stop(self) -> None:
        leases, self._leases = self._leases, []
        for lease in leases:
            lease.close()


class _SharedSyncPlaywright:
    def __init__(self, pool):
        self._pool = pool
        self._lease = None

    def start(self):
        self._lease = _PlaywrightLease(self._pool)
        return self._lease

    def __enter__(self):
        return self.start()

    def __exit__(self, *_exc) -> None:
        if self._lease is not None:
            self._lease.stop()


_pool = None


def install():
    """Route every ``sync_playwright()`` through the session pool; returns its closer."""
    global _pool
    try:
        import playwright.sync_api as sync_api
    except ImportError:
        return lambda: None
    if _pool is None:
        original = sync_api.sync_playwright
        _pool = _Pool(original)
        shared = lambda: _SharedSyncPlaywright(_pool)  # noqa: E731
        sync_api.sync_playwright = shared
        # Modules imported earlier bound the original name; rebind them too.
        for module in list(sys.modules.values()):
            if getattr(module, "sync_playwright", None) is original:
                module.sync_playwright = shared
    return _pool.close
