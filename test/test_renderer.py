import base64
import json
import re
from importlib.resources import files
from pathlib import Path

import pytest

from obs_html_interim.content import ContentError, parse_manifest
from obs_html_interim.renderer import render_artifact
from obs_html_interim.artifact_data import decode_artifact_data


HEX_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def test_manifest_dependencies_remain_canonical_without_document_metadata_row(tmp_path):
    manifest = tmp_path / "manifest.md"
    manifest.write_text(
        "---\ncanonicalNotes: [source-only]\nprojectField: Keep this metadata\n---\n"
        "- [[chapter]]\n", encoding="utf-8",
    )
    (tmp_path / "chapter.md").write_text("# Chapter\n", encoding="utf-8")
    (tmp_path / "source-only.md").write_text(
        "---\nobsHtml: {document: false}\nkind: data\n---\n", encoding="utf-8",
    )
    data = decode_artifact_data(render_artifact(manifest, parse_manifest(manifest)))
    home = data["notes"][0]
    assert data["document"]["metadata"]["canonicalNotes"] == ["source-only"]
    assert data["document"]["metadata"]["projectField"] == "Keep this metadata"
    assert any(note["sourcePath"] == "source-only.md" for note in data["notes"])
    assert data["toc"] == ["home", "chapter"]
    assert home["tables"] == [], "metadata stays canonical without an implicit view"


def test_artifact_is_one_self_contained_semantic_document(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text(
        "---\nstatus: active\n---\n# One\n\nFirst body.", encoding="utf-8"
    )
    (tmp_path / "two.md").write_text("# Two\n\nSecond body.", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one|First]]\n  - [[two|Second]]\n", encoding="utf-8")
    chapters = parse_manifest(manifest)

    artifact = render_artifact(manifest, chapters)

    assert artifact.startswith("<!doctype html>")
    assert artifact.count('<style id="artifact-styles">') == 1
    assert artifact.count('<script id="query-script"') == 1
    assert artifact.count('<script id="artifact-script"') == 1
    assert artifact.count('class="chapter"') == 1
    assert artifact.count('<article class="chapter" data-active-chapter>') == 1
    store = re.search(r'<script id="artifact-data"[^>]*>(.*?)</script>', artifact, re.DOTALL)
    assert store
    data = decode_artifact_data(store[0])
    assert [(item["title"], item["depth"]) for item in data["notes"]] == [
        ("manifest", 0),
        ("First", 0),
        ("Second", 1),
    ]
    assert data["toc"] == ["home", "one", "two"]
    assert data["notes"][1]["html"].count("First body.") == 1
    assert data["notes"][2]["html"].count("Second body.") == 1
    assert data["notes"][1]["frontmatter"] == {"status": "active"}
    assert 'data-frontmatter-toggle' in artifact
    assert 'data-frontmatter-body' in artifact
    assert " style=" not in artifact
    assert artifact.count('<script id="obs-comments"') == 1
    assert '<script id="obs-comments" type="application/json" data-comment-island>' in artifact
    assert '{"version":2,"annotations":[],"reviewers":[],"reviews":[]}' in artifact


