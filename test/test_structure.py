import json
import re
import tomllib
from pathlib import Path
import yaml
from obs_html.cards import parse_card_spec
from obs_html.content import collect_notes, read_manifest
from obs_html.content import read_chapter_content, render_chapter, Chapter


ROOT = Path(__file__).parents[1]
USER_FACING_DIRECTORIES = (ROOT / "data", ROOT / "spec")


def test_config_references_existing_json_schema() -> None:
    config_path = ROOT / "src" / "obs_html" / "cfg.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    schema_path = config_path.parent / config["$schema"]

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_build_output_configuration_keeps_distributions_out_of_root() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["tool"]["hatch"]["build"]["directory"] == "data/data_output/dist"
    assert not (ROOT / "dist").exists()


def test_spec_manifest_is_a_nested_list_of_existing_links() -> None:
    manifest_path = ROOT / "spec" / "manifest.md"
    manifest = read_manifest(manifest_path)
    previous_depth = 0

    assert manifest.chapters
    assert manifest.metadata["title"] == "obs-html"
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
        "organization", "template", "sap number", "authors", "reviewers", "approvers",
        "copyright", "confidentiality", "legal entity",
    ):
        assert frontmatter[field] == ""
        assert field not in manifest.metadata
    assert "product" not in manifest.metadata


def test_user_facing_directories_stay_within_entry_caps() -> None:
    violations = []
    for directory in USER_FACING_DIRECTORIES:
        children = list(directory.iterdir())
        folders = [child for child in children if child.is_dir() and not child.name.startswith(".")]
        files = [
            child
            for child in children
            if child.is_file() and not child.name.startswith(".")
        ]
        if len(folders) > 5 or len(files) > 5:
            violations.append((directory.relative_to(ROOT), len(folders), len(files)))

    assert violations == []


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
    assert "This report describes" not in rendered
    assert "img.shields.io" not in manifest.abstract
    assert "data:image" not in rendered
    assert '<p class="media-strip">' in rendered