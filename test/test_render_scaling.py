"""Regression guard: per-note Markdown work must not scale with frontmatter fields."""
from markdown_it import MarkdownIt

import obs_html.content as content
from obs_html.content import parse_manifest
from obs_html.renderer import render_report
from obs_html.report_data import decode_report_data


NOTES = 12
FIELDS = 20


def _write_vault(tmp_path):
    (tmp_path / "items").mkdir()
    for index in range(NOTES):
        fields = "".join(f"plain{field}: 'Plain value {field} [mm] | {index}'\n" for field in range(FIELDS))
        following = f"items/item-{(index + 1) % NOTES}"
        (tmp_path / "items" / f"item-{index}.md").write_text(
            f"---\n{fields}next: '[[{following}]]'\nsource: '[Spec](item-{index}.md)'\n---\n"
            f"# Item {index}\n\nSee [[{following}]].\n",
            encoding="utf-8",
        )
    (tmp_path / "home.md").write_text(
        "# Home\n\n" + "".join(f"- [[items/item-{index}]]\n" for index in range(NOTES)),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[home]]\n", encoding="utf-8")
    return manifest


def test_markdown_work_is_per_note_not_per_frontmatter_field(tmp_path, monkeypatch):
    manifest = _write_vault(tmp_path)
    counts = {"parsers": 0, "parse": 0, "parseInline": 0}
    authoring_markdown = content.authoring_markdown
    parse, parse_inline = MarkdownIt.parse, MarkdownIt.parseInline

    def counted_authoring_markdown():
        counts["parsers"] += 1
        return authoring_markdown()

    def counted_parse(self, *args, **kwargs):
        counts["parse"] += 1
        return parse(self, *args, **kwargs)

    def counted_parse_inline(self, *args, **kwargs):
        counts["parseInline"] += 1
        return parse_inline(self, *args, **kwargs)

    monkeypatch.setattr(content, "authoring_markdown", counted_authoring_markdown)
    monkeypatch.setattr(MarkdownIt, "parse", counted_parse)
    monkeypatch.setattr(MarkdownIt, "parseInline", counted_parse_inline)

    data = decode_report_data(render_report(manifest, parse_manifest(manifest)))

    notes = {note["slug"]: note for note in data["notes"]}
    assert len(notes) == NOTES + 2
    first = notes["items-item-0"]["frontmatterHtml"]
    assert first["plain0"] == "Plain value 0 [mm] | 0"
    assert 'href="#items-item-1"' in first["next"]
    assert 'href="#items-item-0"' in first["source"]
    # Before the shared parsers each frontmatter string built its own parser and was parsed
    # up to three times. Now every distinct plain string renders once and link-free strings are
    # not parsed for link discovery.
    budget = 4 * len(notes) + 20
    assert counts["parsers"] <= budget, counts
    assert counts["parse"] + counts["parseInline"] <= NOTES * FIELDS + 6 * len(notes) + 20, counts


def test_schema_validators_are_built_once_not_per_fence_quantity_or_figure(tmp_path, monkeypatch):
    import json
    from collections import Counter

    import obs_html.cards as cards
    import obs_html.figures as figures

    graph = {"version": 1, "nodes": [{"id": "a", "label": "A", "stage": 0},
                                     {"id": "b", "label": "B", "stage": 1}],
             "links": [{"source": "a", "target": "b", "value": 1}]}
    (tmp_path / "flow.json").write_text(json.dumps(graph), encoding="utf-8")
    (tmp_path / "items").mkdir()
    for index in range(NOTES):
        (tmp_path / "items" / f"q{index}.md").write_text(
            "---\n" + json.dumps({
                "kind": "quantity", "aliases": [f"q{index}"], "source": f"[[items/item-{index}]]",
                "query": {"where": [{"field": "kind", "equals": "item"}]},
            }) + f"\n---\n# Quantity {index}\n",
            encoding="utf-8",
        )
        (tmp_path / "items" / f"item-{index}.md").write_text(
            f"---\nkind: item\n---\n# Item {index}\n\nCount [[q{index}]].\n\n"
            "```base\nfilters: 'kind == \"quantity\"'\nviews:\n  - type: table\n    order: [unit]\n```\n\n"
            "```figure\nversion: 1\nkind: sankey\nsource: ../flow.json\ncaption: Flow\n```\n",
            encoding="utf-8",
        )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("".join(f"- [[items/item-{index}]]\n" for index in range(NOTES)), encoding="utf-8")
    built = []
    for module in (content, cards, figures):
        real = module.Draft202012Validator

        def counted(*args, _real=real, _module=module.__name__, **kwargs):
            built.append(_module)
            return _real(*args, **kwargs)

        monkeypatch.setattr(module, "Draft202012Validator", counted)

    data = decode_report_data(render_report(manifest, parse_manifest(manifest)))

    notes = {note["slug"]: note for note in data["notes"]}
    assert all(len(notes[f"items-item-{index}"]["tables"]) == 1 for index in range(NOTES))
    assert all("figure-sankey" in notes[f"items-item-{index}"]["html"] for index in range(NOTES))
    assert all(f"items-q{index}" in notes for index in range(NOTES))
    # One base, one count-query, one figure and one Sankey graph validator per process.
    assert len(built) <= 4, Counter(built)


def test_link_prefilter_keeps_reference_and_comment_split_links(tmp_path):
    for name in ("reference", "comment", "plain"):
        (tmp_path / f"{name}.md").write_text(f"# {name.title()}\n", encoding="utf-8")
    (tmp_path / "start.md").write_text(
        "---\n"
        "byReference: \"[Reference][r]\\n\\n[r]: reference.md\"\n"
        "byComment: '[Comment]<!-- hidden -->(comment.md)'\n"
        "unlinked: '[Plain] (plain.md) [x] |a|b|'\n"
        "---\n# Start\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[start]]\n", encoding="utf-8")

    data = decode_report_data(render_report(manifest, parse_manifest(manifest)))

    slugs = {note["slug"] for note in data["notes"]}
    assert {"reference", "comment"} <= slugs
    assert "plain" not in slugs
    start = next(note for note in data["notes"] if note["slug"] == "start")
    assert 'href="#comment"' in start["frontmatterHtml"]["byComment"]
    assert start["frontmatterHtml"]["unlinked"] == "[Plain] (plain.md) [x] |a|b|"
