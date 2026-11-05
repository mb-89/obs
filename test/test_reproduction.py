import base64
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from zipfile import ZipFile

import pytest
from pypdf import PdfReader, PdfWriter

from pickers import choose_files
from producer_commands import python_command
from obs_html.cli import DEFAULT_CONFIG, PROJECT_ROOT, main
from obs_html.config import load_config
from obs_html.content import ContentError, read_manifest
from obs_html.pdf import attach_archive
from obs_html.pdf import export_pdf
from obs_html.reproduction import ARCHIVE_NAME, embedded_archive, source_archive
from obs_html.report_data import REPORT_PATTERN, decode_report_data, encode_report_data

HISTORY_FENCE = (
    "\n## History\n\n```base\nproperties:\n  version: {displayName: Version}\n  change: {displayName: Change}\n"
    "views: [{type: table, name: History, order: [version, change]}]\n"
    "obsHtml: {records: documentHistory}\n```\n"
)


def vault_at(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[one]]\n", encoding="utf-8")
    (vault / "one.md").write_text("# One\n\nA conclusion.\n", encoding="utf-8")
    return vault


def report_data(report: str) -> dict:
    return decode_report_data(report)


def test_reader_and_archive_share_exact_attachment_owner(tmp_path: Path) -> None:
    vault = vault_at(tmp_path)
    original = b"original evidence\n" * 10000
    (vault / "evidence.dat").write_bytes(original)
    (vault / "one.md").write_text(
        "# One\n\n![Original](evidence.dat)\n\n![Again](evidence.dat)\n", encoding="utf-8",
    )
    output = tmp_path / "report.html"
    assert main(["--source", str(vault), "--output", str(output), "--embed-source",
                 "--embed-attachments"]) == 0
    report = output.read_text(encoding="utf-8")
    data = report_data(report)
    assert base64.b64encode(original).decode() not in report
    source_assets = [asset for asset in data["embeddedAssets"].values()
                     if asset.get("archivePath") == "vault/evidence.dat"]
    assert len(source_assets) == 1
    asset = source_assets[0]
    assert asset["archivePath"] == "vault/evidence.dat"
    assert asset["mime"] == "application/octet-stream"
    with ZipFile(BytesIO(embedded_archive(report))) as archive:
        assert archive.read(asset["archivePath"]) == original
        assert archive.namelist().count(asset["archivePath"]) == 1


