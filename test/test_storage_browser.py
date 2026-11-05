import base64
import html
import os
import struct
import zlib
from pathlib import Path

import pytest

from obs_html.content import parse_manifest
from obs_html.renderer import render_artifact


@pytest.mark.skipif(
    not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"),
    reason="Set OBS_HTML_TEST_NATIVE_BROWSER for opaque-origin storage checks.",
)
def test_storage_denial_keeps_settings_and_review_controls_usable(
    tmp_path: Path,
) -> None:
    from playwright.sync_api import expect, sync_playwright

    (tmp_path / "one.md").write_text(
        "# One\n\nThe review control remains available when storage is denied.\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n", encoding="utf-8")
    artifact = tmp_path / "artifact.html"
    artifact.write_text(
        render_artifact(manifest, parse_manifest(manifest)),
        encoding="utf-8",
    )
    wrapper = tmp_path / "sandbox.html"
    wrapper.write_text(
        '<!doctype html><iframe id="artifact" sandbox="allow-scripts" '
        f'src="{html.escape(artifact.as_uri() + "#one", quote=True)}"></iframe>',
        encoding="utf-8",
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"],
        )
        page = browser.new_page()
        try:
            page.goto(wrapper.as_uri())
            frame = page.frame_locator("#artifact")
            expect(frame.locator("[data-active-chapter]")).to_have_attribute(
                "data-chapter",
                "one",
            )
            expect(frame.locator("[data-chapter-body]")).to_contain_text(
                "The review control remains available",
            )
            frame.locator("body").evaluate("() => obsArtifact.openBar('settings', 'right')")
            expect(frame.locator('[data-storage-warning="appearance"]')).to_have_count(0)
            expect(frame.locator("html")).to_have_attribute("data-theme", "light")

            frame.locator("[data-theme-select]").select_option("dark")
            expect(frame.locator("html")).to_have_attribute("data-theme", "dark")

            frame.locator("body").evaluate("() => obsArtifact.openBar('comments', 'right')")
            reviewer = frame.locator("[data-comment-author]")
            expect(reviewer).to_be_visible()
            expect(frame.locator('[data-storage-warning="reviewer"]')).to_be_visible()
            frame.locator('[data-storage-warning="reviewer"] button').focus()
            expect(frame.locator("#hover-card")).to_contain_text(
                "cannot be remembered in this environment",
            )
            reviewer.fill("Local Reviewer")
            expect(reviewer).to_have_value("Local Reviewer")
            expect(frame.locator("[data-comment-save]")).to_be_enabled()
        finally:
            browser.close()


@pytest.mark.skipif(
    not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"),
    reason="Set OBS_HTML_TEST_NATIVE_BROWSER for opaque-origin asset checks.",
)
def test_repeated_embedded_images_do_not_request_internal_asset_uris(
    tmp_path: Path,
) -> None:
    from playwright.sync_api import expect, sync_playwright

    image = tmp_path / "shared.png"
    image.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a8xoAAAAASUVORK5CYII=",
    ))
    for name in ("one", "two"):
        (tmp_path / f"{name}.md").write_text(
            f"# {name.title()}\n\n![Shared image](shared.png)\n",
            encoding="utf-8",
        )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n- [[two]]\n", encoding="utf-8")
    artifact = tmp_path / "artifact.html"
    artifact_html = render_artifact(manifest, parse_manifest(manifest))
    assert "obs-asset:" in artifact_html
    artifact.write_text(artifact_html, encoding="utf-8")
    wrapper = tmp_path / "sandbox.html"
    wrapper.write_text(
        '<!doctype html><iframe id="artifact" sandbox="allow-scripts" '
        f'src="{html.escape(artifact.as_uri() + "#one", quote=True)}"></iframe>',
        encoding="utf-8",
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"],
        )
        page = browser.new_page()
        failed_requests: list[str] = []
        page.on("requestfailed", lambda request: failed_requests.append(request.url))
        try:
            page.goto(wrapper.as_uri())
            frame = page.frame_locator("#artifact")
            expect(frame.locator("[data-active-chapter]")).to_have_attribute(
                "data-chapter",
                "one",
            )
            image_element = frame.locator("[data-chapter-body] figure > img")
            expect(image_element).to_have_count(1)
            assert image_element.get_attribute("src").startswith("data:image/")
            frame.locator("body").evaluate("() => obsArtifact.activateChapter('two')")
            expect(frame.locator("[data-active-chapter]")).to_have_attribute(
                "data-chapter",
                "two",
            )
            assert frame.locator("[data-chapter-body] figure > img").get_attribute(
                "src",
            ).startswith("data:image/")
            static_image_src = frame.locator("body").evaluate("""() => {
                const root = document.createElement("div");
                document.body.append(root);
                obsArtifact.renderStatic("one", root);
                return root.querySelector("img").getAttribute("src");
            }""")
            assert static_image_src.startswith("data:image/")
            page.wait_for_timeout(100)
            assert not [url for url in failed_requests if url.startswith("obs-asset:")]
        finally:
            browser.close()


