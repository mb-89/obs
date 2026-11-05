from pathlib import Path

import pytest

from obs_html.cli import main


@pytest.fixture(scope="module")
def report(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("print-chapter")
    vault = root / "vault"
    vault.mkdir()
    (vault / "intro.md").write_text("# Intro\n\nSee [[other]].\n", encoding="utf-8")
    (vault / "other.md").write_text("# Other\n\nBody *text*.\n\n- one\n- two\n", encoding="utf-8")
    (vault / "manifest.md").write_text("- [[intro]]\n- [[other]]\n", encoding="utf-8")
    output = root / "report.html"
    assert main(["--source", str(vault), "--output", str(output)]) == 0
    return output


def test_print_chapter_prints_its_html(report, capsys) -> None:
    capsys.readouterr()
    assert main(["--print-chapter", str(report), "intro"]) == 0
    out = capsys.readouterr().out
    assert '<h1 id="intro--intro">Intro</h1>' in out
    assert '<a href="#other">Other</a>' in out
    assert "Body" not in out


def test_print_chapter_prints_plain_text(report, capsys) -> None:
    capsys.readouterr()
    assert main(["--print-chapter", str(report), "other", "--chapter-format", "text"]) == 0
    assert capsys.readouterr().out == "Other\nBody text.\none\ntwo\n"


def test_chapter_format_requires_print_chapter(capsys) -> None:
    with pytest.raises(SystemExit, match="2"):
        main(["--chapter-format", "text"])
    assert "--chapter-format requires --print-chapter" in capsys.readouterr().err


def test_print_chapter_rejects_generation_options(report, capsys) -> None:
    with pytest.raises(SystemExit, match="2"):
        main(["--print-chapter", str(report), "intro", "--source", "vault"])
    assert "--print-chapter cannot be combined" in capsys.readouterr().err
