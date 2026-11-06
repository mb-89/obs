from pathlib import Path

import yaml

from obs_html_interim.content import (
    Chapter,
    collect_notes,
    read_chapter_content,
    read_manifest,
    render_chapter,
)

ROOT = Path(__file__).parents[2]


def test_spec_manifest_is_a_nested_list_of_existing_links() -> None:
    manifest_path = ROOT / "spec" / "manifest.md"
    manifest = read_manifest(manifest_path)
    previous_depth = 0

    assert manifest.chapters
    assert manifest.metadata["title"] == "obs"
    assert manifest.abstract.strip()
    for index, chapter in enumerate(manifest.chapters):
        depth = chapter.depth
        assert depth == 0 if index == 0 else depth <= previous_depth + 1
        previous_depth = depth
        assert chapter.source_path.is_file()


def test_spec_manifest_reaches_every_design_input_note() -> None:
    manifest_path = ROOT / "spec" / "manifest.md"
    manifest = read_manifest(manifest_path)
    design_inputs = set((ROOT / "spec" / "design_input").glob("*.md"))

    assert design_inputs <= {chapter.source_path for chapter in manifest.chapters}


def test_every_spec_wiki_link_resolves() -> None:
    manifest_path = ROOT / "spec" / "manifest.md"
    manifest = read_manifest(manifest_path)
    home = Chapter(0, "Home", "home", manifest_path, "", "home")
    home_document = read_chapter_content(home, manifest.metadata["subtitle"])
    notes, documents, reference_index = collect_notes(
        manifest_path, manifest.chapters, home, home_document, manifest.metadata,
    )

    for note in notes:
        render_chapter(
            note, notes, manifest_path.parent, document=documents.get(note.source_path),
            command_runner=lambda _command: "", reference_index=reference_index,
        )


def test_spec_manifest_declares_generic_paged_presentation() -> None:
    manifest_path = ROOT / "spec" / "manifest.md"
    manifest = read_manifest(manifest_path)
    frontmatter = yaml.safe_load(manifest_path.read_text(encoding="utf-8").split("---", 2)[1])

    assert manifest.metadata["obsHtml"] == {
        "layout": "paged",
        "pages": [
            {"page": "cover"},
            {"page": "abstract", "title": "Abstract"},
            {"page": "contents", "title": "Contents"},
        ],
    }
    assert manifest.presentation["layout"] == "paged"
    assert manifest.presentation["pages"] == [
        {"page": "cover"},
        {"page": "abstract", "title": "Abstract"},
        {"page": "contents", "title": "Contents"},
    ]
    assert frontmatter["product"] == {"name": "", "version": ""}
    for field in (
        "organization", "template", "document number", "authors", "reviewers", "approvers",
        "copyright", "confidentiality", "legal entity",
    ):
        assert frontmatter[field] == ""
        assert field not in manifest.metadata
    assert "product" not in manifest.metadata


def test_dogfood_subtitle_owns_hosted_logos_not_abstract() -> None:
    manifest_path = ROOT / "spec" / "manifest.md"
    manifest = read_manifest(manifest_path)
    home = Chapter(0, "Home", "home", manifest_path, "", "home")
    document = read_chapter_content(home, manifest.metadata["subtitle"])
    rendered = render_chapter(home, manifest.chapters, manifest_path.parent, document=document)

    assert '<img src="https://img.shields.io/badge/Obsidian-' in rendered
    assert 'alt="Obsidian"' in rendered
    assert '<img src="https://img.shields.io/badge/HTML5-' in rendered
    assert 'alt="HTML5"' in rendered
    assert rendered.index('alt="Obsidian"') < rendered.index("→") < rendered.index('alt="HTML5"')
    assert "This artifact describes" not in rendered
    assert "img.shields.io" not in manifest.abstract
    assert "data:image" not in rendered
    assert '<p class="media-strip">' in rendered