def test_source_selection_excludes_poison_and_preserves_no_git_rebuild(tmp_path: Path) -> None:
    vault = vault_at(tmp_path)
    (vault / "helper.ps1").write_text("Write-Output source", encoding="utf-8")
    generator = tmp_path / "generator"
    shutil.copytree(PROJECT_ROOT / "src", generator / "src",
                    ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("pyproject.toml", "uv.lock", "README.md", "RUNME.ps1", "RUNME.sh"):
        shutil.copyfile(PROJECT_ROOT / name, generator / name)
    subprocess.run(["git", "init", "--quiet", str(generator)], check=True)
    subprocess.run(["git", "-C", str(generator), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(generator), "rm", "--cached", "--quiet", "--",
         "src/obs_html/note-profile.schema.json"],
        check=True,
    )
    for name in ("build/poison.py", "node_modules/poison.js", "cache/poison.dat",
                 "BUILD/poison.py", "compiled.dll"):
        path = generator / "src" / "obs_html" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("must not ship", encoding="utf-8")
    (vault / "compiled.dll").write_text("must not ship", encoding="utf-8")
    environment = vault / "installed-runtime"
    environment.mkdir()
    (environment / "pyvenv.cfg").write_text("home = python", encoding="utf-8")
    (environment / "installed.py").write_text("must not ship", encoding="utf-8")
    (generator / "src" / "obs_html" / "untracked.py").write_text("must not ship", encoding="utf-8")
    config = load_config(DEFAULT_CONFIG)
    archive = source_archive(vault, vault / "manifest.md", generator, config, False)
    extracted = tmp_path / "extracted"
    with ZipFile(BytesIO(archive)) as contents:
        assert contents.read("vault/helper.ps1") == b"Write-Output source"
        assert contents.read("generator/src/obs_html/note-profile.schema.json") == (
            (generator / "src" / "obs_html" / "note-profile.schema.json").read_bytes()
        )
        assert not any("poison" in name or name.endswith(("untracked.py", ".dll"))
                       for name in contents.namelist())
        assert not any("installed-runtime" in name for name in contents.namelist())
        assert "generator/uv.lock" in contents.namelist()
        contents.extractall(extracted)
    rebuilt = source_archive(extracted / "vault", extracted / "vault" / "manifest.md",
                             extracted / "generator", config, False)
    with ZipFile(BytesIO(rebuilt)) as contents:
        assert contents.read("vault/helper.ps1") == b"Write-Output source"
        assert "generator/src/obs_html/archive.js" in contents.namelist()
        assert "generator/src/obs_html/note-profile.schema.json" in contents.namelist()


def test_malformed_shared_asset_is_explicit_error(tmp_path: Path) -> None:
    vault = vault_at(tmp_path)
    (vault / "one.md").write_text("# One\n\n[Evidence](input.dat)\n", encoding="utf-8")
    (vault / "input.dat").write_bytes(b"exact original")
    output = tmp_path / "report.html"
    assert main(["--source", str(vault), "--output", str(output), "--embed-source"]) == 0
    report = output.read_text(encoding="utf-8")
    data = report_data(report)
    asset = next(iter(data["embeddedAssets"].values()))
    asset["sha256"] = "0" * 64
    damaged = REPORT_PATTERN.sub(lambda match: encode_report_data(data), report, count=1)
    with pytest.raises(ContentError, match="asset|digest"):
        embedded_archive(damaged)


def test_source_snapshot_preserves_authored_output_directories(tmp_path: Path) -> None:
    vault = vault_at(tmp_path)
    folders = ("output", "outputs", "build", "dist", "target", "cache", "env", "venv", "coverage")
    for folder in folders:
        source = vault / folder / "result.md"
        source.parent.mkdir()
        source.write_text("---\nkind: result\n---\nAuthored source result.\n", encoding="utf-8")
        (source.parent / "helper.ps1").write_bytes(b"Write-Output source")
        (source.parent / "input.dat").write_bytes(b"exact input bytes")
    archive = source_archive(vault, vault / "manifest.md", PROJECT_ROOT,
                             load_config(DEFAULT_CONFIG), False)
    with ZipFile(BytesIO(archive)) as contents:
        for folder in folders:
            assert contents.read(f"vault/{folder}/result.md") == (vault / folder / "result.md").read_bytes()
            assert contents.read(f"vault/{folder}/helper.ps1") == b"Write-Output source"
            assert contents.read(f"vault/{folder}/input.dat") == b"exact input bytes"


@pytest.mark.skipif(not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"),
                    reason="Set OBS_HTML_TEST_NATIVE_BROWSER for native shared payload checks.")
def test_native_shared_assets_download_print_review_and_reproduce(tmp_path: Path) -> None:
    from playwright.sync_api import sync_playwright
    from obs_html.comments import extract_comments

    vault = vault_at(tmp_path)
    original = b"exact original evidence\n" * 1000
    icon = b'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="32" height="32" fill="green"/></svg>'
    (vault / "original.dat").write_bytes(original)
    (vault / "icon.svg").write_bytes(icon)
    (vault / "one.md").write_text(
        "# One\n\n![Original](original.dat)\n\n![Icon](icon.svg)\n", encoding="utf-8",
    )
    output = tmp_path / "report.html"
    assert main(["--source", str(vault), "--output", str(output), "--embed-source", "--check",
                 "--embed-attachments"]) == 0
    assert main(["--source", str(vault), "--output", str(output), "--embed-source",
                 "--embed-attachments"]) == 0
    archive = embedded_archive(output.read_text(encoding="utf-8"))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"])
        try:
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(output.as_uri() + "#one")
            page.evaluate("obsPayload.ready()")
            page.wait_for_function("document.querySelector('[data-chapter-body] img')?.naturalWidth === 32")
            with page.expect_download() as downloaded:
                page.get_by_role("link", name="Original", exact=True).click()
            assert Path(downloaded.value.path()).read_bytes() == original
            page.evaluate("obsReport.openBar('settings')")
            with page.expect_download() as zipped:
                page.locator("[data-source-exports] [data-source-download]").click()
            assert Path(zipped.value.path()).read_bytes() == archive
            page.evaluate("window.print = () => {}; obsPages.exportPDF()")
            assert page.locator(".print-book img").evaluate_all(
                "images => images.length > 0 && images.every(image => image.complete && image.naturalWidth === 32)",
            )
            page.emulate_media(media="print")
            pdf = page.pdf(print_background=True, prefer_css_page_size=True)
            assert "One" in "\n".join(item.extract_text() for item in PdfReader(BytesIO(pdf)).pages)
            page.emulate_media(media="screen")
            page.evaluate("""() => {
                window.dispatchEvent(new Event('afterprint'));
                obsComments.data.annotations.push({
                    id: 'payload-review', target: {chapter: 'one'}, text: 'Keep exact originals',
                    author: 'Reviewer'
                });
                window.showSaveFilePicker = undefined;
                obsReport.openBar('comments');
            }""")
            with page.expect_download() as reviewed_download:
                page.locator("[data-comment-save]").click()
            reviewed = tmp_path / "reviewed.html"
            reviewed_download.value.save_as(reviewed)
            reviewed_html = reviewed.read_text(encoding="utf-8")
            assert not re.search(r'(?:src|href)="blob:', reviewed_html)
            assert embedded_archive(reviewed_html) == archive
            assert "Keep exact originals" in extract_comments(reviewed)
            page.close()
            reopened = browser.new_page()
            reopened.goto(reviewed.as_uri() + "#one")
            reopened.evaluate("obsPayload.ready()")
            with reopened.expect_download() as redownload:
                reopened.get_by_role("link", name="Original", exact=True).click()
            assert Path(redownload.value.path()).read_bytes() == original
            assert errors == []
        finally:
            browser.close()
    extracted = tmp_path / "extracted"
    with ZipFile(BytesIO(archive)) as contents:
        contents.extractall(extracted)
    environment = os.environ | {"PYTHONPATH": str(extracted / "generator" / "src"),
                                "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, str(extracted / "reproduce.py")],
                            cwd=extracted, env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    rebuilt = embedded_archive((extracted / "document.html").read_text(encoding="utf-8"))
    with ZipFile(BytesIO(rebuilt)) as contents:
        assert contents.read("vault/original.dat") == original


@pytest.mark.skipif(not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"),
                    reason="Set OBS_HTML_TEST_NATIVE_BROWSER for native malformed payload checks.")
@pytest.mark.parametrize("damage", ["digest", "member"])
def test_native_malformed_shared_assets_fail_explicitly(tmp_path: Path, damage: str) -> None:
    from playwright.sync_api import sync_playwright, Error as BrowserError

    vault = vault_at(tmp_path)
    (vault / "original.dat").write_bytes(b"exact original evidence")
    (vault / "one.md").write_text("# One\n\n[Original](original.dat)\n", encoding="utf-8")
    output = tmp_path / "report.html"
    assert main(["--source", str(vault), "--output", str(output), "--embed-source"]) == 0
    report = output.read_text(encoding="utf-8")
    data = report_data(report)
    asset = next(iter(data["embeddedAssets"].values()))
    if damage == "digest":
        asset["sha256"] = "0" * 64
    else:
        asset["archivePath"] = "vault/missing.dat"
    report = REPORT_PATTERN.sub(lambda match: encode_report_data(data), report, count=1)
    output.write_text(report, encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"])
        try:
            page = browser.new_page()
            page.goto(output.as_uri() + "#one")
            with pytest.raises(BrowserError, match="digest mismatch|Missing embedded ZIP member"):
                page.evaluate("obsPayload.ready()")
            assert page.locator("[data-payload-error]").is_visible()
        finally:
            browser.close()


@pytest.mark.skipif(not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"),
                    reason="Set OBS_HTML_TEST_NATIVE_BROWSER for native standalone assets.")
def test_native_assets_without_source_archive_remain_self_contained(tmp_path: Path) -> None:
    from playwright.sync_api import sync_playwright

    vault = vault_at(tmp_path)
    (vault / "icon.svg").write_bytes(
        b'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><circle r="16"/></svg>',
    )
    (vault / "one.md").write_text("# One\n\n![Icon](icon.svg)\n\n![Again](icon.svg)\n", encoding="utf-8")
    output = tmp_path / "report.html"
    assert main(["--source", str(vault), "--output", str(output)]) == 0
    assert embedded_archive(output.read_text(encoding="utf-8")) is None
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"])
        try:
            page = browser.new_page()
            page.goto(output.as_uri() + "#one")
            page.wait_for_function("""() => {
                const images = [...document.querySelectorAll('[data-chapter-body] figure > img')];
                return images.length === 2 && images.every(image => image.naturalWidth === 32);
            }""")
            assert page.evaluate("typeof globalThis.obsPayload.ready") == "function"
        finally:
            browser.close()


@pytest.mark.skipif(not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"),
                    reason="Set OBS_HTML_TEST_NATIVE_BROWSER for native payload timeout.")
def test_native_print_payload_readiness_uses_existing_timeout(tmp_path: Path) -> None:
    from playwright.sync_api import sync_playwright

    vault = vault_at(tmp_path)
    output = tmp_path / "report.html"
    assert main(["--source", str(vault), "--output", str(output), "--embed-source"]) == 0
    report = output.read_text(encoding="utf-8")
    data = report_data(report)
    assert data["printReadyTimeoutMilliseconds"] > 50
    # The payload is compressed, so a text replace would silently keep the long default.
    data["printReadyTimeoutMilliseconds"] = 50
    report = REPORT_PATTERN.sub(lambda match: encode_report_data(data), report, count=1)
    output.write_text(report, encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"])
        try:
            page = browser.new_page()
            page.goto(output.as_uri())
            page.evaluate("""() => {
                obsPayload.ready = () => new Promise(() => {});
                globalThis.printCalls = 0;
                window.print = () => { printCalls++; };
            }""")
            page.evaluate("obsReport.openBar('settings')")
            page.locator("[data-export-pdf]").click()
            page.wait_for_function(
                "document.querySelector('[data-export-status]').textContent.includes('Timed out')",
            )
            assert page.evaluate("printCalls") == 0
            assert "Timed out" in page.locator("[data-export-status]").inner_text()
            assert page.locator("html").get_attribute("class").find("preparing-print") == -1
        finally:
            browser.close()


def test_archive_opt_in_includes_sources_and_roundtrips_pdf(tmp_path: Path) -> None:
    vault = vault_at(tmp_path)
    (vault / ".secret").write_text("not shared", encoding="utf-8")
    (vault / "script.py").write_text("print('input helper')", encoding="utf-8")
    output = tmp_path / "report.html"
    assert main(["--source", str(vault), "--output", str(output)]) == 0
    assert embedded_archive(output.read_text(encoding="utf-8")) is None
    assert main(["--source", str(vault), "--output", str(output), "--embed-source"]) == 0
    report = output.read_text(encoding="utf-8")
    archive = embedded_archive(report)
    assert archive is not None
    with ZipFile(BytesIO(archive)) as contents:
        assert "vault/.secret" not in contents.namelist()
        assert contents.read("vault/script.py") == b"print('input helper')"
        assert contents.read("generator/uv.lock") == (PROJECT_ROOT / "uv.lock").read_bytes()
        for name in ("README.md", "RUNME.ps1", "RUNME.sh"):
            assert contents.read(f"generator/{name}") == (PROJECT_ROOT / name).read_bytes()
        assert "--config ../build-config.json" in contents.read("REPRODUCE.txt").decode()
        assert "generator/src/obs_html/archive.js" in contents.namelist()
        assert "--execute-commands" in contents.read("reproduce.py").decode()
        assert json.loads(contents.read("build-config.json"))["report"]["print"]["paperSizes"]["A4"] == {
            "widthMillimeters": 210, "heightMillimeters": 297}
        (tmp_path / "build-config.json").write_bytes(contents.read("build-config.json"))
    assert load_config(tmp_path / "build-config.json") == load_config(DEFAULT_CONFIG)
    assert 'id="pdf-library-script"' in report
    assert "Download source ZIP" in report
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    pdf = BytesIO()
    writer.write(pdf)
    enriched = attach_archive(pdf.getvalue(), archive)
    reader = PdfReader(BytesIO(enriched))
    assert len(reader.pages) == 1
    assert reader.attachments[ARCHIVE_NAME] == [archive]
    with pytest.raises(ContentError, match="already contains"):
        attach_archive(enriched, archive)
    source_pdf = tmp_path / "original.pdf"
    source_pdf.write_bytes(pdf.getvalue())
    target = tmp_path / "attached.pdf"
    assert main(["--attach-source-to-pdf", str(source_pdf), "--source-report", str(output),
                 "--output", str(target)]) == 0
    assert PdfReader(target).attachments[ARCHIVE_NAME] == [archive]
    assert source_pdf.read_bytes() == pdf.getvalue()


def test_source_archive_records_authorized_silent_producers(tmp_path: Path) -> None:
    vault = vault_at(tmp_path)
    (vault / "one.md").write_text(
        "# One\n\n```cmd silent\n"
        + python_command("open('produced.txt', 'wb').write(b'produced\\n')")
        + "\n```\n",
        encoding="utf-8",
    )
    output = tmp_path / "report.html"

    assert main([
        "--source", str(vault), "--output", str(output), "--embed-source", "--execute-commands",
    ]) == 0

    archive = embedded_archive(output.read_text(encoding="utf-8"))
    assert archive is not None
    with ZipFile(BytesIO(archive)) as contents:
        assert contents.read("vault/one.md") == (vault / "one.md").read_bytes()
        assert contents.read("vault/produced.txt") == b"produced\n"
        assert "Original generation authorized command fences: True." in (
            contents.read("REPRODUCE.txt").decode()
        )


def test_check_archive_never_writes_and_missing_checkout_fails(tmp_path: Path) -> None:
    vault = vault_at(tmp_path)
    output = tmp_path / "report.html"
    assert main(["--source", str(vault), "--output", str(output), "--embed-source", "--check"]) == 0
    assert not output.exists()
    with pytest.raises(ContentError, match="generator checkout"):
        source_archive(vault, vault / "manifest.md", tmp_path, load_config(DEFAULT_CONFIG), False)


def test_encrypted_pdf_and_corrupt_archive_are_explicit_errors() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("password")
    pdf = BytesIO()
    writer.write(pdf)
    with pytest.raises(ContentError, match="encrypted"):
        attach_archive(pdf.getvalue(), b"archive")
    encoded = base64.b64encode(b"not a zip").decode()
    with pytest.raises(ContentError, match="Invalid embedded"):
        embedded_archive(f'<script id="obs-source-archive" type="application/octet-stream">{encoded}</script>')


def test_manifest_history_and_empty_cover_fields(tmp_path: Path) -> None:
    vault = vault_at(tmp_path)
    manifest = vault / "manifest.md"
    manifest.write_text(
        '---\nproduct: {name: SE Harness, version: ""}\nsap number: ""\n'
        'copyright: null\nconfidentiality: ""\nauthors: []\n'
        'history:\n  - {version: "00", date: 2026-10-01, author: Ada, change: Initial}\n'
        '  - {version: "01*", date: "", author: Lin, change: Working draft}\n'
        '---\n- [[one]]\n', encoding="utf-8",
    )
    output = tmp_path / "report.html"
    assert main(["--source", str(vault), "--output", str(output)]) == 0
    unauthored = decode_report_data(output.read_text(encoding="utf-8"))["notes"][0]
    assert unauthored["tables"] == [], "history metadata alone must not add a Home table"
    manifest.write_text(manifest.read_text(encoding="utf-8") + HISTORY_FENCE, encoding="utf-8")
    metadata = read_manifest(manifest).metadata
    assert metadata["product"] == {"name": "SE Harness"}
    assert "sap number" not in metadata
    assert "authors" not in metadata
    assert metadata["history"][0]["date"] == "2026-10-01"
    assert "date" not in metadata["history"][1]
    assert main(["--source", str(vault), "--output", str(output)]) == 0
    data = decode_report_data(output.read_text(encoding="utf-8"))
    home = data["notes"][0]
    assert "SE Harness" in home["html"]
    assert "<dd>01*</dd>" not in home["html"]
    assert "cover-confidentiality" not in home["html"]
    assert '<h2 id="home--history">History</h2>' in home["html"]
    assert [table["definition"]["obsHtml"]["records"] for table in home["tables"]] == ["documentHistory"]


@pytest.mark.parametrize("history", [
    "{version: '00'}",
    '[{version: 0, author: Ada, change: Text}]',
    '[{version: "00*", author: Ada, change: Draft}, {version: "01", author: Ada, change: Next}]',
    '[{version: "00", author: Ada, change: Text, date: "2026-02-30"}]',
    '[{version: "00", author: Ada, change: Text}, {version: "00", author: Ada, change: Duplicate}]',
])
def test_invalid_history_fails_validation(tmp_path: Path, history: str) -> None:
    vault = vault_at(tmp_path)
    manifest = vault / "manifest.md"
    manifest.write_text(f"---\nhistory: {history}\n---\n- [[one]]\n", encoding="utf-8")
    with pytest.raises(ContentError):
        read_manifest(manifest)


@pytest.mark.skipif(not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"),
                    reason="Set OBS_HTML_TEST_NATIVE_BROWSER to a Chromium executable for native PDF integration.")
def test_native_pdf_and_standalone_browser_attachment(tmp_path: Path) -> None:
    from playwright.sync_api import sync_playwright
    from playwright.sync_api import Error as BrowserError

    vault = vault_at(tmp_path)
    (vault / "manifest.md").write_text(
        '---\ntitle: Source archive test\nproduct: {name: SE Harness}\n'
        'history:\n  - {version: "00*", author: Ada, change: Working draft}\n'
        '---\n- [[one]]\n\n> [!important]\n> A key conclusion.\n' + HISTORY_FENCE, encoding="utf-8",
    )
    html = tmp_path / "report.html"
    assert main(["--source", str(vault), "--output", str(html), "--embed-source"]) == 0
    archive = embedded_archive(html.read_text(encoding="utf-8"))
    pdf_bytes = export_pdf(html)
    reader = PdfReader(BytesIO(pdf_bytes))
    assert reader.attachments[ARCHIVE_NAME] == [archive]
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "Source archive test" in text
    assert "Working draft" in text
    assert "Page 1 of" in text
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    plain = BytesIO()
    writer.write(plain)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ["OBS_HTML_TEST_NATIVE_BROWSER"])
        try:
            page = browser.new_page()
            page.goto(html.as_uri())
            assert page.locator("[data-source-exports]").is_visible() is False  # dock is closed
            assert page.locator("[data-source-download]").count() >= 2
            assert page.locator(".source-archive-bar button").count() == 0
            assert page.locator(".source-archive-bar .content-card-title").count() == 0
            history = page.locator('[data-active-chapter] [data-data-table="home-base-1"] tbody')
            assert history.locator("tr[data-row-key]").count() == 1
            assert history.inner_text().count("00*") == 1
            with page.expect_download() as download:
                page.locator(".source-archive-bar [data-source-download]").click()
            assert download.value.suggested_filename == ARCHIVE_NAME
            assert Path(download.value.path()).read_bytes() == archive
            plain_path = tmp_path / "printed.pdf"
            plain_path.write_bytes(plain.getvalue())
            with page.expect_download() as attached_download:
                page.evaluate("obsReport.openBar('settings')")
                assert page.evaluate("""() => {
                    const box = selector => document.querySelector(selector).getBoundingClientRect();
                    const pages = box('.settings-pages'), pdf = box('[data-export-pdf]');
                    const zip = box('[data-source-exports] [data-source-download]');
                    const attach = box('[data-source-attach]');
                    return Math.abs(pages.x - zip.x) < 1 && Math.abs(pdf.x - attach.x) < 1 &&
                        Math.abs(zip.width - attach.width) < 1 && Math.abs(pdf.width - attach.width) < 1;
                }""")
                choose_files(page, page.locator("[data-source-exports] [data-source-attach]").click,
                             plain_path)
            result = attached_download.value
            assert result.suggested_filename == "printed-with-source.pdf"
            assert PdfReader(result.path()).attachments[ARCHIVE_NAME] == [archive]
            enriched = page.evaluate(
                "async bytes => Array.from(await obsArchive.attach(new Uint8Array(bytes)))",
                list(plain.getvalue()),
            )
            assert PdfReader(BytesIO(bytes(enriched))).attachments[ARCHIVE_NAME] == [archive]
            with pytest.raises(BrowserError, match="already contains"):
                page.evaluate(
                    "async bytes => Array.from(await obsArchive.attach(new Uint8Array(bytes)))", enriched,
                )
        finally:
            browser.close()
