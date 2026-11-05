"""Explicit Markdown columns share the ordinary semantic and renderer pipeline."""
import json

import pytest

from obs_html_interim.content import (
    Chapter, ContentError, paragraph_warnings, parse_manifest, read_chapter_content, render_chapter,
)
from obs_html_interim.renderer import render_artifact
from obs_html_interim.artifact_data import decode_artifact_data


def test_columns_preserve_canonical_cards_queries_links_and_source_lines(tmp_path):
    source = tmp_path / "chapter.md"
    cards = {"version": 1, "cards": [{
        "title": "Coverage",
        "body": "See [[chapter#Details]] and [evidence](evidence.txt).",
        "metrics": [{"label": "Items", "where": []}],
    }]}
    (tmp_path / "evidence.txt").write_text("shared", encoding="utf-8")
    source.write_text(
        "|||\n```cards\n" + json.dumps(cards) + "\n```\n"
        "|||\n## Details\n\nQuestion #mark/open_point/columns\n\n"
        "```base\nviews:\n  - type: table\n    order: [title]\n```\n|||\n",
        encoding="utf-8",
    )
    chapter = Chapter(0, "Chapter", "chapter", source, "chapter")
    document = read_chapter_content(chapter)
    html = render_chapter(chapter, [chapter], tmp_path, document=document)
    assert html.count('class="markdown-columns"') == 1
    assert html.count('class="markdown-column"') == 2
    assert len(document.tables) == 1
    assert html.count('data-base-table="chapter-base-1"') == 1
    assert len(document.marks) == 1
    assert any("chapter.md:8:" in message for message in paragraph_warnings(
        chapter, document, 1, 1,
    ))
    assert 'href="#chapter/details"' in html
    assert 'id="chapter--details"' in html
    assert '(<code>evidence.<wbr>txt</code>)' in html
    assert "|||" not in html


def test_weighted_columns_keep_the_declared_subject_ratio(tmp_path):
    source = tmp_path / "chapter.md"
    source.write_text(
        "||| 1:2\nCoverage\n|||\nEvidence\n|||\n", encoding="utf-8",
    )
    chapter = Chapter(0, "Chapter", "chapter", source, "chapter")
    html = render_chapter(chapter, [chapter], tmp_path, document=read_chapter_content(chapter))
    assert 'class="markdown-columns markdown-columns--weighted"' in html
    assert "--markdown-column-template:minmax(0,1fr) minmax(0,2fr)" in html


def test_manifest_columns_keep_one_home_query_owner(tmp_path):
    (tmp_path / "chapter.md").write_text("# Details\n", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text(
        "- [[chapter]]\n\n|||\nLeft **overview**.\n|||\n"
        "```base\nviews:\n  - type: table\n    order: [title]\n```\n|||\n",
        encoding="utf-8",
    )
    data = decode_artifact_data(render_artifact(manifest, parse_manifest(manifest)))
    home = next(note for note in data["notes"] if note["slug"] == "home")
    assert home["html"].count('class="markdown-column"') == 2
    assert home["html"].count('data-base-table="home-base-1"') == 1
    assert sum(
        table["definition"]["views"][0]["order"] == ["title"] for table in home["tables"]
    ) == 1


@pytest.mark.parametrize("body", [
    "|||\nLeft\n", "|||\nLeft\n|||\nRight\n", "|||\n|||\nRight\n|||\n",
    "|||\n<!-- invisible -->\n|||\nRight\n|||\n",
    "|||\nLeft\n|||\n|||\n",
    "|||\nLeft\n|||\nInner\n|||\nRight\n|||\n",
    "> |||\n> Left\n> |||\n> Right\n> |||\n",
    "- |||\n\n  Left\n\n  |||\n\n  Right\n\n  |||\n",
    "||| 0:2\nLeft\n|||\nRight\n|||\n",
    "|||\nLeft\n||| 1:2\nRight\n|||\n",
])
def test_malformed_or_nested_columns_are_explicit_input_errors(tmp_path, body):
    source = tmp_path / "chapter.md"
    source.write_text(body, encoding="utf-8")
    chapter = Chapter(0, "Chapter", "chapter", source, "chapter")
    with pytest.raises(ContentError, match="[Cc]olumn"):
        read_chapter_content(chapter)


def test_code_delimiters_stay_literal_and_multiple_column_blocks_work(tmp_path):
    source = tmp_path / "chapter.md"
    source.write_text(
        "```text\n|||\n|||\n|||\n```\n\n    |||\n\n"
        "inline ||| stays prose\n\n"
        "|||\nLeft `|||`.\n|||\nRight.\n|||\n\n"
        "|||\nSecond left.\n|||\nSecond right.\n|||\n", encoding="utf-8",
    )
    chapter = Chapter(0, "Chapter", "chapter", source, "chapter")
    html = render_chapter(chapter, [chapter], tmp_path)
    assert html.count('class="markdown-columns"') == 2
    assert html.count('class="markdown-column"') == 4
    assert '<pre><code class="language-text">|||\n|||\n|||\n</code></pre>' in html
    assert "<code>|||</code>" in html
    assert "inline ||| stays prose" in html


def test_standalone_delimiter_ends_an_ordinary_markdown_table_without_blank_lines(tmp_path):
    source = tmp_path / "chapter.md"
    source.write_text(
        "|||\n| Left | Value |\n|---|---|\n| One | 1 |\n"
        "|||\n| Right | Value |\n|---|---|\n| Two | 2 |\n|||\n",
        encoding="utf-8",
    )
    chapter = Chapter(0, "Chapter", "chapter", source, "chapter")
    html = render_chapter(chapter, [chapter], tmp_path)
    assert html.count("<table>") == 2
    assert html.count('class="markdown-column"') == 2
    assert "|||" not in html


def test_cli_check_reports_malformed_columns_without_writing(tmp_path, capsys):
    from obs_html_interim.cli import main

    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "chapter.md").write_text("|||\nUnclosed column.\n", encoding="utf-8")
    before = set(tmp_path.iterdir())
    with pytest.raises(SystemExit) as failure:
        main(["--source", str(manifest), "--check"])
    assert failure.value.code == 2
    assert "Columns" in capsys.readouterr().err
    assert set(tmp_path.iterdir()) == before
