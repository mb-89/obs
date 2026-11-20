"""The pure lookup and cycle search of block and section embeds (capabilities/embeds#Block and
section embeds); test_vault.py covers them through a build.

Reader: whoever changes what a block or section embed shows, or how embeds that show each other are found.
"""
from obs import embeds


def text(value: str) -> dict:
    return {"type": "text", "attrs": {}, "children": [], "text": value}


def heading(level: int, value: str) -> dict:
    return {"type": "section", "attrs": {"level": level}, "children": [text(value)]}


def paragraph(value: str) -> dict:
    return {"type": "paragraph", "attrs": {}, "children": [text(value)]}


def embed(target: str, fragment: str) -> dict:
    return {"type": "embeds", "attrs": {"target": target, "chapter": target, "heading": fragment}, "children": []}


def test_a_section_runs_to_the_next_heading_of_its_level_or_higher() -> None:
    nodes = [heading(1, "Title"), heading(2, "Pitch ^pitch"), paragraph("a"), heading(3, "Detail"),
             paragraph("b"), heading(2, "Later"), paragraph("c")]

    assert embeds.shown(nodes, "Pitch", {}) == nodes[1:5]
    assert embeds.shown(nodes, "pitch", {}) == nodes[1:5]  # Read as a link to the heading reads it.
    assert embeds.shown(nodes, "^pitch", {"pitch": nodes[1]}) == nodes[1:5]
    assert embeds.shown(nodes, "Detail", {}) == nodes[3:5]
    assert embeds.shown(nodes, "Missing", {}) is None


def test_a_block_id_shows_the_one_block_it_names() -> None:
    nodes = [paragraph("a"), paragraph("b")]

    assert embeds.shown(nodes, "^b", {"b": nodes[1]}) == [nodes[1]]
    assert embeds.shown(nodes, "^c", {"b": nodes[1]}) is None


def test_a_missing_target_lists_at_most_ten_candidates() -> None:
    nodes = [heading(2, f"H{index}") for index in range(12)]

    problem, remedy = embeds.missing("Nope", "note.md", nodes, {})
    assert problem == "names the heading Nope, which note.md lacks"
    assert "H9" in remedy and "H10" not in remedy and "2 more" in remedy
    assert remedy.endswith(f"see {embeds.OWNER}")
    assert "has no block id" in embeds.missing("^x", "note.md", nodes, {})[1]


def test_the_cycle_is_named_in_the_order_its_embeds_show_each_other() -> None:
    a, b, c = embed("b", "Part B"), embed("a", "Part A"), embed("a", "Part A")
    part_a, part_b = [heading(2, "Part A"), a], [heading(2, "Part B"), b]
    shown = [embeds.Shown(a["attrs"], "a.md", "![[b#Part B]]", part_b),
             embeds.Shown(b["attrs"], "b.md", "![[a#Part A]]", part_a),
             embeds.Shown(c["attrs"], "c.md", "![[a#Part A]]", part_a)]

    found = embeds.cycle(shown)
    assert [item.note for item in found] == ["a.md", "b.md"]
    assert embeds.cycle_problem(found)[0] == "shows b.md: ![[a#Part A]], which shows a.md: ![[b#Part B]] again"
    assert embeds.cycle(shown[2:]) is None  # c shows a, which shows nothing of its own here.
