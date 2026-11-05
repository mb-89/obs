import json

import pytest

from obs_html.content import ContentError, parse_manifest
from obs_html.renderer import render_report
from obs_html.report_data import REPORT_PATTERN, decode_report_data

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>'
FIGURES = "".join(
    f"```figure\nversion: 1\nkind: image\nsource: img.svg\ncaption: {name}.\n```\n^{name}\n\n"
    for name in "abcdef"
)


def build(tmp_path, prose, figures=None, config=None):
    (tmp_path / "img.svg").write_text(SVG, encoding="utf-8")
    profile = {"numbering": "chapter", **(figures or {})}
    manifest = tmp_path / "manifest.md"
    manifest.write_text("---\n" + json.dumps({"obsHtml": {"figures": profile}}) + "\n---\n"
                        "- [[one]]\n- [[two]]\n", encoding="utf-8")
    (tmp_path / "one.md").write_text("# One\n", encoding="utf-8")
    (tmp_path / "two.md").write_text("# Two\n\n" + FIGURES + prose + "\n", encoding="utf-8")
    html = render_report(manifest, parse_manifest(manifest), figure_references=config)
    notes = decode_report_data(REPORT_PATTERN.search(html)[0])["notes"]
    return next(note["html"] for note in notes if note["slug"] == "two")


def link(name, number):
    return f'<a href="#two/block-{name}">{number}</a>'


def test_two_adjacent_references_read_as_one_plural(tmp_path):
    html = build(tmp_path, "See [[#^d]] and [[#^e]].")
    assert f"See Figures {link('d', '2.4')} and {link('e', '2.5')}." in html


def test_three_consecutive_references_render_as_a_range(tmp_path):
    html = build(tmp_path, "See [[#^d]], [[#^e]] and [[#^f]].")
    assert f"See Figures {link('d', '2.4')}–{link('f', '2.6')}." in html
    html = build(tmp_path, "See [[#^a]], [[#^b]], [[#^c]], and [[#^e]].")
    assert f"See Figures {link('a', '2.1')}–{link('c', '2.3')}, and {link('e', '2.5')}." in html


def test_author_order_and_non_consecutive_numbers_are_kept(tmp_path):
    html = build(tmp_path, "See [[#^c]], [[#^b]] and [[#^a]] or [[#^e]] [[#^f]].")
    assert (f"See Figures {link('c', '2.3')}, {link('b', '2.2')} and {link('a', '2.1')} "
            f"or {link('e', '2.5')} {link('f', '2.6')}.") in html


def test_labelled_references_and_other_words_end_the_group(tmp_path):
    html = build(tmp_path, "See [[#^a]] and [[#^b|the second]], [[#^c]] but [[#^d]].")
    assert (f"See {link('a', 'Figure 2.1')} and {link('b', 'the second')}, "
            f"{link('c', 'Figure 2.3')} but {link('d', 'Figure 2.4')}.") in html


def test_markdown_links_manifest_plural_and_packaged_conjunctions(tmp_path):
    html = build(tmp_path, "Siehe [](two.md#^a) und\n[](two.md#^b).",
                 figures={"label": "Abb.", "labelPlural": "Abb."})
    assert f"Siehe Abb. {link('a', '2.1')} und\n{link('b', '2.2')}." in html


def test_conjunctions_come_from_configuration(tmp_path):
    config = {"labels": ["Figure"], "conjunctions": ["plus"]}
    html = build(tmp_path, "[[#^a]] plus [[#^b]]; [[#^c]] and [[#^d]]", config=config)
    assert f"Figures {link('a', '2.1')} plus {link('b', '2.2')}" in html
    assert f"{link('c', 'Figure 2.3')} and {link('d', 'Figure 2.4')}" in html


def test_merged_references_in_a_caption_keep_plain_alt_text(tmp_path):
    (tmp_path / "img.svg").write_text(SVG, encoding="utf-8")
    html = build(tmp_path, "```figure\nversion: 1\nkind: image\nsource: img.svg\n"
                           "caption: 'Like [[#^a]] and [[#^b]].'\n```\n^g")
    assert 'alt="Like Figures 2.1 and 2.2."' in html


def test_unlabelled_references_still_require_numbered_figures(tmp_path):
    with pytest.raises(ContentError, match="Unlabelled reference"):
        build(tmp_path, "[[#^a]] and [[#^b]]", figures={"numbering": "none"})
