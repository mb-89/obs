import json
from pathlib import Path

import pytest

import obs_html_interim.content as content
from obs_html_interim.cli import main
from obs_html_interim.content import (
    Chapter,
    ContentError,
    collect_notes,
    paragraph_warnings,
    parse_manifest,
    read_chapter_content,
    read_manifest,
    render_chapter,
)
from obs_html_interim.artifact_data import decode_artifact_data


def test_alias_frontmatter_is_not_reparsed_for_each_reference(tmp_path, monkeypatch) -> None:
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n", encoding="utf-8")
    (tmp_path / "one.md").write_text(
        "# One\n\n" + " ".join("[[Friendly name]]" for _ in range(24)),
        encoding="utf-8",
    )
    target = tmp_path / "target.md"
    target.write_text("---\naliases: [Friendly name]\n---\n# Target\n", encoding="utf-8")
    original_split = content._split_frontmatter
    target_parses = 0

    def count_target_parses(source, source_path):
        nonlocal target_parses
        if source_path == target:
            target_parses += 1
        return original_split(source, source_path)

    monkeypatch.setattr(content, "_split_frontmatter", count_target_parses)
    output = tmp_path.parent / f"{tmp_path.name}-artifact.html"
    assert main(["--source", str(manifest), "--output", str(output)]) == 0
    assert target_parses <= 2
    data = decode_artifact_data(output.read_text(encoding="utf-8"))
    rendered = next(note["html"] for note in data["notes"] if note["slug"] == "one")
    assert rendered.count('href="#target"') >= 24


def test_cli_deduplicates_case_insensitive_aliases_per_note(tmp_path, capsys) -> None:
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n", encoding="utf-8")
    (tmp_path / "one.md").write_text("# One\n\n[[Friendly]]\n", encoding="utf-8")
    (tmp_path / "target.md").write_text(
        "---\naliases: [Friendly, friendly]\n---\n# Target\n", encoding="utf-8",
    )
    output = tmp_path.parent / f"{tmp_path.name}-artifact.html"

    assert main(["--source", str(manifest), "--output", str(output)]) == 0
    data = decode_artifact_data(output.read_text(encoding="utf-8"))
    rendered = next(note["html"] for note in data["notes"] if note["slug"] == "one")
    assert '<a href="#target">Target</a>' in rendered

    (tmp_path / "another.md").write_text(
        "---\naliases: [FRIENDLY]\n---\n# Another\n", encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="2"):
        main(["--source", str(manifest), "--output", str(output)])
    assert "Ambiguous note name or alias: Friendly" in capsys.readouterr().err


def test_authoring_comments_are_semantically_inert_but_code_is_literal(tmp_path) -> None:
    source = tmp_path / "one.md"
    source.write_text(
        "# One\n\n<!-- Add the introduction text here. -->\n"
        "Before <!-- [[missing]] #mark/decision/hidden --> after.\n\n"
        "<!-- Multiline\n\n```base\ninvalid\n```\n[[absent]]\n"
        "#mark/open_point/hidden\n-->\n\n"
        "`<!-- inline code -->`\n\n```text\n<!-- fenced code -->\n```\n\n"
        "<b>raw stays escaped</b>\n\n"
        "Actual paragraph needs a long-paragraph diagnostic.\n",
        encoding="utf-8",
    )
    chapter = Chapter(0, "One", "one", source, "one")
    document = read_chapter_content(chapter)
    html = render_chapter(chapter, [chapter], tmp_path, document=document)
    assert "Add the introduction" not in html
    assert "Before  after." in html
    assert "missing" not in html and "absent" not in html
    assert document.tables == () and document.marks == ()
    assert "&lt;!-- inline code --&gt;" in html
    assert "&lt;!-- fenced code --&gt;" in html
    assert "&lt;b&gt;raw stays escaped&lt;/b&gt;" in html
    warnings = paragraph_warnings(chapter, document, 1, 20)
    assert any(f"{source}:23:" in warning for warning in warnings)
    assert not any("hidden" in warning for warning in warnings)


