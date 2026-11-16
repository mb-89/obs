"""Browser tests: they start the local Chrome/Edge/Chromium through Playwright."""
import base64
import copy
import json
import re
from io import BytesIO

import pytest
import yaml
from pypdf import PdfReader

from conftest import FIXTURE, ROOT
from documents import chapter, document, node
from obs_html import cli


PIXEL = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="


@pytest.mark.browser
def test_pdf_destination_prints_the_rendered_document(pdf_browser, tmp_path, capsys) -> None:
    destination = tmp_path / "artifact.pdf"
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "logo.png").write_bytes(base64.b64decode(PIXEL))
    cli.main([str(FIXTURE), str(destination)])
    reader = PdfReader(BytesIO(destination.read_bytes()))
    box = reader.pages[0].mediabox
    assert (round(float(box.width) / 72 * 25.4, 1), round(float(box.height) / 72 * 25.4, 1)) == (215.9, 279.4)
    assert "Fixture document" in reader.pages[0].extract_text()
    assert len(reader.pages) >= 4  # Cover, contents, abstract and chapters start new pages.
    assert sorted(path.name for path in tmp_path.iterdir()) == ["artifact.pdf", "images"]


@pytest.mark.browser
def test_export_pdf_and_rendered_check_read_existing_html(pdf_browser, fixture_artifact, tmp_path, capsys) -> None:
    html = fixture_artifact
    cli.main(["--export-pdf", str(html), "--output", str(tmp_path / "artifact.pdf")])
    assert PdfReader(tmp_path / "artifact.pdf").pages
    cli.main(["--check-rendered", str(html)])
    assert "status ready, 0 console errors," in capsys.readouterr().out


@pytest.mark.browser
def test_rendered_check_fails_on_console_errors(pdf_browser, tmp_path, capsys) -> None:
    html = tmp_path / "broken.html"
    html.write_text('<!doctype html><html data-artifact-status="ready"><script>console.error("bad")</script>',
                    encoding="utf-8")
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--check-rendered", str(html)])
    assert exit_info.value.code == 2
    error = capsys.readouterr().err
    assert "Console error: bad" in error  # The console's own error, as the check reports it.
    assert f"\n{html}: --check-rendered: " in f"\n{error}", error


def _live_tracker(status: str) -> dict:
    """A Document whose Base declares the live-data capability note's live source over two issue
    notes; issue 1 is labelled ready, so the declaration derives Next for it (generic-tables.md,
    Current data, The check)."""
    note = (ROOT / "spec" / "capabilities" / "live-data.md").read_text(encoding="utf-8")
    declaration = yaml.safe_load(re.search(r"```yaml\n(.*?)```", note, re.S)[1])["obsHtml"]["liveSource"]
    issues = {1: {"state": "open", "labels": ["ready"], "status": status},
              2: {"state": "closed", "labels": [], "status": "Done"}}
    records = tuple({"id": f"widgets-{number}", "type": "note", "path": f"issues/widgets-{number}.md", "fields": {
        "kind": "issue", "repo": "widgets", "number": number, "updated": f"2026-11-0{number}T10:00:00Z", **item}}
        for number, item in issues.items())
    spec = {"filters": 'kind == "issue"', "views": [{"type": "table", "name": "Board", "order": ["file.name", "status"]}],
            "obsHtml": {"liveSource": copy.deepcopy(declaration)}}
    return document("Tracker", chapter("tracker", "Tracker", node("bases", source="", spec=spec)), records=records)


@pytest.mark.browser
def test_rendered_check_fails_on_a_live_source_that_does_not_reproduce_a_row_and_passes_once_corrected(
        pdf_browser, tmp_path, capsys) -> None:
    """generic-tables.md, Current data, The check: a row whose status the declaration's derive does
    not reproduce logs one console error naming its note and the field, so --check-rendered fails;
    the corrected note passes (spec/capabilities/live-data.md tells authors to run it)."""
    for status, name in (("Running", "wrong"), ("Next", "corrected")):
        (tmp_path / f"{name}.json").write_text(json.dumps(_live_tracker(status)), encoding="utf-8")
        assert cli.main([str(tmp_path / f"{name}.json"), str(tmp_path / f"{name}.html")]) == 0
    capsys.readouterr()
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--check-rendered", str(tmp_path / "wrong.html")])
    assert exit_info.value.code == 2
    error = capsys.readouterr().err
    errors = [line for line in error.splitlines() if line.startswith("Console error: ")]
    assert len(errors) == 1, error
    assert "note issues/widgets-1.md" in errors[0] and "derive check of field status" in errors[0]
    cli.main(["--check-rendered", str(tmp_path / "corrected.html")])
    assert "status ready, 0 console errors," in capsys.readouterr().out