def test_artifact_serializes_semantics_and_chapter_owned_tables(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text(
        "# One\n\nResolve this soon. #mark/open_point/which_option\n\n"
        "```base\n"
        "obsHtml: {records: tag}\n"
        "properties:\n  label:\n    displayName: Label\n"
        "views:\n  - type: table\n    name: Tags\n    order: [label]\n"
        "```\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one|First]]\n", encoding="utf-8")

    artifact = render_artifact(
        manifest,
        parse_manifest(manifest),
        facet_distinct_ratio=0.4,
    )
    store = re.search(r'<script id="artifact-data"[^>]*>(.*?)</script>', artifact, re.DOTALL)
    assert store
    data = decode_artifact_data(store[0])

    assert data["facetDistinctRatio"] == 0.4
    assert data["tablePageSize"] == json.loads(
        files("obs_html_interim").joinpath("cfg.json").read_text(encoding="utf-8")
    )["artifact"]["tablePageSize"]
    assert "generatedViews" not in data
    assert "glossaryEntries" not in data
    chapter = data["notes"][1]
    assert chapter["tables"] == [{
        "key": "one-base-1",
        "definition": {
            "obsHtml": {"records": "tag"},
            "properties": {"label": {"displayName": "Label"}},
            "views": [{"type": "table", "name": "Tags", "order": ["label"]}],
        },
    }]
    assert chapter["marks"] == [{
        "kind": "open_point",
        "label": "which_option",
        "text": "Resolve this soon.",
        "html": "Resolve this soon.",
        "anchor": "mark-one-open-point-which-option",
        "backlinks": [{"href": "#one/@mark-one-open-point-which-option", "label": "First"}],
    }]


def test_open_point_backlinks_keep_canonical_body_and_property_locations(tmp_path: Path) -> None:
    target = "owner#mark-owner-open-point-datum-a-continuity"
    (tmp_path / "owner.md").write_text(
        "# Owner\n\nDoes the datum continue? #mark/open_point/datum_a_continuity\n",
        encoding="utf-8",
    )
    (tmp_path / "referrer.md").write_text(
        f"---\nOpen: '[[{target}|Copied question]]'\n"
        f"Other: '[[{target}]]'\n---\n"
        f"# Referrer\n\nFirst [[{target}]] and [[{target}]].\n\n"
        f"Second [question]({target}).\n\n"
        "```base\nobsHtml: {records: tag}\n"
        "views:\n  - type: table\n    order: [label, text, backlinks]\n```\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[owner]]\n- [[referrer]]\n", encoding="utf-8")

    artifact = render_artifact(manifest, parse_manifest(manifest))
    data = decode_artifact_data(artifact)
    owner, referrer = data["notes"][1:]
    backlinks = owner["marks"][0]["backlinks"]

    assert backlinks == [
        {"href": "#owner/@mark-owner-open-point-datum-a-continuity", "label": "Owner"},
        {"href": "#referrer?sourceLine=7", "label": "Referrer · line 7"},
        {"href": "#referrer?sourceLine=9", "label": "Referrer · line 9"},
        {"href": "#referrer?sourceField=Open", "label": "Referrer · Open"},
        {"href": "#referrer?sourceField=Other", "label": "Referrer · Other"},
    ]
    assert 'data-source-line="7"' in referrer["html"]
    assert '>#mark/open_point/datum_a_continuity</a>' in referrer["frontmatterHtml"]["Open"]
    assert "Copied question" not in referrer["frontmatterHtml"]["Open"]


def test_open_point_backlinks_distinguish_table_cells_and_nested_properties(tmp_path: Path) -> None:
    target = "owner#mark-owner-open-point-datum"
    (tmp_path / "owner.md").write_text("Question. #mark/open_point/datum\n", encoding="utf-8")
    (tmp_path / "referrer.md").write_text(
        f"---\nOpen: ['[[{target}]]', '[[{target}]]']\n"
        f"Nested:\n- Open: '[[{target}]]'\n- Open: '[[{target}]]'\n---\n"
        f"# Referrer\n\n| First | Second |\n|---|---|\n| [[{target}]] | [[{target}]] |\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[owner]]\n- [[referrer]]\n", encoding="utf-8")

    artifact = render_artifact(manifest, parse_manifest(manifest))
    data = decode_artifact_data(artifact)
    owner, referrer = data["notes"][1:]

    assert [link["href"] for link in owner["marks"][0]["backlinks"]] == [
        "#owner/@mark-owner-open-point-datum",
        "#referrer?sourceLine=11&sourceCell=1",
        "#referrer?sourceLine=11&sourceCell=2",
        "#referrer?sourceField=Open",
        "#referrer?sourceField=Nested.0.Open",
        "#referrer?sourceField=Nested.1.Open",
    ]
    assert 'data-source-cell="1"' in referrer["html"]
    assert 'data-source-cell="2"' in referrer["html"]


def test_open_point_backlinks_reveal_tight_list_locations(tmp_path: Path) -> None:
    target = "owner#mark-owner-open-point-datum"
    (tmp_path / "owner.md").write_text("Question. #mark/open_point/datum\n", encoding="utf-8")
    (tmp_path / "referrer.md").write_text(
        f"# Referrer\n\n- First [[{target}]]\n- Second [[{target}]]\n", encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[owner]]\n- [[referrer]]\n", encoding="utf-8")

    artifact = render_artifact(manifest, parse_manifest(manifest))
    data = decode_artifact_data(artifact)

    assert '<li data-source-line="3">' in data["notes"][2]["html"]
    assert '<li data-source-line="4">' in data["notes"][2]["html"]
    assert [link["href"] for link in data["notes"][1]["marks"][0]["backlinks"]] == [
        "#owner/@mark-owner-open-point-datum", "#referrer?sourceLine=3", "#referrer?sourceLine=4",
    ]


def test_open_point_self_reference_does_not_create_register_backlinks(tmp_path: Path) -> None:
    (tmp_path / "owner.md").write_text(
        "Question with [its identity](#mark-owner-open-point-datum) "
        "and [evidence](https://example.org/evidence). "
        "#mark/open_point/datum #mark/decision/answered\n\n"
        "```base\nobsHtml: {records: tag}\n"
        "views:\n  - type: table\n    order: [label, text, backlinks]\n```\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[owner]]\n", encoding="utf-8")

    artifact = render_artifact(manifest, parse_manifest(manifest))
    data = decode_artifact_data(artifact)
    owner = data["notes"][1]

    assert [(mark["kind"], mark["label"], mark["anchor"]) for mark in owner["marks"]] == [
        ("open_point", "datum", "mark-owner-open-point-datum"),
        ("decision", "answered", "mark-owner-open-point-datum"),
    ]
    assert owner["marks"][0]["backlinks"] == [{
        "href": "#owner/@mark-owner-open-point-datum", "label": "Owner",
    }]
    assert owner["html"].count('id="mark-owner-open-point-datum"') == 1
    assert 'href="https://example.org/evidence"' in owner["html"]
    assert '>#mark/open_point/datum</a>' in owner["html"]


def test_artifact_rejects_duplicate_marker_identity_across_chapters(tmp_path: Path) -> None:
    marker = "Resolve this soon. #mark/open_point/which_option\n"
    (tmp_path / "one.md").write_text(marker, encoding="utf-8")
    (tmp_path / "two.md").write_text(marker, encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n- [[two]]\n", encoding="utf-8")

    with pytest.raises(ContentError, match="Duplicate paragraph marker"):
        render_artifact(manifest, parse_manifest(manifest))


def test_document_pages_use_manifest_metadata_and_ordinary_base_definitions(tmp_path: Path) -> None:
    from datetime import datetime

    (tmp_path / "one.md").write_text("# One\n\nContent.", encoding="utf-8")
    manifest = tmp_path / "contents.md"
    manifest.write_text(
        "---\ntitle: '<img src=x onerror=bad()>'\n"
        "owners: [Ada, Lin]\nsettings: {review: true}\ngeneration: {timestamp: authored}\n"
        "---\n- [[one]]\n\nAbstract **prose** with [[one|a link]].\n"
        "```base\nfilters: 'owners != null'\n"
        "properties:\n  chapter: {displayName: Chapter}\n"
        "views:\n  - type: table\n    name: Chapters\n    order: [chapter]\n"
        "obsHtml: {records: chapter}\n```\n"
        "```base\nviews:\n  - type: table\n    order: [key, value]\n"
        "obsHtml: {records: documentMetadata}\n```\n",
        encoding="utf-8",
    )
    artifact = render_artifact(manifest, parse_manifest(manifest))
    store = re.search(r'<script id="artifact-data"[^>]*>(.*?)</script>', artifact, re.DOTALL)
    assert store
    data = decode_artifact_data(store[0])
    document = data["document"]
    assert document["metadata"]["owners"] == ["Ada", "Lin"]
    assert document["metadata"]["settings"] == {"review": True}
    assert document["metadata"]["generation"] == {"timestamp": "authored"}
    assert datetime.fromisoformat(document["generation"]["timestamp"]).tzinfo is not None
    assert set(document["generation"]) == {"timestamp", "generator", "target"}
    assert str(tmp_path) not in store[1]
    home, authored = data["notes"]
    assert home["slug"] == "home" and home["generated"] == "home"
    assert '<h1 class="document-title">&lt;img src=x onerror=bad()&gt;</h1>' in home["html"]
    assert home["tables"][-1]["definition"]["views"][0]["order"] == ["key", "value"]
    assert "<h1>Abstract</h1>" not in home["html"]
    assert 'Abstract <strong>prose</strong> with <a href="#one">a link</a>.' in home["html"]
    assert home["tables"][0]["definition"] == {
        "filters": "owners != null",
        "properties": {"chapter": {"displayName": "Chapter"}},
        "views": [{"type": "table", "name": "Chapters", "order": ["chapter"]}],
        "obsHtml": {"records": "chapter"},
    }
    assert home["html"].index("Abstract <strong>prose") < home["html"].index('data-base-table="home-base-1"')
    assert home["html"].index('data-base-table="home-base-1"') < home["html"].index('data-base-table="home-base-2"')
    assert authored["generated"] == ""
    assert '<script id="yaml-script" ' in artifact
    assert 'Copyright (C)' in artifact
    assert '<script id="base-schema" type="application/json">' in artifact


def test_compact_heading_is_one_identity_line_on_a_home_only_document(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.md"
    manifest.write_text(
        "---\ntitle: Summary\norganization: Org\nproduct: {name: Product, version: '2'}\n"
        "document type: Artifact\nauthors: Ada\nconfidentiality: Internal\n"
        "obsHtml: {heading: compact, pages: [{page: abstract}]}\n---\n"
        "```base\nviews:\n  - type: table\n    order: [key, value]\n"
        "obsHtml: {records: documentMetadata}\n```\n",
        encoding="utf-8",
    )
    data = decode_artifact_data(render_artifact(manifest, parse_manifest(manifest)))
    assert data["toc"] == ["home"]
    html = data["notes"][0]["html"]
    assert html.startswith(
        '<header class="document-heading document-heading--compact"><div class="compact-heading">'
        '<span class="cover-organization">Org</span><span class="cover-product">Product 2</span>'
        '<span class="cover-type">Artifact</span><h1 class="document-title">Summary</h1></div></header>'
    )
    assert "cover-frame" not in html and "cover-facts" not in html and "Internal" not in html
    assert 'data-base-table="home-base-1"' in html


def test_empty_abstract_has_no_implicit_tables_and_keeps_title_fallback(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("# One", encoding="utf-8")
    manifest = tmp_path / "My document.md"
    manifest.write_text("- [[one]]\n", encoding="utf-8")
    artifact = render_artifact(manifest, parse_manifest(manifest))
    data = decode_artifact_data(artifact)
    assert data["document"]["title"] == "My document"
    assert data["notes"][0]["tables"] == []
    assert all(chapter["generated"] != "abstract" for chapter in data["notes"])
    assert "<title>My document</title>" in artifact
    stylesheet = files("obs_html_interim").joinpath("base.css").read_text(encoding="utf-8")
    assert re.search(r"\.document-title\s*\{\s*text-align: center;", stylesheet)


def _artifact_data(manifest: Path) -> dict:
    artifact = render_artifact(manifest, parse_manifest(manifest))
    return decode_artifact_data(artifact)


@pytest.mark.parametrize("title, identity, visible", [
    (None, "My document", "My document"),
    ("Named document", "Named document", "Named document"),
    ("", "My document", None),
])
def test_document_title_visibility_is_separate_from_identity(
    tmp_path: Path, title: str | None, identity: str, visible: str | None,
) -> None:
    (tmp_path / "one.md").write_text("# One\n\nBody.", encoding="utf-8")
    manifest = tmp_path / "My document.md"
    metadata = {"subtitle": "Source → Target", "organization": "Example", "authors": ["Ada"]}
    if title is not None:
        metadata["title"] = title
    manifest.write_text(
        "---\n" + json.dumps(metadata) + "\n---\n- [[one]]\n\nOpening evidence.\n",
        encoding="utf-8",
    )
    artifact = render_artifact(manifest, parse_manifest(manifest))
    data = decode_artifact_data(artifact)
    home = data["notes"][0]
    assert data["document"]["title"] == home["title"] == identity
    assert home["slug"] == home["generated"] == "home"
    assert f"<title>{identity}</title>" in artifact
    if visible is None:
        assert "document-title" not in home["html"]
    else:
        assert f'<h1 class="document-title">{visible}</h1>' in home["html"]
    assert home["html"].count("Source → Target") == 1
    assert "cover-frame" in home["html"] and "Example" in home["html"] and "Ada" in home["html"]
    assert "Opening evidence." in home["html"]
    assert home["tables"] == []


def test_reference_closure_stores_each_note_once_without_adding_toc_entries(tmp_path: Path) -> None:
    (tmp_path / "chapter.md").write_text(
        "# Chapter\n\n[[Term]] [[definition|same source]] [again](definition.md)\n", encoding="utf-8",
    )
    (tmp_path / "definition.md").write_text(
        "---\naliases: [Term]\n---\n# Definition\n\n[[nested]] [[chapter]]", encoding="utf-8",
    )
    (tmp_path / "nested.md").write_text("# Nested\n\n[[definition]]", encoding="utf-8")
    (tmp_path / "unreferenced.md").write_text(
        "# Unrelated\n\n[[missing]]\n\n```cmd\nmust not run\n```\n", encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n", encoding="utf-8")
    data = _artifact_data(manifest)
    assert data["toc"] == ["home", "chapter"]
    assert {note["slug"] for note in data["notes"]} == {"home", "chapter", "definition", "nested"}
    assert len({note["slug"] for note in data["notes"]}) == len(data["notes"])
    assert "chapters" not in data
    by_slug = {note["slug"]: note for note in data["notes"]}
    assert by_slug["chapter"]["html"].count('href="#definition"') == 3
    assert 'href="#nested"' in by_slug["definition"]["html"]
    assert 'href="#definition"' in by_slug["nested"]["html"]


def test_repeated_embedded_image_payload_is_stored_once(tmp_path: Path) -> None:
    image = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a8xoAAAAASUVORK5CYII="
    )
    (tmp_path / "shared.png").write_bytes(image)
    (tmp_path / "one.md").write_text("![Shared image](shared.png)\n", encoding="utf-8")
    (tmp_path / "two.md").write_text("![Shared image](shared.png)\n", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n- [[two]]\n", encoding="utf-8")

    artifact = render_artifact(manifest, parse_manifest(manifest))
    data = decode_artifact_data(artifact)
    payload = f"data:image/png;base64,{base64.b64encode(image).decode('ascii')}"

    asset_id, = [key for key, value in data["embeddedAssets"].items() if value == payload]
    assert json.dumps(data).count(payload) == 1
    for slug in ("one", "two"):
        note = next(note for note in data["notes"] if note["slug"] == slug)
        assert f"obs-asset:{asset_id}" in note["html"]
        assert payload not in note["html"]


def test_standalone_content_images_use_shared_figure_presentation(tmp_path: Path) -> None:
    image = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a8xoAAAAASUVORK5CYII="
    )
    (tmp_path / "figure.png").write_bytes(image)
    (tmp_path / "chapter.md").write_text(
        "# Chapter\n\n![Standalone diagram](figure.png \"Image title\")\n\n"
        "[![Linked logo](figure.png)](https://example.invalid/)\n\n"
        "Inline ![Inline icon](figure.png) stays inline.\n\n"
        "[![Cover one](figure.png)](https://one.invalid/) "
        "[![Cover two](figure.png)](https://two.invalid/)\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n", encoding="utf-8")

    artifact = render_artifact(manifest, parse_manifest(manifest))
    data = decode_artifact_data(artifact)
    chapter = next(note for note in data["notes"] if note["slug"] == "chapter")

    assert chapter["html"].count('data-artifact-figure') == 1
    assert re.search(
        r'<figure class="artifact-figure" data-artifact-figure>\s*<img src="obs-asset:',
        chapter["html"],
    )
    assert 'alt="Standalone diagram"' in chapter["html"]
    assert 'title="Image title"' in chapter["html"]
    assert chapter["html"].count("<figcaption") == 0
    assert re.search(
        r'<a href="https://example\.invalid/"><img src="obs-asset:',
        chapter["html"],
    )
    assert 'Inline <img src="obs-asset:' in chapter["html"]
    assert 'alt="Inline icon" /> stays inline.' in chapter["html"]
    assert '<a href="https://one.invalid/"><img' in chapter["html"]
    assert '<a href="https://two.invalid/"><img' in chapter["html"]
    assert 'id="figure-script"' in artifact


def test_quantity_notes_are_included_by_query_with_source_links(tmp_path: Path) -> None:
    (tmp_path / "chapter.md").write_text(
        "# Chapter\n\n```base\nfilters: 'kind == \"quantity\"'\n"
        "views:\n  - type: table\n    order: [value, unit]\n```\n",
        encoding="utf-8",
    )
    (tmp_path / "flatness.md").write_text(
        "---\nkind: quantity\nvalue: 20\nunit: µm\naliases: [flatness_A]\n"
        "source: '[[drawing]]'\n---\n# Datum A flatness\n\n"
        "Empirical target; its surface assignment remains open.\n",
        encoding="utf-8",
    )
    (tmp_path / "drawing.md").write_text("# Drawing", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n", encoding="utf-8")

    data = _artifact_data(manifest)
    notes = {note["slug"]: note for note in data["notes"]}

    assert {"home", "chapter", "flatness", "drawing"} <= notes.keys()
    assert notes["flatness"]["frontmatter"]["value"] == 20
    assert notes["flatness"]["frontmatter"]["unit"] == "µm"
    assert notes["flatness"]["frontmatter"]["aliases"] == ["flatness_A"]
    assert notes["chapter"]["tables"][0]["definition"]["filters"] == 'kind == "quantity"'


def test_note_metadata_html_is_derived_for_rich_table_cells(tmp_path: Path) -> None:
    (tmp_path / "register.md").write_text(
        '# Register\n\n```base\nfilters: \'kind == "quantity"\'\n'
        "views:\n  - type: table\n    order: [citation]\n```\n",
        encoding="utf-8",
    )
    (tmp_path / "quantity.md").write_text(
        "---\nkind: quantity\nvalue: 20\nunit: µm\naliases: [flatness_A]\n"
        "source: '[[drawing]]'\n"
        "citation: 'See [[drawing]] **sheet 2** and $x$.'\n---\n# Flatness\n",
        encoding="utf-8",
    )
    (tmp_path / "drawing.md").write_text("# Drawing", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[register]]\n", encoding="utf-8")

    data = _artifact_data(manifest)
    quantity = next(note for note in data["notes"] if note["slug"] == "quantity")

    assert quantity["frontmatterHtml"]["citation"].startswith(
        'See <a href="#drawing">Drawing</a> <strong>sheet 2</strong> and '
        '<span class="math inline"><math'
    )


def test_query_matches_seed_nested_references_and_queries_until_fixed_point(tmp_path: Path) -> None:
    (tmp_path / "register.md").write_text(
        '# Register\n\n```base\nobsHtml: {records: glossary}\n'
        'views:\n  - type: table\n    order: [term, definition]\n```\n', encoding="utf-8",
    )
    (tmp_path / "term.md").write_text(
        "---\nkind: glossary\nterm: Concept\ndefinition: 'Read [[details]].'\n---\n"
        "# Concept\n\n```base\nfilters: status == \"wanted\"\n"
        "views:\n  - type: table\n    order: [title]\nobsHtml: {records: note}\n```\n", encoding="utf-8",
    )
    (tmp_path / "details.md").write_text("# Details\n\n[[term]]", encoding="utf-8")
    (tmp_path / "matched.md").write_text("---\nstatus: wanted\n---\n# Matched\n\n[[last]]", encoding="utf-8")
    (tmp_path / "last.md").write_text("# Last", encoding="utf-8")
    (tmp_path / "unmatched.md").write_text("---\nstatus: unwanted\n---\n[[missing]]", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[register]]\n", encoding="utf-8")
    data = _artifact_data(manifest)
    assert data["toc"] == ["home", "register"]
    assert {note["slug"] for note in data["notes"]} == {
        "home", "register", "term", "details", "matched", "last",
    }
    assert 'href="#details"' in next(note for note in data["notes"] if note["slug"] == "term")["definitionHtml"]


def test_tag_query_includes_unlisted_source_note_and_metadata_links_are_followed(tmp_path: Path) -> None:
    (tmp_path / "register.md").write_text(
        '# Register\n\n```base\nfilters: type == "risk"\n'
        'views:\n  - type: table\n    order: [label, text]\nobsHtml: {records: tag}\n```\n', encoding="utf-8",
    )
    (tmp_path / "risk.md").write_text(
        "A risk. #mark/risk/hidden_risk\n\n[[nested]]", encoding="utf-8",
    )
    (tmp_path / "other.md").write_text("A question. #mark/question/not_selected", encoding="utf-8")
    (tmp_path / "nested.md").write_text("# Nested", encoding="utf-8")
    (tmp_path / "owner.md").write_text("# Owner", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("---\nowner: '[[owner]]'\n---\n- [[register]]\n", encoding="utf-8")
    data = _artifact_data(manifest)
    assert {note["slug"] for note in data["notes"]} == {"home", "register", "risk", "nested", "owner"}


def test_unresolved_link_in_a_referenced_note_is_an_explicit_error(tmp_path: Path) -> None:
    (tmp_path / "chapter.md").write_text("[[linked]]", encoding="utf-8")
    (tmp_path / "linked.md").write_text("[[missing]]", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n", encoding="utf-8")
    with pytest.raises(ContentError, match="Unresolved note reference 'missing'"):
        _artifact_data(manifest)


@pytest.mark.parametrize(("metadata", "expression"), [
    ("values: null", 'values == null'),
    ("values: true", 'values == true'),
    ("values: 1.0", 'values == 1'),
    ("values: {nested: yes}", 'values.nested == true'),
])
def test_query_inclusion_uses_canonical_typed_metadata(
    tmp_path: Path, metadata: str, expression: str,
) -> None:
    (tmp_path / "register.md").write_text(
        f"# Register\n\n```base\nfilters: '{expression}'\n"
        "views:\n  - type: table\n    order: [title]\nobsHtml: {records: note}\n```\n",
        encoding="utf-8",
    )
    (tmp_path / "matched.md").write_text(f"---\n{metadata}\n---\n# Matched", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[register]]\n", encoding="utf-8")
    assert {note["slug"] for note in _artifact_data(manifest)["notes"]} == {"home", "register", "matched"}


def test_artifact_starts_with_no_open_bars(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("# One", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n", encoding="utf-8")

    artifact = render_artifact(manifest, parse_manifest(manifest))

    assert 'data-bar="toc" aria-label="Table of contents" hidden' in artifact
    assert 'data-bar="filter" aria-label="Filter" hidden' in artifact
    assert 'data-bar="search" aria-label="Search" hidden' in artifact
    assert 'class="bar-icon bar-icon--filter"' in artifact
    assert 'data-menu-button\n          aria-label="Open bars menu" aria-expanded="false"' in artifact


def test_inline_runtimes_are_embedded_from_package_scripts(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("# One", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("---\nobsHtml: {layout: paged}\n---\n- [[one]]\n", encoding="utf-8")

    artifact = render_artifact(manifest, parse_manifest(manifest))

    package = files("obs_html_interim")
    assert package.joinpath("storage.js").read_text(encoding="utf-8") in artifact
    startup = re.search(r'<script id="reader-startup-script"[^>]*>(.*?)</script>', artifact, re.DOTALL)[1]
    reading = decode_artifact_data(artifact)["reading"]
    expected = (package.joinpath("reader-startup.js").read_text(encoding="utf-8")
                .replace("READER_THEME", json.dumps(reading["theme"]))
                .replace("READER_PAGED", json.dumps(reading["paged"])))
    assert reading["paged"] is True
    assert [line.strip() for line in startup.strip().splitlines()] == expected.strip().splitlines()


def test_artifact_has_generic_bar_scripts_and_resize_handles(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("# One", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n", encoding="utf-8")

    artifact = render_artifact(manifest, parse_manifest(manifest))

    assert '<script id="bar-scripts" ' in artifact
    assert artifact.count('role="separator"') == 4
    for direction, orientation in (
        ("left", "vertical"),
        ("right", "vertical"),
        ("top", "horizontal"),
        ("bottom", "horizontal"),
    ):
        assert f'data-dock-resize="{direction}" role="separator"' in artifact
        assert f'aria-orientation="{orientation}" tabindex="0"' in artifact


def test_table_of_contents_has_branch_and_all_controls(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("# One", encoding="utf-8")
    (tmp_path / "two.md").write_text("# Two", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[one]]\n  - [[two]]\n", encoding="utf-8")

    artifact = render_artifact(manifest, parse_manifest(manifest))

    assert "data-toc-tree" in artifact
    assert 'data-toc-action="collapse" aria-label="Collapse all" title="Collapse all"' in artifact
    assert 'data-toc-action="expand" aria-label="Expand all" title="Expand all"' in artifact


def test_stylesheet_keeps_color_literals_in_semantic_tokens() -> None:
    stylesheet = files("obs_html_interim").joinpath("base.css").read_text(encoding="utf-8")
    lines_with_colors = [line for line in stylesheet.splitlines() if HEX_COLOR.search(line)]

    assert not lines_with_colors
    index = json.loads(files("obs_html_interim").joinpath("assets.json").read_text(encoding="utf-8"))
    assert index["assets"]["color"]["children"]["text"]["value"]["light"] == "#000000"


def test_appearance_overrides_use_the_shared_token_palette() -> None:
    stylesheet = files("obs_html_interim").joinpath("base.css").read_text(encoding="utf-8")

    assert "color-scheme: light dark" in stylesheet
    assert ':root[data-theme="light"]' in stylesheet
    assert ':root[data-theme="dark"]' in stylesheet
    assert "color-scheme: light;" in stylesheet
    assert "color-scheme: dark;" in stylesheet
    from obs_html_interim.semantic_assets import SemanticAssets
    declarations = re.findall(r"--color-[\w-]+:([^;]+);", SemanticAssets(Path.cwd()).css())
    assert declarations
    assert all(re.fullmatch(r"var\(--asset-[0-9a-f]+\)", value) for value in declarations)


def test_filter_value_menus_display_only_while_popover_is_open() -> None:
    stylesheet = files("obs_html_interim").joinpath("base.css").read_text(encoding="utf-8")
    open_rule = re.search(r"\.filter-values:popover-open\s*\{(?P<body>[^}]*)}", stylesheet)
    base_rule = re.search(r"\.filter-values\s*\{(?P<body>[^}]*)}", stylesheet)

    assert open_rule and "display: flex" in open_rule["body"]
    assert base_rule and "display:" not in base_rule["body"]


def test_query_help_buttons_share_the_input_height_and_are_square() -> None:
    stylesheet = files("obs_html_interim").joinpath("base.css").read_text(encoding="utf-8")

    assert "--query-control-size: 2.35rem" in stylesheet
    assert "height: var(--query-control-size)" in stylesheet
    assert "width: var(--query-control-size)" in stylesheet


def test_comment_highlights_have_distinct_hover_feedback() -> None:
    stylesheet = files("obs_html_interim").joinpath("base.css").read_text(encoding="utf-8")

    assert "::highlight(obs-comments-hover)" in stylesheet
    assert ".chapter-body.comment-highlight-hover" in stylesheet
    assert "cursor: pointer" in stylesheet


def test_review_states_use_shared_semantic_color_tokens() -> None:
    stylesheet = files("obs_html_interim").joinpath("base.css").read_text(encoding="utf-8")

    for token in ("--color-success", "--color-failure", "--color-waiting", "--color-annotation"):
        assert token in stylesheet
    assert "background: var(--color-success)" in stylesheet
    assert "background: var(--color-failure)" in stylesheet
    assert "background: var(--color-waiting)" in stylesheet


def test_next_chapter_control_leaves_scrollbar_gutter_clickable() -> None:
    stylesheet = files("obs_html_interim").joinpath("base.css").read_text(encoding="utf-8")

    assert ".chapter-nav-zone--next" in stylesheet
    assert "right: 1rem" in stylesheet


def test_semantic_paragraphs_are_understated_and_responsive() -> None:
    stylesheet = files("obs_html_interim").joinpath("base.css").read_text(encoding="utf-8")

    assert ".content-card" in stylesheet
    assert ".semantic-mark" in stylesheet
    assert "grid-template-columns: minmax(0, 4fr) minmax(0, 1fr)" in stylesheet
    assert ".semantic-mark-icon--risk" in stylesheet
    assert ".semantic-mark-icon--decision" in stylesheet
    assert "--color-bluf-" not in stylesheet
    card_rule = re.search(r"\.content-card\s*\{(?P<body>[^}]*)}", stylesheet)
    title_rule = re.search(r"\.content-card-title\s*\{(?P<body>[^}]*)}", stylesheet)
    assert card_rule and "padding: var(--card-clearance);" in card_rule["body"]
    assert "background: var(--color-accent-soft)" in card_rule["body"]
    assert "margin-inline: calc(-1 * (var(--card-clearance) + var(--border-width)))" in card_rule["body"]
    assert title_rule and "text-align: center" in title_rule["body"]
    link_rule = re.search(r"\.chapter-body \.content-card-title a\s*\{([^}]*)}", stylesheet)
    assert link_rule and "font-style: italic" not in link_rule[1]
    assert "text-decoration: none" in link_rule[1]
    rail_rule = re.search(r"\.semantic-mark-rail\s*\{([^}]*)}", stylesheet)
    assert rail_rule and "align-self: stretch" in rail_rule[1]


def test_generic_table_runtime_owns_local_tree_and_view_operations() -> None:
    script = files("obs_html_interim").joinpath("table.js").read_text(encoding="utf-8")

    assert "retainMatchesAndAncestors" in script
    assert "baseExpression" in script
    assert 'aria-label", "Filter table"' in script
    assert 'makePanel("order", "Group / Sort")' in script
    assert 'makePanel("properties", "Properties")' in script
    assert 'makePanel("filter", "Filter")' in script
    assert "availableColumns" in script
    assert "initialGroup" in script
    assert "initialSort" in script
    assert "renderProperties" in script
    assert 'columns.length === 1' in script
    assert "renderGroup(entries, depth + 1, groupPath, branchKey)" in script
    assert "items.forEach(appendBranch)" in script
    assert "Filter fields" in script
    assert "parentKey" in script
    assert 'draggable = true' in script
    assert 'className = "data-table-column-resize"' in script
    assert 'aria-label", "Table options"' in script
    assert "data-table-column-move" not in script
    assert "contentWidths" in script
    assert "fitColumns" in script
    assert "Math.min(240" not in script
    assert "ResizeObserver" in script
    assert 'column.width || 220' not in script


def test_table_resize_handles_do_not_create_horizontal_overflow() -> None:
    stylesheet = files("obs_html_interim").joinpath("base.css").read_text(encoding="utf-8")
    handle = re.search(r"\.data-table-column-resize\s*\{([^}]*)}", stylesheet)
    table = re.search(r"\.data-table-scroll table\s*\{([^}]*)}", stylesheet)
    scroller = re.search(r"\.data-table-scroll\s*\{([^}]*)}", stylesheet)

    assert handle and table and scroller
    assert re.search(r"right:\s*0\s*;", handle[1])
    assert "width: 0.6rem;" in handle[1]
    assert "width: 100%;" in table[1]
    assert "min-width:" not in table[1]
    assert "overflow-x: auto;" in scroller[1]
    # A handle anchored inside the final cell must not enlarge the scrollable area.
    for table_width in (278, 720):
        for font_size in (16, 20):
            handle_width = 0.6 * font_size
            handle_left = table_width - handle_width
            assert 0 <= handle_left < table_width
            assert handle_left + handle_width <= table_width


def test_table_reference_contract_covers_headers_groups_and_footer(tmp_path: Path) -> None:
    from test_browser import run_artifact_dom_contract

    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "chapter.md").write_text("# Chapter\n", encoding="utf-8")
    artifact = tmp_path / "artifact.html"
    artifact.write_text(render_artifact(manifest, parse_manifest(manifest)), encoding="utf-8")
    run_artifact_dom_contract(artifact, "--table-controls-only")


def test_table_popover_resets_native_insets_to_stay_next_to_its_button() -> None:
    stylesheet = files("obs_html_interim").joinpath("base.css").read_text(encoding="utf-8")
    rule = re.search(r"\.data-table-options\s*\{([^}]*)}", stylesheet)
    assert rule
    declarations = dict(re.findall(r"([\w-]+)\s*:\s*([^;]+);", rule[1]))
    assert declarations["inset"] == "auto"
    assert declarations["margin"] == "0"
    assert declarations["position"] == "fixed"
    assert not {"top", "right", "bottom", "left"}.intersection(declarations)


def test_filter_badges_follow_applied_queries_and_share_funnel_styling() -> None:
    stylesheet = files("obs_html_interim").joinpath("base.css").read_text(encoding="utf-8")
    script = files("obs_html_interim").joinpath("artifact.js").read_text(encoding="utf-8")
    table = files("obs_html_interim").joinpath("table.js").read_text(encoding="utf-8")

    assert "menuButton.dataset.filterActive" not in script
    assert 'optionsToggle.dataset.filterActive = String(!query.empty)' in table
    assert "Open bars menu; artifact filter active" not in script
    assert "Table options; filter active" in table
    apply = table.split("const apply = () => {", 1)[1].split(
        'previousPage.addEventListener', 1,
    )[0]
    assert apply.index("return;") < apply.index("dataset.filterActive")
    assert '.icon-button[data-filter-active="true"]>.filter-status-icon' in stylesheet
    assert 'clip-path: polygon(' not in stylesheet
    assert "pointer-events: none;" in stylesheet


def test_disclosures_share_bare_icon_styling_across_surfaces() -> None:
    stylesheet = files("obs_html_interim").joinpath("base.css").read_text(encoding="utf-8")
    script = files("obs_html_interim").joinpath("artifact.js").read_text(encoding="utf-8")
    table = files("obs_html_interim").joinpath("table.js").read_text(encoding="utf-8")
    from obs_html_interim.bars.toc import BAR

    for component in ("toc-toggle", "heading-toggle", "chapter-breadcrumb-toggle"):
        assert f'"disclosure-toggle {component}"' in script
    for component in ("data-table-tree-toggle", "data-table-group-toggle"):
        assert f'"disclosure-toggle {component}"' in table
    assert BAR.header_actions.count('class="disclosure-toggle toc-action"') == 2
    assert "data-toc-action" not in BAR.render([])
    rule = re.search(
        r"\.disclosure-toggle,\s*\.disclosure-toggle:hover:not\(:disabled\),"
        r"\s*\.disclosure-toggle:active\s*\{([^}]*)}", stylesheet,
    )
    assert rule
    for declaration in (
        "background: transparent;", "border: 0;", "border-radius: 0;",
        "box-shadow: none;", "padding: 0;",
    ):
        assert declaration in rule[1]
    assert ".disclosure-toggle:focus-visible" in stylesheet


def test_artifact_runtime_derives_breadcrumb_navigation_from_chapters() -> None:
    script = files("obs_html_interim").joinpath("artifact.js").read_text(encoding="utf-8")

    assert "chapterParentIndex" in script
    assert "chapterChildren" in script
    assert 'navigation.className = "chapter-breadcrumbs"' in script
    assert 'document.createElement("summary")' in script
    assert 'document.createElement("button")' not in script.split(
        "const renderBreadcrumbs", 1
    )[1].split("const activateChapter", 1)[0]
    assert "generatedViews" not in script


def test_breadcrumbs_share_top_band_with_out_of_flow_menu() -> None:
    stylesheet = files("obs_html_interim").joinpath("base.css").read_text(encoding="utf-8")
    rules = re.findall(r"(?<![\w.-])\.chapter-body\s*\{([^}]*)}", stylesheet)
    assert len(rules) == 2
    assert all(re.search(r"padding:\s*1rem\s", rule) for rule in rules)
    menu = re.search(r"\.menu-button\s*\{([^}]*)}", stylesheet)[1]
    assert "position: fixed;" in menu
    assert "top: 1rem;" in menu
    crumbs = re.search(r"\.chapter-breadcrumbs\s*\{([^}]*)}", stylesheet)[1]
    assert "min-height: 2.4rem;" in crumbs
    assert "padding-inline-end: 2.9rem;" in crumbs
    metadata = re.search(r"\.frontmatter-panel\s*\{([^}]*)}", stylesheet)[1]
    assert "margin: 1rem auto 0;" in metadata
    chevron = re.search(r"\.frontmatter-nav-zone\s*\{([^}]*)}", stylesheet)[1]
    assert "height: 1rem;" in chevron


def test_media_strip_centers_logos_and_separators_on_both_axes() -> None:
    stylesheet = files("obs_html_interim").joinpath("base.css").read_text(encoding="utf-8")
    rule = re.search(r"\.chapter-body \.media-strip\s*\{([^}]*)}", stylesheet)[1]
    assert "display: flex;" in rule
    assert "justify-content: center;" in rule
    assert "align-items: center;" in rule
def test_explicit_image_caption_has_one_owner_and_preserves_links(tmp_path):
    import yaml
    from obs_html_interim.content import parse_manifest
    from obs_html_interim.renderer import render_artifact
    (tmp_path / "manifest.md").write_text("- [[one]]\n", encoding="utf-8")
    (tmp_path / "reference.md").write_text("# Reference\n\nCanonical source.\n", encoding="utf-8")
    (tmp_path / "image.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"/>', encoding="utf-8",
    )
    spec = {"version": 1, "kind": "image", "source": "image.svg", "alt": "Alternative description",
            "caption": ["*First caption [[reference]].*", "Second **qualification**. [Source](reference.md)"]}
    (tmp_path / "one.md").write_text(
        "# One\n\n```figure\n" + yaml.safe_dump(spec) + "```\n\n*Ordinary prose stays outside.*\n",
        encoding="utf-8",
    )
    path = tmp_path / "manifest.md"
    artifact = render_artifact(path, parse_manifest(path))
    data = decode_artifact_data(artifact)
    assert any(item["slug"] == "reference" for item in data["notes"])
    html = next(item["html"] for item in data["notes"] if item["slug"] == "one")
    assert html.count("<figcaption>") == 1
    assert '<p data-figure-caption-review><em>First caption <a href="#reference">' in html
    assert 'alt="Alternative description"' in html
    assert "Second <strong>qualification</strong>." in html
    assert '<a href="#reference">Source</a>' in html
    assert "</figcaption></figure>" in html
    assert html.index("Ordinary prose stays outside") > html.index("</figure>")
