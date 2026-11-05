import json

import pytest

from obs_html_interim.content import ContentError, parse_manifest
from obs_html_interim.renderer import render_artifact
from obs_html_interim.artifact_data import decode_artifact_data


def test_property_editor_is_explicit_and_canonical(tmp_path):
    (tmp_path / "manifest.md").write_text("- [[one]]\n", encoding="utf-8")
    (tmp_path / "one.md").write_text(
        '---\nexplanation: "Original"\nidentifier: "R-1"\n---\n# One\n\n'
        "```property-editor\nversion: 1\nfield: explanation\nlabel: Review explanation\n```\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    html = render_artifact(manifest, parse_manifest(manifest))
    data = decode_artifact_data(html)
    note = next(note for note in data["notes"] if note["slug"] == "one")
    assert note["editableProperties"] == {"explanation": {"label": "Review explanation", "maxLength": 4096}}
    assert "data-property-editor" in note["html"]
    assert note["frontmatter"] == {"explanation": "Original", "identifier": "R-1"}
    assert "property-editor-script" in html


def test_property_editor_projection_is_preserved_as_static_data(tmp_path):
    (tmp_path / "manifest.md").write_text("- [[one]]\n", encoding="utf-8")
    (tmp_path / "one.md").write_text(
        '---\nexplanation: Original\nstatus: explained\naccepted: "yes"\nsink: finding\n---\n'
        "# One\n\n"
        "```property-editor\nversion: 1\nfield: explanation\nlabel: Review\n"
        "projection:\n"
        '  blank: {status: finding, accepted: "no", sink: path}\n'
        '  nonblank: {status: explained, accepted: "yes", sink: finding}\n'
        "```\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    html = render_artifact(manifest, parse_manifest(manifest))
    data = decode_artifact_data(html)
    note = next(note for note in data["notes"] if note["slug"] == "one")
    assert note["editableProperties"]["explanation"]["projection"] == {
        "blank": {"status": "finding", "accepted": "no", "sink": "path"},
        "nonblank": {"status": "explained", "accepted": "yes", "sink": "finding"},
    }


@pytest.mark.parametrize("field", [
    "title", "kind", "aliases", "term", "definition",
    "__proto__", "constructor", "prototype", "Title", "KiNd",
])
@pytest.mark.parametrize("branch", ["blank", "nonblank"])
def test_property_editor_projection_rejects_protected_fields(tmp_path, field, branch):
    value = ["Original"] if field == "aliases" else "Original"
    replacement = ["Changed"] if field == "aliases" else "Changed"
    (tmp_path / "manifest.md").write_text("- [[one]]\n", encoding="utf-8")
    (tmp_path / "one.md").write_text(
        "---\n" + json.dumps({"explanation": "Original", "status": "Initial", field: value}) + "\n---\n"
        "# One\n\n```property-editor\n" + json.dumps({
            "version": 1, "field": "explanation", "label": "Review",
            "projection": {
                "blank": {field: replacement} if branch == "blank" else {"status": "Initial"},
                "nonblank": {field: replacement} if branch == "nonblank" else {"status": "Initial"},
            },
        }) + "\n```\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    with pytest.raises(ContentError, match=r"Property editor|; see capabilities/property-editors\."):
        render_artifact(manifest, parse_manifest(manifest))


def test_property_editor_projection_preserves_supported_arrays(tmp_path):
    (tmp_path / "manifest.md").write_text("- [[one]]\n", encoding="utf-8")
    (tmp_path / "one.md").write_text(
        "---\nexplanation: Original\noutputs: [System]\n---\n# One\n\n"
        "```property-editor\nversion: 1\nfield: explanation\nlabel: Review\n"
        "projection:\n  blank: {outputs: []}\n  nonblank: {outputs: [System, Labels]}\n```\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    artifact = render_artifact(manifest, parse_manifest(manifest))
    data = decode_artifact_data(artifact)
    note = next(note for note in data["notes"] if note["slug"] == "one")
    assert note["editableProperties"]["explanation"]["projection"] == {
        "blank": {"outputs": []}, "nonblank": {"outputs": ["System", "Labels"]},
    }


@pytest.mark.parametrize("field,value", [("missing", "text"), ("explanation", 42), ("title", "semantic")])
def test_property_editor_rejects_missing_nontext_or_semantic_fields(tmp_path, field, value):
    (tmp_path / "manifest.md").write_text("- [[one]]\n", encoding="utf-8")
    (tmp_path / "one.md").write_text(
        "---\n" + json.dumps({"explanation": value, "title": value}) + "\n---\n"
        f"```property-editor\nversion: 1\nfield: {field}\nlabel: Review\n```\n", encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    with pytest.raises(ContentError, match=r"Property editor|; see capabilities/property-editors\."):
        render_artifact(manifest, parse_manifest(manifest))


@pytest.mark.parametrize("projection", [
    {"blank": {"missing": "value"}, "nonblank": {"status": "ok"}},
    {"blank": {"explanation": "replaced"}, "nonblank": {"status": "ok"}},
    {"blank": {"status": {"nested": "value"}}, "nonblank": {"status": "ok"}},
    {"blank": {"status": ["mixed", 2]}, "nonblank": {"status": "ok"}},
    {"blank": {"status": 5}, "nonblank": {"status": "ok"}},
])
def test_property_editor_rejects_unsafe_or_type_mismatched_projection(tmp_path, projection):
    (tmp_path / "manifest.md").write_text("- [[one]]\n", encoding="utf-8")
    (tmp_path / "one.md").write_text(
        "---\n" + json.dumps({
            "explanation": "Original",
            "status": "explained",
            "accepted": "yes",
        }) + "\n---\n"
        "# One\n\n"
        "```property-editor\n" + json.dumps({
            "version": 1, "field": "explanation", "label": "Review",
            "projection": projection,
        }) + "\n```\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    with pytest.raises(ContentError, match=r"Property editor|; see capabilities/property-editors\."):
        render_artifact(manifest, parse_manifest(manifest))
