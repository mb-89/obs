import os
import re
from pathlib import Path

import pytest

from obs_html_interim.content import parse_manifest
from obs_html_interim.renderer import render_artifact
from obs_html_interim.artifact_data import ARTIFACT_PATTERN, decode_artifact_data, encode_artifact_data, prepare_artifact_scripts


@pytest.fixture
def transport_page(tmp_path: Path):
    executable = os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER")
    if not executable:
        pytest.skip("Set OBS_HTML_TEST_NATIVE_BROWSER for canonical transport checks.")
    from playwright.sync_api import sync_playwright

    (tmp_path / "chapter.md").write_text("---\nstatus: draft\n---\n# Chapter\n\n" + "Content. " * 120)
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n")
    artifact = tmp_path / "artifact.html"
    artifact.write_text(render_artifact(manifest, parse_manifest(manifest)), encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable)
        context = browser.new_context()
        page = context.new_page()
        page.on("dialog", lambda dialog: dialog.accept())
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(artifact.as_uri())
        page.evaluate("obsHtmlReady")
        try:
            yield page, artifact
        finally:
            browser.close()
        assert errors == []


def test_current_reviewed_snapshot_and_pending_save_race(transport_page) -> None:
    page, artifact = transport_page
    result = page.evaluate("""async () => {
        obsArtifact.commitCanonicalProjection([{slug: "chapter", fields: {status: "reviewed"}}]);
        const original = obsArtifactTransport.encode;
        let release;
        let captured;
        const captureReached = new Promise(resolve => { captured = resolve; });
        const pending = new Promise(resolve => { release = resolve; });
        const transport = obsArtifactTransport;
        globalThis.obsArtifactTransport = {...transport,
            writeIsland: async (...args) => {
                captured(); await pending; return transport.writeIsland(...args);
            }};
        let activation = false;
        let closed = false;
        let contents;
        globalThis.showSaveFilePicker = () => {
            activation = navigator.userActivation.isActive;
            return Promise.resolve({createWritable: async () => ({
                write: async value => { contents = value; }, close: async () => { closed = true; },
            })});
        };
        document.querySelector("[data-comment-save]").click();
        await captureReached;
        obsArtifact.commitCanonicalProjection([{slug: "chapter", fields: {status: "later"}}]);
        release();
        for (let i=0; i<100 && !closed; i++) await new Promise(resolve => setTimeout(resolve, 10));
        return {contents, closed, activation,
            dirty: document.querySelector("[data-review-save-guidance]").dataset.dirty};
    }""")
    assert result["closed"] is True
    assert result["activation"] is True
    assert result["dirty"] == "true"
    model = decode_artifact_data(result["contents"])
    assert next(note for note in model["notes"] if note["slug"] == "chapter")["frontmatter"]["status"] == "reviewed"
    assert 'data-encoding="gzip"' in result["contents"]
    assert 'src="blob:' not in result["contents"]
    assert 'href="blob:' not in result["contents"]
    body = re.search(r'<div\b[^>]*data-chapter-body[^>]*>(.*?)</div>', result["contents"], re.S)
    assert body and body[1] == ""
    saved = artifact.with_name("reviewed.html")
    saved.write_text(result["contents"], encoding="utf-8")
    reopened = page.context.new_page()
    reopened.goto(saved.as_uri())
    reopened.evaluate("obsHtmlReady")
    assert reopened.evaluate("JSON.parse(obsArtifact.serializeModel()).notes.find(n=>n.slug==='chapter').frontmatter.status") == "reviewed"
    reopened.close()


@pytest.mark.parametrize("failure", ["cancel", "write", "close", "compression", "download"])
def test_failed_save_retains_dirty_state(transport_page, failure: str) -> None:
    page, _ = transport_page
    page.evaluate("""failure => {
        obsArtifact.commitCanonicalProjection([{slug: "chapter", fields: {status: "changed"}}]);
        globalThis.showSaveFilePicker = async () => {
            if (failure === "cancel") throw new DOMException("Cancelled", "AbortError");
            return {createWritable: async () => ({
                write: async () => { if (failure === "write") throw new Error("Write failed"); },
                close: async () => { if (failure === "close") throw new Error("Close failed"); },
            })};
        };
        if (failure === "compression") globalThis.obsArtifactTransport = {
            ...obsArtifactTransport, writeIsland: async () => { throw new Error("Compression failed"); },
        };
        if (failure === "download") delete globalThis.showSaveFilePicker;
        obsArtifact.openBar("comments", "right");
    }""", failure)
    page.locator("[data-comment-save]").click()
    if failure in {"write", "close", "download"}:
        page.wait_for_function("document.querySelector('[data-comment-announcer]').textContent.includes('cannot confirm')")
    elif failure != "cancel":
        page.wait_for_function("document.querySelector('[data-comment-announcer]').textContent.includes('could not be saved')")
    assert page.locator("[data-review-save-guidance]").get_attribute("data-dirty") == "true"


