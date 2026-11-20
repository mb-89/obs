"""The label of an unaliased link to a heading or block, as Obsidian shows it: the target note's
title, " > " and the heading; within its own note the heading alone (capabilities/wikilinks).

Reader: whoever changes how the core labels a wikilink.
"""
from pathlib import Path

from obs.document import build_document

from test_vault import capability_reference

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
       '<text x="1" y="5">[[command-fences#Authorization]]</text></svg>')
FIGURE = f"```figure\nversion: 1\nkind: svg\ncaption: A drawing.\ncontent: '{SVG}'\n```\n^drawing\n\n"


def labels(nodes: list[dict]) -> list[tuple[str, str, str | None]]:
    found = []
    for node in nodes:
        if node["type"] == "wikilinks":
            found.append((node["attrs"]["label"], node["attrs"]["heading"], node["attrs"]["chapter"]))
        found.extend(labels(node.get("children", [])))
    return found


def build(tmp_path: Path) -> dict:
    (tmp_path / "manifest.md").write_text("- [[one]]\n- [[command-fences]]\n", encoding="utf-8")
    (tmp_path / "one.md").write_text(
        "---\nsee: '[[command-fences#Authorization]]'\n---\n# One\n\n## Authorization\n\n" + FIGURE
        + "See [[command-fences#Authorization]], [[#Authorization]], [[#^drawing]], [[command-fences]], "
        "[[command-fences#Authorization|the flag]] and [[missing#Part]].\n", encoding="utf-8")
    (tmp_path / "command-fences.md").write_text("# Commands\n\n## Authorization\n", encoding="utf-8")
    return build_document(tmp_path / "manifest.md", capability_reference())


def test_an_unaliased_heading_link_shows_the_note_title_and_the_heading(tmp_path) -> None:
    document = build(tmp_path)
    content = labels(document["chapters"][0]["content"])
    field = labels(next(record for record in document["records"] if record.get("path") == "one.md")["fieldNodes"])

    assert content == [
        ("Command Fences > Authorization", "Authorization", "command-fences"),  # The frontmatter field.
        ("Command Fences > Authorization", "Authorization", "command-fences"),  # The figure's SVG link.
        ("Command Fences > Authorization", "Authorization", "command-fences"),
        ("Authorization", "Authorization", "one"),
        ("^drawing", "^drawing", "one"),
        ("command-fences", "", "command-fences"),
        ("the flag", "Authorization", "command-fences"),
        ("missing > Part", "Part", None),
    ]
    assert field == [("Command Fences > Authorization", "Authorization", "command-fences")]


def test_a_callout_title_and_a_card_title_and_metric_label_link_by_the_same_rule(tmp_path) -> None:
    """Callout titles and card and metric labels are inline nodes (capabilities/callouts,
    capabilities/cards-metrics), so their links carry the one link label."""
    (tmp_path / "manifest.md").write_text("- [[one]]\n- [[command-fences]]\n", encoding="utf-8")
    (tmp_path / "command-fences.md").write_text("# Commands\n\n## Authorization\n", encoding="utf-8")
    cards = ('{"version": 1, "cards": [{"title": "See [[command-fences#Authorization]]", "body": "Body.", '
             '"metrics": [{"label": "*Open* [[command-fences#Authorization]]", "where": []}]}]}')
    (tmp_path / "one.md").write_text(
        "# One\n\n> [!note] See [[command-fences#Authorization]]\n> Body.\n\n> [!tip]\n> Untitled.\n\n"
        f"```cards\n{cards}\n```\n", encoding="utf-8")

    document = build_document(tmp_path / "manifest.md", capability_reference())

    callout, untitled, cards_node = (node for node in document["chapters"][0]["content"]
                                     if node["type"] in {"callouts", "cards-metrics"})
    link = ("Command Fences > Authorization", "Authorization", "command-fences")
    assert callout["attrs"]["title"][0] == {"type": "text", "attrs": {}, "children": [], "text": "See "}
    assert labels(callout["attrs"]["title"]) == [link]
    assert untitled["attrs"]["title"] == [{"type": "text", "attrs": {}, "children": [], "text": "Tip"}]
    [card] = cards_node["children"]
    assert labels(card["attrs"]["title"]) == [link]
    [label] = card["attrs"]["labels"]
    assert label[0]["type"] == "emphasis" and labels(label) == [link]
