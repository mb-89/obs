import re

import pytest

from obs_html.config import load_config
from obs_html.render import RenderError, render


CONFIG = load_config()


def _render(document, runner=lambda command: f"ran {command}") -> str:
    return render(document, CONFIG, runner)


def test_front_pages_follow_the_profile_order(document) -> None:
    html = _render(document)
    assert html.index('class="front-page cover"') < html.index('class="front-page contents"') \
        < html.index('class="front-page abstract"') < html.index('id="intro"')
    assert "<title>Fixture document</title>" in html
    assert '<p class="cover-product">Widget 2</p>' in html
    assert '<p class="cover-organization">Example org</p>' in html
    assert '<p class="cover-type">Specification</p>' in html
    assert "<dt>Authors</dt><dd>Ada, Lin</dd>" in html
    assert "<p>A short &lt;abstract&gt;.</p>" in html


def test_profile_print_choice_sets_the_page_geometry(document) -> None:
    assert "@page{size:215.9mm 279.4mm;margin:15mm}" in _render(document)
    del document["manifest"]["abstract"][1]
    assert "@page{size:210mm 297mm;margin:20mm}" in _render(document)


def test_contents_nest_the_chapter_tree(document) -> None:
    assert ('<ol><li><a href="#intro">Intro</a><ol><li><a href="#guide-usage">Usage</a></li></ol></li>'
            '<li><a href="#appendix">Appendix</a></li></ol>') in _render(document)


def test_chapters_nest_and_headings_carry_anchors(document) -> None:
    html = _render(document)
    assert '<section class="chapter" id="intro">' in html
    assert '<h3 id="guide-usage--details">Details</h3>' in html
    assert "<h1>Appendix</h1>" in html  # A chapter without a heading gets its title.


def test_structural_nodes_render_escaped(document) -> None:
    html = _render(document)
    assert "<code>x &lt; y</code>" in html
    assert "<ol>\n<li><p>one</p>\n</li>\n<li><p>two</p>\n</li>\n</ol>" in html
    assert '<a href="https://example.org/?a=1&amp;b=2">the site</a>' in html
    assert '<img src="images/logo.png" alt="a logo">' in html


def test_wikilinks_resolve_to_chapters_and_headings(document) -> None:
    html = _render(document)
    assert '<a class="internal-link" href="#guide-usage--details">the details</a>' in html
    assert '<span class="unresolved" title="missing">gone</span>' in html


def test_chapter_frontmatter_renders_as_properties_but_the_cover_owns_the_manifest(document) -> None:
    html = _render(document)
    assert '<dl class="properties"><dt>owner</dt><dd>Ada</dd><dt>tags</dt><dd>a, b</dd></dl>' in html
    assert "obsHtml" not in html


def test_marks_render_their_category_and_identity(document) -> None:
    assert ('<span class="mark" data-mark-category="risk" data-mark-id="limit">#mark/risk/limit</span>'
            in _render(document))


def test_base_views_filter_and_sort_document_records(document) -> None:
    table = re.search(r'<table class="base">.*?</table>', _render(document)).group(0)
    assert "<caption>Items</caption>" in table
    assert "<th>file.name</th><th>Name</th><th>rank</th>" in table
    assert re.findall(r"<tr><td>(\w+)</td>", table) == ["beta", "alpha"]


def test_unsupported_base_filters_fail(document) -> None:
    base = next(node for node in document["chapters"][0]["content"] if node["type"] == "bases")
    base["attrs"]["spec"]["filters"] = "kind.contains('x')"
    with pytest.raises(RenderError, match="Unsupported Base filter"):
        _render(document)


def test_command_fences_render_escaped_output_and_skip_silent_producers(document) -> None:
    commands = []
    html = _render(document, lambda command: commands.append(command) or "<b>derived</b>\n")
    assert commands == ["echo derived"]
    assert '<pre class="command-output">&lt;b&gt;derived&lt;/b&gt;\n</pre>' in html


def test_command_fences_require_authorization(document) -> None:
    with pytest.raises(RenderError, match="authorization"):
        render(document, CONFIG)


def test_unsupported_capabilities_are_refused(document) -> None:
    document["capabilities"].append("figures")
    with pytest.raises(RenderError, match="does not render: figures"):
        _render(document)
    document["capabilities"].remove("figures")
    document["chapters"][1]["content"].append({"type": "figures", "attrs": {}, "children": []})
    with pytest.raises(RenderError, match="does not render: figures"):
        _render(document)


def test_a_minimal_document_renders(document) -> None:
    minimal = {"schemaVersion": 1, "manifest": {"title": "Only", "metadata": {}}, "chapters": [],
               "links": [], "assets": [], "records": [], "semanticResources": [], "diagnostics": [],
               "capabilities": []}
    html = render(minimal, CONFIG)
    assert '<h1 class="document-title">Only</h1>' in html
    assert 'data-report-status="ready"' in html