@pytest.mark.parametrize("damage", ["missing", "unsupported", "corrupt", "unsupported-browser"])
def test_invalid_transport_is_visible_without_starting_consumers(transport_page, damage: str) -> None:
    page, artifact = transport_page
    html = artifact.read_text(encoding="utf-8")
    if damage == "missing":
        html = ARTIFACT_PATTERN.sub("", html, count=1)
    elif damage == "unsupported":
        html = ARTIFACT_PATTERN.sub(
            lambda match: match[0].replace('data-encoding="gzip"', 'data-encoding="br"', 1),
            html, count=1,
        )
    elif damage == "corrupt":
        html = ARTIFACT_PATTERN.sub(lambda match: match[1] + "invalid!" + match[3], html, count=1)
    broken = artifact.with_name(f"{damage}.html")
    broken.write_text(html, encoding="utf-8")
    checked = page.context.new_page()
    errors = []
    checked.on("pageerror", lambda error: errors.append(str(error)))
    if damage == "unsupported-browser":
        checked.add_init_script("delete globalThis.DecompressionStream")
    checked.goto(broken.as_uri())
    checked.wait_for_function("document.documentElement.dataset.artifactStatus === 'error'")
    assert checked.locator("#artifact-initialization-error").is_visible()
    assert "HTML could not be opened:" in checked.locator("#artifact-initialization-error").inner_text()
    assert checked.evaluate("typeof obsArtifact") == "undefined"
    assert errors == []
    checked.close()


def test_late_added_runtime_uses_generic_ordered_boundary(transport_page) -> None:
    page, artifact = transport_page
    html = artifact.read_text(encoding="utf-8")
    html = prepare_artifact_scripts(html.replace("</body>", """
        <script id="extension-script" type="text/javascript">
        globalThis.extensionProof = {
            modelReady: !!globalThis.obsArtifact,
            pagesReady: !!globalThis.obsPages,
            light: document.documentElement.dataset.theme === "light",
            paged: document.documentElement.classList.contains("paged-mode"),
            notes: JSON.parse(document.querySelector("[data-artifact-data]").textContent).notes.length
        };
        </script></body>"""))
    extended = artifact.with_name("extension.html")
    extended.write_text(html, encoding="utf-8")
    checked = page.context.new_page()
    checked.goto(extended.as_uri())
    checked.evaluate("obsHtmlReady")
    assert checked.evaluate("extensionProof") == {
        "modelReady": True, "pagesReady": True, "light": True, "paged": True, "notes": 2,
    }
    checked.close()


def test_none_transport_opens_and_saves_without_compression_streams(transport_page) -> None:
    page, artifact = transport_page
    html = artifact.read_text(encoding="utf-8")
    plain = ARTIFACT_PATTERN.sub(
        lambda match: encode_artifact_data(decode_artifact_data(html), "none"), html, count=1,
    )
    artifact = artifact.with_name("plain.html")
    artifact.write_text(plain, encoding="utf-8")
    checked = page.context.new_page()
    checked.add_init_script("delete globalThis.CompressionStream; delete globalThis.DecompressionStream")
    checked.goto(artifact.as_uri())
    checked.evaluate("obsHtmlReady")
    checked.evaluate("obsArtifact.commitCanonicalProjection([{slug:'chapter',fields:{status:'none-edited'}}])")
    saved = checked.evaluate("obsComments.reviewedHtml()")
    assert "data-encoding" not in ARTIFACT_PATTERN.search(saved)[1]
    assert next(note for note in decode_artifact_data(saved)["notes"] if note["slug"] == "chapter")[
        "frontmatter"
    ]["status"] == "none-edited"
    checked.close()
