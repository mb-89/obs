import json
import os

import pytest

from obs_html_interim.cli import main
from obs_html_interim.artifact_data import decode_artifact_data
from test_named_icons import PIXEL


@pytest.mark.parametrize("value", [0, 1, -0.1, 1.1, "0.45", True])
@pytest.mark.parametrize("check", [False, True])
def test_inactive_icon_opacity_rejects_invalid_config(tmp_path, value, check):
    source = tmp_path / "source"
    source.mkdir()
    (source / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (source / "chapter.md").write_text("# Chapter\n", encoding="utf-8")
    (source / "cfg.json").write_text(
        json.dumps({"artifact": {"inactiveIconOpacity": value}}), encoding="utf-8",
    )
    with pytest.raises(SystemExit) as failure:
        main(["--source", str(source), "--output", str(tmp_path / "invalid.html")] +
             (["--check"] if check else []))
    assert failure.value.code == 2
    assert not (tmp_path / "invalid.html").exists()


@pytest.mark.parametrize("override", [None, 0.3])
def test_native_inactive_icon_opacity_is_icon_only_across_media(tmp_path, override):
    if not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"):
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for computed icon checks.")
    from playwright.sync_api import sync_playwright

    source = tmp_path / "source"
    source.mkdir()
    (source / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (source / "chapter.md").write_text("# Chapter\n", encoding="utf-8")
    (source / "pixel.png").write_bytes(PIXEL)
    (source / "mono.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<path d="M1 1h8v8H1z"/></svg>', encoding="utf-8",
    )
    assets = {"schemaVersion": 1, "assets": {
        "sample": {"type": "appearance", "defaultState": "active",
                   "states": {"active": {}, "inactive": {}}, "children": {
                       kind: {"icon": {"ref": f"sample-{kind}"}} for kind in ("glyph", "image", "mono")
                   }},
        "sample-glyph": {"type": "icon", "value": {"glyph": "🧪"}},
        "sample-image": {"type": "icon", "value": {"asset": "pixel.png"}},
        "sample-mono": {"type": "icon", "value": {"asset": "mono.svg", "monochrome": True}},
    }}
    (source / "assets.json").write_text(json.dumps(assets), encoding="utf-8")
    settings = {"assetIndex": "assets.json"}
    if override is not None:
        settings["inactiveIconOpacity"] = override
    (source / "cfg.json").write_text(json.dumps({"artifact": settings}), encoding="utf-8")
    output = tmp_path / "icons.html"
    args = ["--source", str(source), "--output", str(output)]
    assert main(args + ["--check"]) == 0
    assert main(args) == 0
    expected = override if override is not None else 0.45
    assert decode_artifact_data(output.read_text(encoding="utf-8"))["inactiveIconOpacity"] == expected
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"])
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(output.as_uri())
            page.evaluate("""() => {
                for (const kind of ['glyph', 'image', 'mono']) {
                    for (const state of ['active', 'inactive']) {
                        const button = document.createElement('button');
                        button.className = 'data-table-icon-action';
                        button.dataset.sample = `${kind}-${state}`;
                        button.title = 'Explanation stays readable';
                        button.setAttribute('aria-label', button.title);
                        button.disabled = state === 'inactive';
                        obsAssets.append(button, `sample.${kind}`, state);
                        const label = document.createElement('span');
                        label.textContent = button.title;
                        button.append(label);
                        document.body.append(button);
                    }
                }
            }""")
            for theme, media in [("light", "screen"), ("dark", "screen"), ("dark", "print")]:
                page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
                page.emulate_media(media=media)
                for kind in ("glyph", "image", "mono"):
                    for state in ("active", "inactive"):
                        button = page.locator(f'[data-sample="{kind}-{state}"]')
                        icon = button.locator("[data-icon]")
                        assert float(icon.evaluate("e => getComputedStyle(e).opacity")) == (
                            expected if state == "inactive" else 1
                        )
                        assert button.evaluate("e => getComputedStyle(e).opacity") == "1"
                        assert button.locator("span").last.evaluate("e => getComputedStyle(e).opacity") == "1"
                        assert button.is_disabled() == (state == "inactive")
                        assert button.get_attribute("aria-label") == "Explanation stays readable"
                page.screenshot(path=str(tmp_path / f"icons-{theme}-{media}.png"))
            assert errors == []
        finally:
            browser.close()
