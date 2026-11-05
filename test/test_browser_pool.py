"""The browser tier's launch failure names its variable and remedy instead of Playwright's raw error."""

import pytest

import browser_pool


VARIABLE = "OBS_HTML_TEST_NATIVE_BROWSER"


class _RefusingType:
    def launch(self, **_options):
        from playwright.sync_api import Error

        raise Error("BrowserType.launch: Executable doesn't exist at /ms-playwright/chromium_headless_shell")


class _RefusingPlaywright:
    chromium = _RefusingType()

    def start(self):
        return self

    def stop(self):
        pass


@pytest.mark.unit
@pytest.mark.parametrize("options", [{}, {"executable_path": "/missing/chromium"}])
def test_launch_failure_names_variable_and_remedy(options):
    pool = browser_pool._Pool(_RefusingPlaywright)

    with pytest.raises(browser_pool.BrowserTierLaunchError) as raised:
        pool.browser("chromium", options)

    message = str(raised.value)
    assert message.startswith("test/browser_pool.py:")
    assert VARIABLE in message
    assert "absolute path of a Chromium or Chrome executable" in message
    assert "quality.md" in message
    assert "Executable doesn't exist" in message
    assert options.get("executable_path", "is not set") in message


@pytest.mark.browser
def test_real_launch_of_missing_executable_names_variable(tmp_path):
    missing = tmp_path / "no-chromium"
    pool = browser_pool._Pool(browser_pool._pool._factory)
    try:
        with pytest.raises(browser_pool.BrowserTierLaunchError) as raised:
            pool.browser("chromium", {"executable_path": str(missing)})
    finally:
        pool.close()

    assert VARIABLE in str(raised.value)
    assert str(missing) in str(raised.value)