def test_manifest_abstract_authoring_comments_are_inert(tmp_path) -> None:
    (tmp_path / "one.md").write_text("# One\n", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text(
        "- [[one]]\n\nVisible <!-- [[missing]] --> abstract.\n\n"
        "<!--\n```base\ninvalid\n```\n-->\n", encoding="utf-8",
    )
    parsed = read_manifest(manifest)
    from obs_html_interim.renderer import render_artifact
    html = render_artifact(manifest, parsed.chapters)
    content = json.dumps(decode_artifact_data(html))
    assert "Visible  abstract." in content
    assert "[[missing]]" not in content


def test_local_download_is_cited_by_default_and_cannot_escape_vault(tmp_path) -> None:
    source = tmp_path / "chapter.md"
    source.write_text("[Snapshot](evidence.pdf)\n", encoding="utf-8")
    (tmp_path / "evidence.pdf").write_bytes(b"%PDF-example")
    chapter = Chapter(0, "Chapter", "chapter", source, "chapter")
    html = render_chapter(chapter, [chapter], tmp_path)
    assert "base64" not in html and "<a" not in html
    assert ('<span class="source-reference" data-source-path="evidence.pdf">Snapshot</span>'
            ' (<code>evidence.<wbr>pdf</code>)') in html
    source.write_text("[Escape](../outside.pdf)\n", encoding="utf-8")
    with pytest.raises(ContentError, match="escapes"):
        render_chapter(chapter, [chapter], tmp_path)


def test_collected_body_is_reusable_before_and_after_rendering(tmp_path, monkeypatch) -> None:
    note = tmp_path / "one.md"
    note.write_text(
        "---\nstatus: draft\n---\n# One\n\n"
        "> [!important]\n> Keep `this` **result**. #mark/decision/reuse\n\n"
        "```base\nviews:\n  - type: table\n    order: [chapter]\n```\n\n"
        "```cmd\nexample\n```\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n", encoding="utf-8")
    chapters = parse_manifest(manifest)
    home = Chapter(0, "Home", "home", manifest, "", "home")
    _, documents, _ = collect_notes(
        manifest, chapters, home, read_chapter_content(home, ""), {},
    )
    document = documents[note]
    expected_warnings = [
        f"{note}:6: long paragraph (4 estimated lines at 10 characters; maximum 1). "
        "Split it into shorter paragraphs."
    ]
    commands = []

    def unexpected_work(*args, **kwargs):
        pytest.fail("An already-collected body was parsed or its source read again.")

    monkeypatch.setattr("markdown_it.MarkdownIt.parse", unexpected_work)
    monkeypatch.setattr(Path, "read_text", unexpected_work)
    assert paragraph_warnings(chapters[0], document, 1, 10) == expected_warnings
    expected = (
        '<h1 id="one--one">One</h1>\n'
        '<aside class="content-card content-emphasis" aria-label="Important">\n'
        '<p class="semantic-mark semantic-mark--decision" data-mark-kind="decision" '
        'data-mark-label="reuse" id="mark-one-decision-reuse">'
        '<span class="semantic-mark-content">Keep <code>this</code> <strong>result</strong>. '
        '</span><span class="semantic-mark-rail" aria-label="Paragraph marks">'
        '<a class="semantic-mark-icon semantic-mark-icon--decision" href="#tags" '
        'data-tag-kind="decision" data-tag-label="reuse" aria-label="Decision: reuse">'
        '<span class="resource-icon" data-icon="mark.decision" '
        'aria-hidden="true"></span></a></span></p>\n</aside>\n'
        '<div class="data-table-placeholder" data-base-table="one-base-1"></div>\n'
        '<pre class="command-output"><code>&lt;output&gt;</code></pre>\n'
    )
    for _ in range(2):
        assert render_chapter(
            chapters[0], chapters, tmp_path,
            lambda command: commands.append(command) or "<output>",
            document=document,
        ) == expected
        assert paragraph_warnings(chapters[0], document, 1, 10) == expected_warnings
    assert commands == ["example", "example"]
    assert [(mark.kind, mark.label, mark.text) for mark in document.marks] == [
        ("decision", "reuse", "[!important] Keep `this` **result**."),
    ]


def test_collected_body_retains_resolved_links_assets_and_markdown_dialect(
    tmp_path, monkeypatch,
) -> None:
    (tmp_path / "one.md").write_text(
        "# One\n\n| Formula | Source |\n|---|---|\n"
        "| $\\sqrt{x}$ | [[Other#Details\\|Wikilink]] |\n\n"
        "$$\ny = \\frac{a}{b}\n$$\n\n"
        "[[1]](two.md#Details) [Download](data:application/json;base64,e30=)\n\n"
        "![Diagram](figure.svg)\n\n`[[missing]]`\n",
        encoding="utf-8",
    )
    (tmp_path / "two.md").write_text(
        "---\naliases: Other\n---\n# Two\n\n## Details\n", encoding="utf-8",
    )
    (tmp_path / "figure.svg").write_text("<svg/>", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n", encoding="utf-8")
    chapters = parse_manifest(manifest)
    home = Chapter(0, "Home", "home", manifest, "", "home")
    notes, documents, _ = collect_notes(
        manifest, chapters, home, read_chapter_content(home, ""), {},
    )
    assert [note.slug for note in notes] == ["home", "one", "two"]

    def unexpected_parse(*args, **kwargs):
        pytest.fail("Rendering or diagnostics parsed an already-collected body.")

    monkeypatch.setattr("markdown_it.MarkdownIt.parse", unexpected_parse)
    document = documents[chapters[0].source_path]
    assert paragraph_warnings(chapters[0], document, 5, 80) == []
    rendered = render_chapter(chapters[0], notes, tmp_path, document=document)
    assert "<table>" in rendered
    assert "<msqrt>" in rendered
    assert "<mfrac>" in rendered
    assert 'display="block"' in rendered
    assert '<a href="#two/details">Wikilink</a>' in rendered
    assert '<a href="#two/details">[1]</a>' in rendered
    assert '<a href="data:application/json;base64,e30=">Download</a>' in rendered
    assert '<img src="data:image/svg+xml;base64,PHN2Zy8+" alt="Diagram" />' in rendered
    assert "<code>[[missing]]</code>" in rendered


def test_manifest_defines_order_depth_and_labels(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("# One", encoding="utf-8")
    (tmp_path / "two.md").write_text("# Two", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one|First]]\n  - [Second](two.md)\n", encoding="utf-8")

    chapters = parse_manifest(manifest)

    assert [(item.title, item.depth) for item in chapters] == [("First", 0), ("Second", 1)]
    assert [item.slug for item in chapters] == ["one", "two"]


def test_pipe_tables_math_and_bracketed_citations(tmp_path: Path) -> None:
    (tmp_path / "refs.md").write_text("# References\n\n## Ref 1\n", encoding="utf-8")
    (tmp_path / "one.md").write_text(
        "# One\n\n| Formula | Source |\n|---|---|\n"
        "| $\\sigma = \\sqrt{x^2}$ | [[1]](refs.md#ref-1) |\n\n"
        "$$\ny = \\frac{a}{b}\n$$\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n- [[refs]]\n", encoding="utf-8")
    chapters = parse_manifest(manifest)
    rendered = render_chapter(chapters[0], chapters, tmp_path)
    assert "<table>" in rendered
    assert "<msqrt>" in rendered
    assert "<mfrac>" in rendered
    assert 'display="block"' in rendered
    assert '<a href="#refs/ref-1">[1]</a>' in rendered


@pytest.mark.parametrize("body", [
    "> [!important]\n> **The conclusion.**\n",
    "> [!important]\n>\n> **The conclusion.**\n>\n> Supporting [[two]].\n",
    "> Quotation.\n>\n> > [!important]\n> > **The conclusion.**\n",
])
def test_important_callout_is_an_explicit_semantic_card(tmp_path: Path, body: str) -> None:
    (tmp_path / "one.md").write_text("# One\n\n" + body, encoding="utf-8")
    (tmp_path / "two.md").write_text("# Two\n", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n- [[two]]\n", encoding="utf-8")
    chapters = parse_manifest(manifest)
    rendered = render_chapter(chapters[0], chapters, tmp_path)
    assert '<aside class="content-card content-emphasis" aria-label="Important">' in rendered
    assert '<header class="content-card-title">Important</header>' not in rendered
    assert "<strong>The conclusion.</strong>" in rendered
    assert "[!important]" not in rendered
    assert rendered.count("<aside") == rendered.count("</aside>") == 1
    assert rendered.count("<blockquote>") == rendered.count("</blockquote>")
    if "Supporting" in body:
        assert '<a href="#two">Two</a>' in rendered


def test_emphasis_does_not_infer_from_bold_position_or_other_callouts(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text(
        "# One\n\n**First sentence.**\n\n> Quotation.\n\n> [!custom]\n> Unknown type.\n\n"
        "> [!note]Title without space\n\n> Lead.\n> [!note]\n\n"
        "```\n> [!important]\n> Example only.\n```\n\n`> [!warning]`\n", encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n", encoding="utf-8")
    chapters = parse_manifest(manifest)
    rendered = render_chapter(chapters[0], chapters, tmp_path)
    assert "<aside" not in rendered
    assert rendered.count("<blockquote>") == 4
    assert "[!custom]" in rendered
    assert "[!note]Title without space" in rendered
    assert "[!important]" in rendered
    assert "[!warning]" in rendered


CALLOUTS = {
    # authored keyword: (canonical type, tone, default title)
    "note": ("note", "accent", "Note"),
    "abstract": ("abstract", "accent", "Abstract"),
    "summary": ("abstract", "accent", "Summary"),
    "tldr": ("abstract", "accent", "Tldr"),
    "info": ("info", "accent", "Info"),
    "todo": ("todo", "accent", "Todo"),
    "tip": ("tip", "accent", "Tip"),
    "hint": ("tip", "accent", "Hint"),
    "success": ("success", "success", "Success"),
    "check": ("success", "success", "Check"),
    "done": ("success", "success", "Done"),
    "question": ("question", "warning", "Question"),
    "help": ("question", "warning", "Help"),
    "faq": ("question", "warning", "Faq"),
    "warning": ("warning", "warning", "Warning"),
    "caution": ("warning", "warning", "Caution"),
    "attention": ("warning", "warning", "Attention"),
    "failure": ("failure", "failure", "Failure"),
    "fail": ("failure", "failure", "Fail"),
    "missing": ("failure", "failure", "Missing"),
    "danger": ("danger", "failure", "Danger"),
    "error": ("danger", "failure", "Error"),
    "bug": ("bug", "failure", "Bug"),
    "example": ("example", "accent", "Example"),
    "quote": ("quote", "neutral", "Quote"),
    "cite": ("quote", "neutral", "Cite"),
}


def _render_body(tmp_path: Path, body: str) -> str:
    (tmp_path / "one.md").write_text("# One\n\n" + body, encoding="utf-8")
    (tmp_path / "two.md").write_text("# Two\n", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n- [[two]]\n", encoding="utf-8")
    chapters = parse_manifest(manifest)
    return render_chapter(chapters[0], chapters, tmp_path)


@pytest.mark.parametrize("keyword", sorted(CALLOUTS))
def test_obsidian_callout_types_render_as_titled_tone_cards(tmp_path: Path, keyword: str) -> None:
    kind, tone, title = CALLOUTS[keyword]
    rendered = _render_body(tmp_path, f"> [!{keyword}]\n> Body with `code` and [[two]].\n")
    assert rendered == (
        '<h1 id="one--one">One</h1>\n'
        f'<aside class="content-card content-callout content-callout--{tone}" '
        f'data-callout="{kind}" aria-label="{CALLOUTS[kind][2]}">\n'
        f'<header class="content-card-title">{title}</header>\n'
        '<p>Body with <code>code</code> and <a href="#two">Two</a>.</p>\n'
        '</aside>\n'
    )


@pytest.mark.parametrize("marker,fold", [("WARNING", ""), ("Warning", "+"), ("warning", "-")])
def test_callout_titles_case_and_fold_markers(tmp_path: Path, marker: str, fold: str) -> None:
    rendered = _render_body(
        tmp_path,
        f"> [!{marker}]{fold} Check **[[two|limits]]**\n>\n> First.\n>\n> > [!tip]\n> > Nested.\n",
    )
    assert '<aside class="content-card content-callout content-callout--warning" ' \
        'data-callout="warning" aria-label="Warning">' in rendered
    assert '<header class="content-card-title">Check <strong><a href="#two">limits</a>' \
        '</strong></header>' in rendered
    assert '<p>First.</p>' in rendered
    assert 'data-callout="tip"' in rendered and '>Tip</header>' in rendered
    assert "[!" not in rendered and "<details" not in rendered
    assert rendered.count("<aside") == rendered.count("</aside>") == 2


def test_callout_with_only_a_title_renders_a_titled_card(tmp_path: Path) -> None:
    rendered = _render_body(tmp_path, "> [!success] All checks passed\n")
    assert rendered.endswith(
        '<aside class="content-card content-callout content-callout--success" '
        'data-callout="success" aria-label="Success">\n'
        '<header class="content-card-title">All checks passed</header>\n'
        '</aside>\n'
    )


def test_important_callout_keeps_untitled_emphasis_and_accepts_a_title(tmp_path: Path) -> None:
    rendered = _render_body(tmp_path, "> [!Important]- Key result\n> The conclusion.\n")
    assert '<aside class="content-card content-emphasis" aria-label="Important">\n' \
        '<header class="content-card-title">Key result</header>\n' \
        '<p>The conclusion.</p>\n</aside>' in rendered


@pytest.mark.parametrize("keyword", ["important", "warning"])
def test_paragraph_length_ignores_any_callout_marker(tmp_path: Path, keyword: str) -> None:
    _render_body(tmp_path, f"> [!{keyword}]\n> Twelve chars\n")
    chapter = parse_manifest(tmp_path / "manifest.md")[0]
    assert paragraph_warnings(chapter, read_chapter_content(chapter), 1, 20) == []


def test_code_spans_offer_breaks_only_after_separator_runs(tmp_path: Path) -> None:
    rendered = _render_body(
        tmp_path,
        "`content.py:1444` `src\\obs_html/x` `../a__b` `--flag-name` `/root` `trail.` "
        "`<a&b>.c` `plain`\n",
    )
    assert (
        "<code>content.<wbr>py:<wbr>1444</code> <code>src\\<wbr>obs_<wbr>html/<wbr>x</code> "
        "<code>../a__<wbr>b</code> <code>--flag-<wbr>name</code> <code>/root</code> "
        "<code>trail.</code> <code>&lt;a&amp;b&gt;.<wbr>c</code> <code>plain</code>"
    ) in rendered


def test_local_images_are_embedded_and_downloads_remain_links(tmp_path: Path) -> None:
    (tmp_path / "figure.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>', encoding="utf-8",
    )
    (tmp_path / "one.md").write_text(
        "# One\n\n![Diagram](figure.svg)\n\n"
        "[Drawing](data:application/pdf;base64,JVBERg==)\n"
        "[Unsafe](data:text/html;base64,PHNjcmlwdD4=)\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n", encoding="utf-8")
    chapters = parse_manifest(manifest)
    rendered = render_chapter(chapters[0], chapters, tmp_path)
    assert 'src="data:image/svg+xml;base64,' in rendered
    assert '<a href="data:application/pdf;base64,JVBERg==">' in rendered
    assert 'href="data:text/html' not in rendered


def test_invalid_formula_is_a_content_error_and_currency_stays_text(tmp_path: Path) -> None:
    note = tmp_path / "one.md"
    note.write_text("# One\n\nPrices $5 and $10.\n", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n", encoding="utf-8")
    chapters = parse_manifest(manifest)
    rendered = render_chapter(chapters[0], chapters, tmp_path)
    assert "Prices $5 and $10." in rendered
    assert "<math" not in rendered
    note.write_text("# One\n\n$x^$\n", encoding="utf-8")
    with pytest.raises(ContentError, match="Invalid math formula"):
        render_chapter(chapters[0], chapters, tmp_path)

@pytest.mark.parametrize("target,message", [
    ("missing.png", "does not exist"),
    ("../outside.png", "escapes the vault"),
    ("unsupported.bmp", "Unsupported image type"),
])
def test_invalid_local_images_fail_explicitly(tmp_path: Path, target: str, message: str) -> None:
    (tmp_path / "one.md").write_text(f"# One\n\n![Diagram]({target})\n", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n", encoding="utf-8")
    chapters = parse_manifest(manifest)
    with pytest.raises(ContentError, match=message):
        render_chapter(chapters[0], chapters, tmp_path)


@pytest.mark.parametrize("summaries", [
    "{}",
    "{Count: {filters: 'recordType == \"tag\"', target: '[[one]]'}}",
])
def test_manifest_rejects_summaries_with_migration_to_card_counts(tmp_path: Path, summaries: str) -> None:
    manifest = tmp_path / "manifest.md"
    manifest.write_text(f"---\nsummaries: {summaries}\n---\n- [[one]]\n", encoding="utf-8")
    (tmp_path / "one.md").write_text("# One\n", encoding="utf-8")
    with pytest.raises(ContentError) as error:
        read_manifest(manifest)
    message = str(error.value)
    assert "summaries" in message and "cards" in message and "where" in message


def test_manifest_rejects_numbered_items(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("# One", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("1. [[one]]\n", encoding="utf-8")

    with pytest.raises(ContentError, match="bulleted list; numeric markers"):
        parse_manifest(manifest)


def test_manifest_rejects_paths_outside_the_vault(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.md"
    outside.write_text("# Outside", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[../outside]]\n", encoding="utf-8")

    with pytest.raises(ContentError, match="escapes the vault"):
        parse_manifest(manifest)


def test_manifest_separates_metadata_toc_and_abstract(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("# One", encoding="utf-8")
    (tmp_path / "two.md").write_text("# Two", encoding="utf-8")
    manifest_path = tmp_path / "contents.md"
    prose = "# Context\n\nRead [[two]].\n\n- An abstract list, not navigation.\n"
    manifest_path.write_text(
        "---\ntitle: Example\nowners: [Ada, Lin]\n---\n\n"
        "- [[one|First]]\n  - [[two|Child]]\n\n" + prose, encoding="utf-8",
    )

    manifest = read_manifest(manifest_path)

    assert manifest.metadata == {"title": "Example", "owners": ["Ada", "Lin"]}
    assert [(chapter.title, chapter.depth) for chapter in manifest.chapters] == [
        ("First", 0), ("Child", 1),
    ]
    assert manifest.abstract.strip() == prose.strip()


@pytest.mark.parametrize("title", ["42", "[]", "'   '", "false", "null"])
def test_manifest_rejects_invalid_document_title(tmp_path: Path, title: str) -> None:
    (tmp_path / "one.md").write_text("# One", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text(f"---\ntitle: {title}\n---\n- [[one]]\n", encoding="utf-8")
    with pytest.raises(ContentError, match="title must be"):
        read_manifest(manifest)


def test_manifest_accepts_explicitly_empty_document_title(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("# One", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("---\ntitle: ''\n---\n- [[one]]\n", encoding="utf-8")
    assert read_manifest(manifest).metadata["title"] == ""


def test_manifest_reserves_generated_page_slugs_and_rejects_self_reference(tmp_path: Path) -> None:
    (tmp_path / "home.md").write_text("# Home", encoding="utf-8")
    (tmp_path / "abstract.md").write_text("# Abstract", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[home]]\n- [[abstract]]\n", encoding="utf-8")
    assert [chapter.slug for chapter in parse_manifest(manifest)] == ["home-2", "abstract"]
    manifest.write_text("- [[manifest]]\n", encoding="utf-8")
    with pytest.raises(ContentError, match="cannot include itself"):
        parse_manifest(manifest)


@pytest.mark.parametrize("aliases", ["[Other, Second]", "Other"])
def test_wikilinks_resolve_aliases_and_keep_explicit_labels(tmp_path: Path, aliases: str) -> None:
    (tmp_path / "one.md").write_text(
        "Read [[oThEr]] and [[Other|custom label]].", encoding="utf-8",
    )
    (tmp_path / "two.md").write_text(f"---\naliases: {aliases}\n---\n# Two", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n- [[two]]\n", encoding="utf-8")
    chapters = parse_manifest(manifest)
    rendered = render_chapter(chapters[0], chapters, tmp_path)
    assert '<a href="#two">Two</a>' in rendered
    assert '<a href="#two">custom label</a>' in rendered


def test_quantity_alias_renders_its_canonical_value_and_unit(tmp_path: Path) -> None:
    (tmp_path / "chapter.md").write_text(
        "See [[flatness_A]], [[empirical_target]], [[collision_probability]], and "
        "[[flatness_A|the explicit label]].", encoding="utf-8",
    )
    (tmp_path / "probability.md").write_text(
        "---\nkind: quantity\nvalue: 0.5\naliases: [collision_probability]\n"
        "source: '[[drawing]]'\n---\n# Collision probability\n",
        encoding="utf-8",
    )
    (tmp_path / "target.md").write_text(
        "---\nkind: quantity\nvalue: 20\nunit: µm\naliases: [empirical_target]\n"
        "source: '[[drawing]]'\n---\n# Empirical target\n",
        encoding="utf-8",
    )
    (tmp_path / "flatness.md").write_text(
        "---\nkind: quantity\nvalue: 20\nunit: µm\naliases: [flatness_A]\n"
        "source: '[[drawing]]'\n---\n# Datum A flatness\n\n"
        "The drawing tolerance is a total zone width.\n",
        encoding="utf-8",
    )
    (tmp_path / "drawing.md").write_text("# Drawing", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text(
        "- [[chapter]]\n- [[flatness]]\n- [[probability]]\n- [[target]]\n- [[drawing]]\n",
        encoding="utf-8",
    )

    chapters = parse_manifest(manifest)
    rendered = render_chapter(chapters[0], chapters, tmp_path)

    assert '<a href="#flatness">20 µm</a>' in rendered
    assert '<a href="#target">20 µm</a>' in rendered
    assert '<a href="#probability">0.5</a>' in rendered
    assert '<a href="#flatness">the explicit label</a>' in rendered


@pytest.mark.parametrize("metadata", [
    "value: .nan\nunit: µm\naliases: [flatness_A]\nsource: '[[drawing]]'",
    "value: .inf\nunit: µm\naliases: [flatness_A]\nsource: '[[drawing]]'",
    "value: true\nunit: µm\naliases: [flatness_A]\nsource: '[[drawing]]'",
    "value: '20'\nunit: µm\naliases: [flatness_A]\nsource: '[[drawing]]'",
    "unit: µm\naliases: [flatness_A]\nsource: '[[drawing]]'",
    "value: 20\nunit: ''\naliases: [flatness_A]\nsource: '[[drawing]]'",
    "value: 20\nunit: 42\naliases: [flatness_A]\nsource: '[[drawing]]'",
    "value: 20\nunit: µm\naliases: [flatness_A, other]\nsource: '[[drawing]]'",
    "value: 20\nunit: µm\naliases: [not a variable]\nsource: '[[drawing]]'",
    "value: 20\nunit: µm\nsource: '[[drawing]]'",
    "value: 20\nunit: µm\naliases: [flatness_A]\nsource: ''",
    "value: 20\nunit: µm\naliases: [flatness_A]\nsource: drawing",
])
def test_invalid_quantity_metadata_is_rejected(tmp_path: Path, metadata: str) -> None:
    (tmp_path / "quantity.md").write_text(
        "---\nkind: quantity\n" + metadata + "\n---\n# Quantity\n",
        encoding="utf-8",
    )
    (tmp_path / "drawing.md").write_text("# Drawing", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[quantity]]\n", encoding="utf-8")

    with pytest.raises(ContentError, match="finite|Quantity|Frontmatter"):
        chapters = parse_manifest(manifest)
        render_chapter(chapters[0], chapters, tmp_path)


def test_alias_ambiguity_is_explicit_and_exact_note_path_wins(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("[[Shared]]", encoding="utf-8")
    for name in ("two", "three"):
        (tmp_path / f"{name}.md").write_text("---\naliases: [Shared, one]\n---\n", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n- [[two]]\n- [[three]]\n", encoding="utf-8")
    chapters = parse_manifest(manifest)
    with pytest.raises(ContentError, match="Ambiguous note name or alias"):
        render_chapter(chapters[0], chapters, tmp_path)
    (tmp_path / "one.md").write_text("[[one]]", encoding="utf-8")
    assert '<a href="#one">One</a>' in render_chapter(chapters[0], chapters, tmp_path)


@pytest.mark.parametrize("metadata", [
    "aliases: [good, 42]", "aliases: ''", "aliases: {}", "aliases: null",
    "kind: glossary\nterm: BLUF", "kind: glossary\nterm: ''\ndefinition: Content",
])
def test_invalid_semantic_metadata_reports_errors(tmp_path: Path, metadata: str) -> None:
    (tmp_path / "one.md").write_text(f"---\n{metadata}\n---\n# One", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n", encoding="utf-8")
    with pytest.raises(ContentError):
        read_chapter_content(parse_manifest(manifest)[0])


@pytest.mark.parametrize(("profile", "expected"), [
    ("", {"layout": "paged", "heading": "cover",
          "pages": [{"page": "cover"}, {"page": "abstract", "title": "Abstract"},
                    {"page": "contents", "title": "Contents"}],
          "figures": {"numbering": "none", "label": "Figure", "labelPlural": "Figures"},
          "print": {"paper": "A4", "margin": "20mm"}, "cssSnippets": [],
          "query": {"scope": "chapters"}}),
    ("obsHtml:\n  layout: scrolling\n  pages: [{page: contents, title: Inhalt}, {page: cover}]\n"
     "  print: {paper: Letter}\n"
     "  cssSnippets: [house]\n",
     {"layout": "scrolling", "heading": "cover",
      "pages": [{"page": "contents", "title": "Inhalt"}, {"page": "cover"}],
      "figures": {"numbering": "none", "label": "Figure", "labelPlural": "Figures"},
      "print": {"paper": "Letter", "margin": "20mm"}, "cssSnippets": ["house"],
      "query": {"scope": "chapters"}}),
])
def test_manifest_presentation_profile_resolves_over_schema_defaults(
    tmp_path: Path, profile: str, expected,
) -> None:
    (tmp_path / "one.md").write_text("# One", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text(f"---\n{profile}title: Doc\n---\n- [[one]]\n", encoding="utf-8")
    assert read_manifest(manifest).presentation == expected


@pytest.mark.parametrize(("profile", "body", "message"), [
    ("pages: [{page: cover}, {page: cover}]", "", "at most once"),
    ("pages: [{page: cover}, {page: contents}]", "Abstract text.\n", "abstract page"),
    ("pages: [{page: cover, title: Cover}]", "", "obsHtml"),
    ("pages: [{page: appendix}]", "", "obsHtml"),
    ("layout: book", "", "obsHtml"),
    ("heading: line", "", "obsHtml"),
    ("heading: compact", "", "no cover"),
    ("heading: compact, pages: []", "", "at least one page"),
])
def test_manifest_presentation_profile_rejects_invalid_declarations(
    tmp_path: Path, profile: str, body: str, message: str,
) -> None:
    (tmp_path / "one.md").write_text("# One", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text(f"---\nobsHtml: {{{profile}}}\n---\n- [[one]]\n\n{body}", encoding="utf-8")
    with pytest.raises(ContentError, match=message):
        read_manifest(manifest)


def test_manifest_without_front_pages_and_abstract_is_valid(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("# One", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("---\nobsHtml: {pages: []}\n---\n- [[one]]\n", encoding="utf-8")
    assert read_manifest(manifest).presentation["pages"] == []


def test_manifest_without_toc_is_an_abstract_only_document(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.md"
    manifest.write_text(
        "---\nobsHtml: {heading: compact, pages: [{page: abstract}]}\n---\n"
        "Lead.\n\n- [[not-a-chapter]]\n", encoding="utf-8",
    )
    parsed = read_manifest(manifest)
    assert parsed.chapters == []
    assert parsed.abstract == "Lead.\n\n- [[not-a-chapter]]\n"
    assert parsed.presentation["heading"] == "compact"


def test_media_strips_center_only_images_with_symbolic_separators(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text(
        "![First](https://example.com/first.svg) → ![Second](https://example.com/second.svg)\n\n"
        "Use ![First](https://example.com/first.svg) with ![Second](https://example.com/second.svg).\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n", encoding="utf-8")
    chapters = parse_manifest(manifest)
    rendered = render_chapter(chapters[0], chapters, tmp_path)
    assert rendered.count('class="media-strip"') == 1
    assert "<p>Use " in rendered


def test_note_links_in_code_remain_literal_and_heading_links_resolve(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text(
        "# One\n\n`[[missing]]`\n\n```text\n[[also missing]]\n```\n\n"
        "[[two#Details|more]] [markdown](two.md#Details)\n", encoding="utf-8",
    )
    (tmp_path / "two.md").write_text("# Two\n\n## Details\n\nBody.\n\n[local](#Details)", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n- [[two]]\n", encoding="utf-8")
    chapters = parse_manifest(manifest)
    rendered = render_chapter(chapters[0], chapters, tmp_path)
    assert "<code>[[missing]]</code>" in rendered
    assert "[[also missing]]" in rendered
    assert rendered.count('href="#two/details"') == 2
    details = render_chapter(chapters[1], chapters, tmp_path)
    assert '<h2 id="two--details">' in details
    assert 'href="#two/details"' in details
    (tmp_path / "one.md").write_text("[[two#Absent]]", encoding="utf-8")
    with pytest.raises(ContentError, match="Unresolved note heading"):
        render_chapter(chapters[0], chapters, tmp_path)


def test_silent_command_fence_renders_nothing_and_is_not_a_display_command(tmp_path: Path) -> None:
    (tmp_path / "chapter.md").write_text(
        "# Chapter\n\nBefore.\n\n```cmd silent\nproduce-file\n```\n\nAfter.\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n", encoding="utf-8")
    chapters = parse_manifest(manifest)

    rendered = render_chapter(
        chapters[0],
        chapters,
        tmp_path,
        command_runner=lambda _command: pytest.fail("Silent fence was rendered as a display command."),
    )

    assert "Before." in rendered
    assert "After." in rendered
    assert "produce-file" not in rendered


def test_note_links_resolve_canonical_paragraph_mark_anchors(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text(
        "[[02_system_description.md#mark-02-system-description-open-point-datum-a-continuity]]",
        encoding="utf-8",
    )
    (tmp_path / "02_system_description.md").write_text(
        "Resolve datum A continuity. #mark/open_point/datum_a_continuity\n", encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n- [[02_system_description]]\n", encoding="utf-8")
    chapters = parse_manifest(manifest)

    rendered = render_chapter(chapters[0], chapters, tmp_path)

    assert 'href="#02-system-description/mark-02-system-description-open-point-datum-a-continuity"' in rendered


@pytest.mark.parametrize("reference", [
    "[[owner#mark-owner-open-point-datum-a-continuity]]",
    "[[owner#mark-owner-open-point-datum-a-continuity|Copied question]]",
    "[Copied question](owner.md#mark-owner-open-point-datum-a-continuity)",
])
def test_open_point_reference_uses_existing_mark_identity(tmp_path: Path, reference: str) -> None:
    (tmp_path / "one.md").write_text(reference, encoding="utf-8")
    (tmp_path / "owner.md").write_text(
        "Does the datum continue? #mark/open_point/datum_a_continuity\n", encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n- [[owner]]\n", encoding="utf-8")
    chapters = parse_manifest(manifest)

    rendered = render_chapter(chapters[0], chapters, tmp_path)

    assert '>#mark/open_point/datum_a_continuity</a>' in rendered
    assert 'data-tag-kind="open_point"' in rendered
    assert 'data-tag-label="datum_a_continuity"' in rendered
    assert 'href="#owner/mark-owner-open-point-datum-a-continuity"' in rendered
    assert "Copied question" not in rendered


def test_note_links_reject_nonexistent_canonical_paragraph_mark_anchors(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text(
        "[[chapter#mark-chapter-open-point-missing]]", encoding="utf-8",
    )
    (tmp_path / "chapter.md").write_text(
        "A different open point. #mark/open_point/actual_label\n", encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n- [[chapter]]\n", encoding="utf-8")
    chapters = parse_manifest(manifest)

    with pytest.raises(ContentError, match="Unresolved note heading"):
        render_chapter(chapters[0], chapters, tmp_path)


def test_relative_nested_note_links_and_vault_escape(tmp_path: Path) -> None:
    (tmp_path / "folder").mkdir()
    (tmp_path / "folder" / "one.md").write_text(
        "[[two]] [other](two.md)\n", encoding="utf-8",
    )
    (tmp_path / "folder" / "two.md").write_text("# Nested two", encoding="utf-8")
    (tmp_path / "two.md").write_text("# Root two", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[folder/one]]\n- [[folder/two]]\n- [[two]]\n", encoding="utf-8")
    chapters = parse_manifest(manifest)
    rendered = render_chapter(chapters[0], chapters, tmp_path)
    assert rendered.count('href="#folder-two"') == 2
    (tmp_path / "folder" / "one.md").write_text("[[../../outside]]", encoding="utf-8")
    with pytest.raises(ContentError, match="escapes the vault"):
        render_chapter(chapters[0], chapters, tmp_path)


def test_rendered_chapter_uses_body_only_and_links_internally(tmp_path: Path) -> None:
    first = tmp_path / "first.md"
    first.write_text(
        "---\ncontrol: hidden\n---\n# First\n\nSee [[second|Next]].\n<script>bad()</script>\n",
        encoding="utf-8",
    )
    (tmp_path / "second.md").write_text("# Second", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[first]]\n- [[second]]\n", encoding="utf-8")
    chapters = parse_manifest(manifest)

    rendered = render_chapter(chapters[0], chapters, tmp_path)

    assert "control: hidden" not in rendered
    assert '<a href="#second">Next</a>' in rendered
    assert "<script>" not in rendered
    assert "&lt;script&gt;bad()&lt;/script&gt;" in rendered


def test_frontmatter_is_normalized_for_artifact_data(tmp_path: Path) -> None:
    note = tmp_path / "chapter.md"
    note.write_text(
        "---\n"
        "status: active\n"
        "published: 2026-10-19\n"
        "owner:\n"
        "  name: Ada\n"
        "tags: [design, artifact]\n"
        "---\n"
        "# Chapter\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n", encoding="utf-8")

    chapter = parse_manifest(manifest)[0]

    assert read_chapter_content(chapter).frontmatter == {
        "status": "active",
        "published": "2026-10-19",
        "owner": {"name": "Ada"},
        "tags": ["design", "artifact"],
    }


def test_cmd_fence_uses_runner_and_escapes_derived_output(tmp_path: Path) -> None:
    note = tmp_path / "chapter.md"
    note.write_text("# CLI\n\n````cmd\nshow help\n````\n", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n", encoding="utf-8")
    chapters = parse_manifest(manifest)
    commands = []

    rendered = render_chapter(
        chapters[0],
        chapters,
        tmp_path,
        lambda command: commands.append(command) or "usage: <owner>\n",
    )

    assert commands == ["show help"]
    assert '<pre class="command-output"><code>usage: &lt;owner&gt;\n</code></pre>' in rendered
    assert "show help" not in rendered


def test_cmd_fence_requires_explicit_authorization(tmp_path: Path) -> None:
    note = tmp_path / "chapter.md"
    note.write_text("````cmd\necho unsafe\n````\n", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n", encoding="utf-8")
    chapters = parse_manifest(manifest)

    with pytest.raises(ContentError, match="explicit command execution authorization"):
        render_chapter(chapters[0], chapters, tmp_path)


def test_base_fence_is_parsed_and_rendered_in_place(tmp_path: Path) -> None:
    note = tmp_path / "chapter.md"
    note.write_text(
        "Before.\n\n"
        "```base\n"
        "obsHtml: {records: chapter}\n"
        "properties:\n"
        "  chapter:\n"
        "    displayName: Chapter\n"
        "views:\n"
        "  - type: table\n"
        "    name: Summary\n"
        "    order: [chapter, bottom line]\n"
        "```\n\n"
        "After.\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n", encoding="utf-8")
    chapter = parse_manifest(manifest)[0]

    document = read_chapter_content(chapter)
    rendered = render_chapter(chapter, [chapter], tmp_path, document=document)

    assert len(document.tables) == 1
    assert document.tables[0].definition["views"][0]["order"] == ["chapter", "bottom line"]
    assert 'data-base-table="chapter-base-1"' in rendered
    assert rendered.index("Before.") < rendered.index("data-base-table") < rendered.index("After.")
    assert "recordType" not in rendered


def test_missing_local_attachments_are_rejected(tmp_path: Path) -> None:
    note = tmp_path / "chapter.md"
    note.write_text("[Local file](attachment.pdf)", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n", encoding="utf-8")
    chapters = parse_manifest(manifest)

    with pytest.raises(ContentError, match="Attachment does not exist"):
        render_chapter(chapters[0], chapters, tmp_path)


def test_base_view_keeps_standard_group_and_multiple_sort_directives(tmp_path: Path) -> None:
    (tmp_path / "chapter.md").write_text(
        "```base\n"
        "views:\n  - type: table\n    name: Nested\n    order: [label]\n"
        "    groupBy: {property: type, direction: ASC}\n"
        "    sort:\n      - property: label\n        direction: DESC\n"
        "      - property: author\n        direction: ASC\n"
        "```\n", encoding="utf-8",
    )
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    chapter = parse_manifest(tmp_path / "manifest.md")[0]
    view = read_chapter_content(chapter).tables[0].definition["views"][0]

    assert view["groupBy"] == {"property": "type", "direction": "ASC"}
    assert view["sort"] == [
        {"property": "label", "direction": "DESC"}, {"property": "author", "direction": "ASC"},
    ]


def test_base_max_rows_is_a_positive_integer_viewport_option(tmp_path: Path) -> None:
    source = (
        "```base\nviews:\n  - type: table\n    order: [label]\n"
        "obsHtml:\n  maxRows: 10\n```\n"
    )
    (tmp_path / "chapter.md").write_text(source, encoding="utf-8")
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    chapter = parse_manifest(tmp_path / "manifest.md")[0]

    assert read_chapter_content(chapter).tables[0].definition["obsHtml"]["maxRows"] == 10


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "ten", "{value: 10}"])
def test_base_max_rows_rejects_invalid_viewport_options(
    tmp_path: Path, value: str,
) -> None:
    (tmp_path / "chapter.md").write_text(
        "```base\nviews:\n  - type: table\n    order: [label]\n"
        f"obsHtml:\n  maxRows: {value}\n```\n",
        encoding="utf-8",
    )
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    chapter = parse_manifest(tmp_path / "manifest.md")[0]

    with pytest.raises(ContentError, match=r"Invalid base definition|; see capabilities/bases\."):
        read_chapter_content(chapter)


@pytest.mark.parametrize(
    "directive",
    [
        "groupBy: type",
        "groupBy: {property: type, direction: SIDEWAYS}",
        "sort: [{direction: ASC}]",
        "sort: [{property: '', direction: ASC}]",
    ],
)
def test_base_view_rejects_malformed_group_and_sort(tmp_path: Path, directive: str) -> None:
    (tmp_path / "chapter.md").write_text(
        "```base\nviews:\n  - type: table\n    name: Bad\n"
        f"    order: [label]\n    {directive}\n```\n", encoding="utf-8",
    )
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    chapter = parse_manifest(tmp_path / "manifest.md")[0]

    with pytest.raises(ContentError, match=r"Invalid base definition|; see capabilities/bases\."):
        read_chapter_content(chapter)


def test_removed_property_is_ordinary_frontmatter_and_marks_render_once(tmp_path: Path) -> None:
    note = tmp_path / "chapter.md"
    note.write_text(
        "---\nbottom line: The **canonical** result.\n---\n"
        "# Chapter\n\n"
        "#mark/open_point/tolerance_scope Which **tolerance** applies? "
        "#mark/decision/review_tolerance\n\n"
        "The supplier #mark/risk/supplier_delay may be [late](https://example.com).\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n", encoding="utf-8")
    chapter = parse_manifest(manifest)[0]

    document = read_chapter_content(chapter)
    rendered = render_chapter(chapter, [chapter], tmp_path)

    assert document.frontmatter["bottom line"] == "The **canonical** result."
    assert [(mark.kind, mark.label, mark.text) for mark in document.marks] == [
        ("open_point", "tolerance_scope", "Which **tolerance** applies?"),
        ("decision", "review_tolerance", "Which **tolerance** applies?"),
        ("risk", "supplier_delay", "The supplier may be [late](https://example.com)."),
    ]
    assert "data-chapter-bluf" not in rendered
    assert 'data-mark-kind="open_point decision"' in rendered
    assert 'id="mark-chapter-open-point-tolerance-scope"' in rendered
    assert rendered.count('class="semantic-mark-icon ') == 3
    assert 'aria-label="Open Point: tolerance scope"' in rendered
    assert 'aria-label="Decision: review tolerance"' in rendered
    assert 'href="#tags" data-tag-kind="open_point" data-tag-label="tolerance_scope"' in rendered
    assert 'href="#tags" data-tag-kind="decision" data-tag-label="review_tolerance"' in rendered
    assert '<span class="semantic-mark-content">' in rendered
    assert '<span class="semantic-mark-rail" aria-label="Paragraph marks">' in rendered
    assert "Which <strong>tolerance</strong> applies?" in rendered
    assert 'The supplier may be <a href="https://example.com">late</a>.' in rendered
    assert "#mark/" not in rendered


def test_marker_inside_inline_code_does_not_mark_paragraph(tmp_path: Path) -> None:
    (tmp_path / "chapter.md").write_text(
        "Use `#mark/risk/example` to mark a risk.\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n", encoding="utf-8")
    chapter = parse_manifest(manifest)[0]

    document = read_chapter_content(chapter)
    rendered = render_chapter(chapter, [chapter], tmp_path)

    assert document.marks == ()
    assert "<code>#mark/<wbr>risk/<wbr>example</code>" in rendered


@pytest.mark.parametrize(
    ("bordered_tags", "card_count", "titles"),
    [
        ((), 0, []),
        (("risk",), 2, ["Risk", "Risk"]),
        (("risk", "decision"), 2, ["Risk / Decision", "Risk"]),
    ],
)
def test_tag_borders_are_optional_shared_cards(
    tmp_path: Path, bordered_tags: tuple[str, ...], card_count: int, titles: list[str]
) -> None:
    from html.parser import HTMLParser

    class CardParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.parents: list[str] = []
            self.titles: list[str] = []
            self.card_paragraphs = 0

        def handle_starttag(self, tag, attrs) -> None:
            if tag == "p" and self.parents and self.parents[-1] == "section":
                self.card_paragraphs += 1
            self.parents.append(tag)

        def handle_endtag(self, tag) -> None:
            assert self.parents.pop() == tag

        def handle_data(self, data) -> None:
            if self.parents and self.parents[-1] == "header":
                self.titles.append(data)

    (tmp_path / "chapter.md").write_text(
        "First **prose**. #mark/risk/first #mark/decision/chosen\n\n"
        "Second prose. #mark/risk/second\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n", encoding="utf-8")
    chapters = parse_manifest(manifest)
    rendered = render_chapter(
        chapters[0], chapters, tmp_path, bordered_tags=bordered_tags
    )
    parser = CardParser()
    parser.feed(rendered)

    assert parser.parents == []
    assert parser.card_paragraphs == card_count
    assert parser.titles == titles
    assert rendered.count('<section class="content-card">') == card_count
    assert rendered.count('class="semantic-mark-rail"') == 2
    assert rendered.count('class="semantic-mark-icon ') == 3
    assert "First <strong>prose</strong>." in rendered
    assert "Second prose." in rendered


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("Text. #mark/unknown/example\n", "Unknown paragraph marker kind"),
        ("Text. #mark/open_point/Bad-Label\n", "Malformed paragraph marker"),
        (
            "One. #mark/issue/repeated\n\nTwo. #mark/issue/repeated\n",
            "Duplicate paragraph marker",
        ),
    ],
)
def test_invalid_paragraph_markers_fail_generation(
    tmp_path: Path, source: str, message: str
) -> None:
    (tmp_path / "chapter.md").write_text(source, encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n", encoding="utf-8")
    chapter = parse_manifest(manifest)[0]

    with pytest.raises(ContentError, match=message):
        read_chapter_content(chapter)
@pytest.mark.parametrize("subtitle", ["''", "[]", "42", "null"])
def test_manifest_rejects_invalid_subtitle(tmp_path: Path, subtitle: str) -> None:
    (tmp_path / "one.md").write_text("# One", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text(f"---\nsubtitle: {subtitle}\n---\n- [[one]]\n", encoding="utf-8")
    with pytest.raises(ContentError, match="subtitle must be a non-empty Markdown string"):
        read_manifest(manifest)
