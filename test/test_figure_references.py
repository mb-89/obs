"""Block-id links to figures: the core resolves `[[#^name]]` and `[[note#^name]]` to the figure
that carries the block id (input-model, Figure captions and references; capabilities/wikilinks).

Reader: whoever changes how the core resolves links or figure block ids.
"""
from pathlib import Path

import pytest

from obs.document import DocumentError, build_document

from test_vault import capability_reference


SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>'


def figure(name: str, caption: str = "A figure.") -> str:
    return f"```figure\nversion: 1\nkind: image\nsource: img.svg\ncaption: {caption}\n```\n^{name}\n\n"


def build(tmp_path: Path, one: str, two: str = "# Two\n") -> dict:
    (tmp_path / "img.svg").write_text(SVG, encoding="utf-8")
    (tmp_path / "manifest.md").write_text("- [[one]]\n- [[two]]\n", encoding="utf-8")
    (tmp_path / "one.md").write_text(one, encoding="utf-8")
    (tmp_path / "two.md").write_text(two, encoding="utf-8")
    return build_document(tmp_path / "manifest.md", capability_reference())


def links(nodes: list[dict]) -> list[dict]:
    found = []
    for node in nodes:
        if node["type"] == "wikilinks":
            found.append(node["attrs"])
        found.extend(links(node.get("children", [])))
    return found


def test_a_block_link_targets_the_figure_in_its_note_or_another(tmp_path) -> None:
    document = build(tmp_path, "# One\n\n" + figure("a") + "See [[#^a]], [[two#^b|the second]] and [[one#Two]].\n",
                     "# Two\n\n" + figure("b"))

    [same, other, heading] = links(document["chapters"][0]["content"])
    assert same == {"target": "", "chapter": "one", "heading": "^a", "label": "^a", "figure": "a"}
    assert other == {"target": "two", "chapter": "two", "heading": "^b", "label": "the second", "figure": "b"}
    assert "figure" not in heading


def test_a_block_link_in_a_field_resolves_like_one_in_the_body(tmp_path) -> None:
    document = build(tmp_path, "---\nsee: '[[two#^b]]'\n---\n# One\n", "# Two\n\n" + figure("b"))

    note = next(record for record in document["records"] if record.get("path") == "one.md")
    assert links(note["fieldNodes"]) == [
        {"target": "two", "chapter": "two", "heading": "^b", "label": "Two > ^b", "figure": "b"}]


def test_an_unknown_block_id_names_the_note_the_link_and_the_owner(tmp_path) -> None:
    with pytest.raises(DocumentError) as failure:
        build(tmp_path, "# One\n\n" + figure("a") + "See [[two#^missing]].\n", "# Two\n\n" + figure("b"))

    message = str(failure.value)
    assert message.startswith(f"{tmp_path / 'one.md'}: link [[two#^missing]]: "), message
    assert "see capabilities/wikilinks." in message


def test_a_duplicate_block_id_in_one_note_names_the_note_the_figure_and_the_owner(tmp_path) -> None:
    with pytest.raises(DocumentError) as failure:
        build(tmp_path, "# One\n\n" + figure("a") + figure("a"))

    message = str(failure.value)
    assert message.startswith(f"{tmp_path / 'one.md'}: figure fence 2, block: "), message
    assert "see capabilities/figures." in message


def test_text_that_only_looks_like_a_link_stays_text(tmp_path) -> None:
    document = build(tmp_path, "# One\n\nEmpty [[]] and ![[#^a]] stay.\n")

    assert links(document["chapters"][0]["content"]) == []