def _pixel(rgb: bytes) -> str:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"\x00" + rgb)) + chunk(b"IEND", b""))
    return base64.b64encode(png).decode("ascii")


PIXELS = {"red": _pixel(b"\xff\x00\x00"), "blue": _pixel(b"\x00\x00\xff")}


@pytest.mark.skipif(
    not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"),
    reason="Set OBS_HTML_TEST_NATIVE_BROWSER for archived asset checks.",
)
def test_archived_images_never_request_internal_asset_uris(tmp_path: Path) -> None:
    """Archived images resolve to blob URLs asynchronously; until then the reference must not
    sit in src, or Chrome logs net::ERR_UNKNOWN_URL_SCHEME for every inserted image."""
    from playwright.sync_api import expect, sync_playwright

    from obs_html.cli import main

    source = tmp_path / "source"
    (source / "assets").mkdir(parents=True)
    for name, pixel in PIXELS.items():
        (source / "assets" / f"{name}.png").write_bytes(base64.b64decode(pixel))
    (source / "one.md").write_text("# One\n\n![Red](assets/red.png)\n", encoding="utf-8")
    (source / "two.md").write_text("# Two\n\n![Red again](assets/red.png)\n\nSee [[evidence]].\n",
                                   encoding="utf-8")
    (source / "evidence.md").write_text(
        "---\ntitle: Evidence\n---\n![Evidence](assets/red.png)\n", encoding="utf-8",
    )
    (source / "manifest.md").write_text("- [[one]]\n- [[two]]\n", encoding="utf-8")
    output = tmp_path / "document.html"
    assert main(["--source", str(source), "--output", str(output), "--embed-source"]) == 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"])
        page = browser.new_page()
        problems: list[str] = []
        page.on("console", lambda message: problems.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: problems.append(str(error)))
        page.on("requestfailed", lambda request: problems.append(f"request failed: {request.url}"))
        loaded = """root => [...root.querySelectorAll('img')].every(image =>
            image.complete && image.naturalWidth > 0 && /^(?:blob|data):/.test(image.getAttribute('src'))
            && !image.hasAttribute('data-obs-asset-src'))"""

        def settled(step: str, root: str = "[data-chapter-body]") -> None:
            page.wait_for_function(f"({loaded})(document.querySelector({root!r}))")
            page.wait_for_timeout(200)
            assert problems == [], step

        try:
            page.goto(output.as_uri() + "#one")
            page.wait_for_function("document.documentElement.dataset.artifactStatus === 'ready'")
            assert "evidence.md" in page.evaluate("obsArtifact.canonicalNotes().map(note => note.sourcePath)")
            body = page.locator("[data-chapter-body]")
            expect(body.locator('img[alt="Red"]')).to_have_count(1)
            settled("initial render")
            assert body.locator('img[alt="Red"]').get_attribute("src").startswith("blob:")

            page.evaluate("obsArtifact.activateChapter('two')")
            expect(page.locator("[data-active-chapter]")).to_have_attribute("data-chapter", "two")
            settled("chapter activation")

            page.evaluate("obsPages.setPaged(true)")
            expect(page.locator(".paged-reader .paper-sheet img").first).to_be_attached()
            settled("paged view", ".paged-reader")
            page.evaluate("obsPages.setPaged(false)")
            settled("screen view")

            assert page.pdf(prefer_css_page_size=True, print_background=True).startswith(b"%PDF")
            settled("print")

            saved = tmp_path / "saved.html"
            saved.write_text(page.evaluate("obsComments.reviewedHtml()"), encoding="utf-8")
            settled("saved copy")
            assert 'data-obs-asset-src="' not in saved.read_text(encoding="utf-8")
            page.goto(saved.as_uri() + "#two")
            page.wait_for_function("document.documentElement.dataset.artifactStatus === 'ready'")
            settled("reopened saved copy")

            page.evaluate("""async pixel => {
                const bytes = Uint8Array.from(atob(pixel), char => char.charCodeAt(0));
                const descriptor = await obsPayload.describeAsset('assets/blue.png', bytes, 'image/png');
                const notes = obsArtifact.canonicalNotes();
                const evidence = notes.find(note => note.sourcePath === 'evidence.md');
                evidence.html = `<p><img src="obs-asset:${descriptor.key}" alt="Replacement"></p>`;
                const staged = await obsArtifact.stageCanonicalTransaction({
                    expectedRevision: obsArtifact.revision, notes,
                    assetChanges: [{...descriptor, bytes, removeKeys: []}],
                });
                staged.commit();
                obsArtifact.activateChapter(evidence.slug);
            }""", PIXELS["blue"])
            replacement = page.locator('[data-chapter-body] img[alt="Replacement"]')
            expect(replacement).to_have_count(1)
            settled("re-render after asset replacement")
            assert replacement.get_attribute("src").startswith("blob:")
        finally:
            browser.close()
