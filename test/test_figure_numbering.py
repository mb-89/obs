import json

import pytest

from obs_html_interim.content import ContentError, parse_manifest
from obs_html_interim.renderer import render_artifact
from obs_html_interim.artifact_data import ARTIFACT_PATTERN, decode_artifact_data

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>'


def figure(caption=None, block=None, kind="image"):
    lines = ["```figure", "version: 1", f"kind: {kind}", "source: img.svg"]
    if caption:
        lines.append(f"caption: {caption}")
    lines.append("```")
    if block:
        lines += [f"^{block}"]
    return "\n".join(lines) + "\n\n"


def build(tmp_path, chapters, figures=None, extra=None):
    (tmp_path / "img.svg").write_text(SVG, encoding="utf-8")
    front = "---\n" + json.dumps({"obsHtml": {"figures": figures}}) + "\n---\n" if figures else ""
    manifest = tmp_path / "manifest.md"
    manifest.write_text(front + "".join(f"- [[{name}]]\n" for name in chapters), encoding="utf-8")
    for name, body in {**chapters, **(extra or {})}.items():
        (tmp_path / f"{name}.md").write_text(body, encoding="utf-8")
    data = decode_artifact_data(ARTIFACT_PATTERN.search(render_artifact(manifest, parse_manifest(manifest)))[0])
    return {note["slug"]: note["html"] for note in data["notes"]}


def test_captioned_figures_are_numbered_and_block_ids_become_anchors(tmp_path):
    notes = build(tmp_path, {
        "one": "# One\n\n" + figure("First", "fig-a") + figure() + figure("Second", "fig-b")
        + "See [[#^fig-b]], then [[two#^fig-c]] and [the third](two.md#^fig-c) and [](two.md#^fig-c).\n",
        "two": "# Two\n\n" + figure("Third", "fig-c"),
    }, figures={"numbering": "document"})
    one = notes["one"]
    assert '<figure class="artifact-figure" data-artifact-figure id="one--block-fig-a" data-figure-number="Figure 1">' in one
    assert '<figcaption><span class="figure-number">Figure 1:</span> First</figcaption>' in one
    assert '<span class="figure-number">Figure 2:</span> Second' in one
    assert "^fig-" not in one
    assert '<a href="#one/block-fig-b">Figure 2</a>' in one
    assert '<a href="#two/block-fig-c">Figure 3</a>' in one
    assert '<a href="#two/block-fig-c">the third</a>' in one
    assert one.count('<a href="#two/block-fig-c">Figure 3</a>') == 2
    assert 'id="two--block-fig-c"' in notes["two"]


def test_numbering_is_opt_in_so_existing_documents_are_unchanged(tmp_path):
    notes = build(tmp_path, {"one": "# One\n\n" + figure("A", "a") + "[[#^a|the figure]]\n"})
    assert "figure-number" not in notes["one"] and "data-figure-number" not in notes["one"]
    assert '<a href="#one/block-a">the figure</a>' in notes["one"]


def test_number_precedes_the_first_caption_paragraph_and_block_id_may_follow_a_blank_line(tmp_path):
    (tmp_path / "img.svg").write_text(SVG, encoding="utf-8")
    fence = ("```figure\nversion: 1\nkind: image\nsource: img.svg\n"
             "caption: ['*First paragraph.*', '*Second paragraph.*']\n```\n\n^a\n\nSee [[#^a]].\n")
    one = build(tmp_path, {"one": "# One\n\n" + fence}, figures={"numbering": "chapter"})["one"]
    assert ('<p data-figure-caption-review><span class="figure-number">Figure 1.1:</span> '
            '<em>First paragraph.</em></p><p data-figure-caption-review><em>Second paragraph.</em></p>') in one
    assert '<a href="#one/block-a">Figure 1.1</a>' in one
    assert "^a" not in one


def test_alt_text_is_the_rendered_caption_not_its_markdown(tmp_path):
    notes = build(tmp_path, {
        "one": "# One\n\n" + figure("A", "a")
        + figure("'*As [[#^a]], with **emphasis**.*'", "b"),
    }, figures={"numbering": "document"})
    assert 'alt="As Figure 1, with emphasis."' in notes["one"]
    assert "[[" not in notes["one"] and "**" not in notes["one"]


def test_chapter_numbering_and_label_come_from_the_manifest(tmp_path):
    notes = build(tmp_path, {
        "one": "# One\n\n" + figure("A") + figure("B"),
        "two": "# Two\n\n" + figure("C", "c") + "[[#^c]]\n",
    }, figures={"numbering": "chapter", "label": "Abb."})
    assert "Abb. 1.1:" in notes["one"] and "Abb. 1.2:" in notes["one"]
    assert '<a href="#two/block-c">Abb. 2.1</a>' in notes["two"]


def test_numbering_none_keeps_anchors_and_requires_link_labels(tmp_path):
    notes = build(tmp_path, {
        "one": "# One\n\n" + figure("A", "a") + "[[#^a|the figure]]\n",
    }, figures={"numbering": "none"})
    assert "figure-number" not in notes["one"]
    assert '<a href="#one/block-a">the figure</a>' in notes["one"]
    with pytest.raises(ContentError, match="Unlabelled reference"):
        build(tmp_path, {"one": "# One\n\n" + figure("A", "a") + "[[#^a]]\n"},
              figures={"numbering": "none"})


def test_unresolved_and_duplicate_block_ids_fail(tmp_path):
    with pytest.raises(ContentError, match="Unresolved figure block reference"):
        build(tmp_path, {"one": "# One\n\n" + figure("A", "a") + "[[#^missing|x]]\n"})
    with pytest.raises(ContentError, match="Duplicate block id"):
        build(tmp_path, {"one": "# One\n\n" + figure("A", "a") + figure("B", "a")})


def test_sankey_count_labels_come_from_the_fence(tmp_path):
    graph = {"version": 1, "branchLayout": "split",
             "nodes": [{"id": "a", "label": "A", "stage": 0},
                       {"id": "b", "label": "B", "stage": 1,
                        "records": {"where": [{"field": "kind", "equals": "x"}]}}],
             "links": [{"source": "a", "target": "b", "value": 2}]}
    (tmp_path / "flow.json").write_text(json.dumps(graph), encoding="utf-8")
    fence = "```figure\nversion: 1\nkind: sankey\nsource: flow.json\n{}```\n"
    neutral = build(tmp_path, {"one": "# One\n\n" + fence.format("")})["one"]
    assert "records" in neutral and "traces" not in neutral
    labelled = build(tmp_path, {"one": "# One\n\n" + fence.format(
        "countLabels: {unit: traces, unique: distinct}\n")})["one"]
    assert "&quot;countLabels&quot;:{&quot;unit&quot;:&quot;traces&quot;,&quot;unique&quot;:&quot;distinct&quot;}" in labelled
