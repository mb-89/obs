import os
from pathlib import Path

import pytest

from obs_html.cli import main
from obs_html.pdf import RenderedCheck


def _document(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text("# Rendered\n\nBody.\n", encoding="utf-8")
    output = tmp_path / "document.html"
    assert main(["--source", str(vault), "--output", str(output)]) == 0
    return output


def test_rendered_check_reports_status_errors_and_pages(tmp_path, monkeypatch, capsys) -> None:
    calls = []

    def check(html, timeout_seconds):
        calls.append((html, timeout_seconds))
        return RenderedCheck("ready", (), 3)

    monkeypatch.setattr("obs_html.pdf.check_rendered", check)
    assert main(["--check-rendered", str(tmp_path / "document.html")]) == 0
    out = capsys.readouterr().out
    assert f"Rendered {tmp_path / 'document.html'}: status ready, 0 console errors, 3 pages." in out
    assert calls == [(tmp_path / "document.html", 120)]


@pytest.mark.parametrize(("result", "reason"), [
    (RenderedCheck("ready", ("Uncaught boom (file:///d.html:4)",), 2), "1 console errors"),
    (RenderedCheck("error", (), 0), "status error"),
    (RenderedCheck("timeout", (), 0), "status timeout"),
])
def test_rendered_check_fails_on_console_errors_or_unready_status(
    tmp_path, monkeypatch, capsys, result, reason,
) -> None:
    monkeypatch.setattr("obs_html.pdf.check_rendered", lambda _html, _timeout: result)
    with pytest.raises(SystemExit, match="2"):
        main(["--check-rendered", str(tmp_path / "document.html")])
    captured = capsys.readouterr()
    assert f"Rendered check failed: {reason}" in captured.err
    for error in result.console_errors:
        assert f"Console error: {error}" in captured.err


@pytest.mark.parametrize("extra", [
    ["--check"], ["--source", "vault"], ["--output", "out.html"], ["--export-pdf", "d.html"],
    ["--embed-source"], ["--extract-comments", "d.html"],
])
def test_rendered_check_is_a_separate_operation(extra, capsys) -> None:
    with pytest.raises(SystemExit, match="2"):
        main(["--check-rendered", "document.html", *extra])
    assert "--check-rendered cannot be combined" in capsys.readouterr().err


@pytest.mark.skipif(not os.environ.get("OBS_HTML_TEST_NATIVE_BROWSER"),
                    reason="Set OBS_HTML_TEST_NATIVE_BROWSER for the native rendered check.")
def test_native_rendered_check_counts_pages_and_reports_console_errors(tmp_path, capsys) -> None:
    clean = _document(tmp_path)
    capsys.readouterr()
    assert main(["--check-rendered", str(clean)]) == 0
    out = capsys.readouterr().out
    assert "status ready, 0 console errors, " in out
    assert int(out.rsplit(", ", 1)[1].split(" ")[0]) >= 1

    broken = tmp_path / "broken.html"
    broken.write_text(clean.read_text(encoding="utf-8").replace(
        "</body>", "<script>console.error('synthetic failure')</script></body>",
    ), encoding="utf-8")
    with pytest.raises(SystemExit, match="2"):
        main(["--check-rendered", str(broken)])
    captured = capsys.readouterr()
    assert "Console error: synthetic failure" in captured.err
    assert "status ready, 1 console errors, " in captured.out
