import json
import os

from obs_html.content import parse_manifest
from obs_html.renderer import render_artifact

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>'


def figure(caption=None, block=None):
    lines = ["```figure", "version: 1", "kind: image", "source: img.svg"]
    if caption:
        lines.append(f"caption: {caption}")
    lines.append("```")
    if block:
        lines.append(f"^{block}")
    return "\n".join(lines) + "\n\n"


def lint(tmp_path, chapters, figures=None, config=None):
    (tmp_path / "img.svg").write_text(SVG, encoding="utf-8")
    front = "---\n" + json.dumps({"obsHtml": {"figures": figures}}) + "\n---\n" if figures else ""
    manifest = tmp_path / "manifest.md"
    manifest.write_text(front + "".join(f"- [[{name}]]\n" for name in chapters), encoding="utf-8")
    for name, body in chapters.items():
        (tmp_path / f"{name}.md").write_text(body, encoding="utf-8")
    warnings = []
    render_artifact(manifest, parse_manifest(manifest), warning_handler=warnings.append,
                  figure_references=config)
    return [warning.replace(f"{tmp_path}{os.sep}", "") for warning in warnings]


def test_a_clean_figure_with_caption_block_id_and_block_link_has_no_warnings(tmp_path):
    assert lint(tmp_path, {
        "one": "# One\n\n" + figure("The plot.", "plot") + "As [[#^plot]] shows.\n",
    }, figures={"numbering": "document"}) == []


def test_figure_fence_without_caption_warns(tmp_path):
    assert lint(tmp_path, {"one": "# One\n\n" + figure(block="a")}) == [
        "one.md:3: figure without caption. Add a caption to the figure fence.",
    ]
    assert lint(tmp_path, {"one": "# One\n\n" + figure("A.", "a")}) == []


def test_image_alone_in_its_paragraph_warns_with_the_figure_fence_to_use(tmp_path):
    assert lint(tmp_path, {"one": "# One\n\n![Plot](img.svg)\n"}) == [
        "one.md:3: image without caption. Use a figure fence with kind: image, "
        "source: img.svg and a caption.",
    ]
    assert lint(tmp_path, {"one": "# One\n\nThe icon ![](img.svg) marks it.\n"}) == []


def test_caption_paragraph_outside_a_figure_warns(tmp_path):
    italic_after = "# One\n\n" + figure("A.", "a") + "*The plot of A.*\n"
    assert lint(tmp_path, {"one": italic_after}) == [
        "one.md:11: caption outside the figure. Move the text into the figure's caption "
        "and delete the paragraph.",
    ]
    numbered_before = "# One\n\nAbb. 2: The plot of A.\n\n" + figure("A.", "a")
    assert lint(tmp_path, {"one": numbered_before}) == [
        "one.md:3: caption outside the figure. Move the text into the figure's caption "
        "and delete the paragraph.",
    ]
    image_after = "# One\n\n![Plot](img.svg)\n\n*The plot.*\n"
    assert "one.md:5: caption outside the figure" in " ".join(lint(tmp_path, {"one": image_after}))
    assert lint(tmp_path, {"one": "# One\n\n" + figure("A.", "a") + "The plot rises.\n\n"
                           "*Emphasis away from any figure.*\n"}) == []


def test_prose_naming_a_figure_by_number_suggests_its_block_link(tmp_path):
    notes = {
        "one": "# One\n\n" + figure("A.", "a") + figure("B.", "b") + "As Figure 2 shows.\n",
        "two": "# Two\n\nSee fig. 1 and `Figure 1` and [[one#^a]].\n",
    }
    assert lint(tmp_path, notes, figures={"numbering": "document"}) == [
        "one.md:19: typed figure number 'Figure 2'. Link the figure instead: [[#^b]].",
        "two.md:3: typed figure number 'fig. 1'. Link the figure instead: [[one#^a]].",
    ]
    assert lint(tmp_path, {
        "one": "# One\n\n" + figure("A.", "a") + "As Abb. 1 shows.\n",
    }) == ["one.md:11: typed figure number 'Abb. 1'. Link the figure instead: [[#^a]]."]
    assert lint(tmp_path, {
        "one": "# One\n\n" + figure("A.", "a") + "Bild 1 rises.\n",
    }, config={"labels": ["Figure"], "conjunctions": ["and"]}) == []
    assert lint(tmp_path, {
        "one": "# One\n\n" + figure("A.", "a") + "The figure rises after 2 seconds.\n",
    }) == []


def test_typed_number_in_a_caption_and_without_a_candidate_still_warns(tmp_path):
    warnings = lint(tmp_path, {
        "one": "# One\n\n" + figure("'Like Figure 7.'", "a"),
    })
    assert warnings == [
        "one.md:3: typed figure number 'Figure 7'. Link the figure instead with an "
        "Obsidian block link such as [[#^name]] or [[note#^name]].",
    ]


def test_figure_without_block_id_warns(tmp_path):
    assert lint(tmp_path, {"one": "# One\n\n" + figure("A.")}) == [
        "one.md:3: figure without block id. Add a line ^name after the fence so "
        "references can link it.",
    ]
    assert lint(tmp_path, {"one": "# One\n\n" + figure("A.") + "Prose.\n\nAbb. 1 rises.\n"})[1] == (
        "one.md:12: typed figure number 'Abb. 1'. Link the figure instead: add a block id "
        "after the figure at line 3 and link it with [[#^name]]."
    )
