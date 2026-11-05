import json
from xml.etree import ElementTree

import pytest

from obs_html.content import ContentError, parse_manifest, render_chapter


def quantity(tmp_path, metadata):
    (tmp_path / "source.md").write_text("# Source\n", encoding="utf-8")
    (tmp_path / "quantity.md").write_text("---\n" + json.dumps({
        "kind": "quantity", "aliases": ["findingCount"], "source": "[[source]]", **metadata,
    }) + "\n---\n# Count\n", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n- [[quantity]]\n- [[source]]\n", encoding="utf-8")
    (tmp_path / "chapter.md").write_text(
        "Findings [[findingCount]]. Explicit [[findingCount|all findings]].\n", encoding="utf-8")
    return manifest


def test_query_quantity_uses_existing_implicit_reference(tmp_path):
    manifest = quantity(tmp_path, {"query": {
        "where": [{"field": "findingKey", "exists": True}], "distinct": "findingKey",
    }})
    chapters = parse_manifest(manifest)
    rendered = render_chapter(chapters[0], chapters, tmp_path)
    assert 'data-quantity-reference="quantity.md"' in rendered
    links = ElementTree.fromstring(f"<div>{rendered}</div>").findall(".//a")
    pending, explicit = links
    assert pending.text == "Calculating…"
    assert pending.attrib["aria-busy"] == "true"
    assert pending.attrib["role"] == "status"
    assert pending.attrib["href"] == "#quantity"
    assert explicit.text == "all findings"
    assert explicit.attrib == {"href": "#quantity"}
    assert rendered.count("data-quantity-reference") == 1


@pytest.mark.parametrize("metadata", [
    {}, {"value": 1, "query": {"where": []}}, {"query": {}},
    {"query": {"where": [], "formula": "count()"}},
    {"query": {"where": [{"field": "kind"}]}},
    {"query": {"where": [], "distinct": ""}},
])
def test_query_quantity_rejects_missing_dual_and_malformed_sources(tmp_path, metadata):
    manifest = quantity(tmp_path, metadata)
    with pytest.raises(ContentError, match=r"Quantity|; see capabilities/queries\."):
        chapters = parse_manifest(manifest)
        render_chapter(chapters[0], chapters, tmp_path)


@pytest.mark.parametrize("reference", ["missing", "source", "quantity", "../outside"])
def test_query_quantity_rejects_bad_upstream_owners(tmp_path, reference):
    manifest = quantity(tmp_path, {"query": {"from": reference, "where": []}})
    chapters = parse_manifest(manifest)
    with pytest.raises(ContentError, match=r"Quantity|; see capabilities/queries\."):
        render_chapter(chapters[0], chapters, tmp_path)
