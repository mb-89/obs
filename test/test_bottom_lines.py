"""The pure bottom-line functions (src/obs/bottom_lines.py, input-model#Bottom lines): which callouts
a note holds, what keeps them from being a bottom line, and the ``bottomLine`` a Document names."""
from obs import bottom_lines


def _paragraph(text: str, **attrs: str) -> dict[str, object]:
    return {"type": "paragraph", "attrs": {}, "children": [{"type": "text", "attrs": {}, "children": [], "text": text}],
            **attrs}


def _bluf(*children: dict[str, object], **attrs: str) -> dict[str, object]:
    return {"type": "callouts", "attrs": {"kind": "bluf", "title": []}, "children": list(children), **attrs}


def _block(kind: str, *children: dict[str, object]) -> dict[str, object]:
    return {"type": kind, "attrs": {}, "children": list(children)}


def test_found_names_the_innermost_block_each_bottom_line_sits_in() -> None:
    top, in_item, in_column, in_card = (_bluf(_paragraph(text)) for text in ("top", "item", "column", "card"))
    nodes = [top, _block("list", _block("list-item", in_item)),
             _block("columns", _block("document", in_column), _block("document")),
             _block("cards-metrics", _block("document", in_card)),
             {"type": "callouts", "attrs": {"kind": "note", "title": []}, "children": []}]

    assert bottom_lines.found(nodes) == [(top, None), (in_item, "list item"), (in_column, "columns block"),
                                         (in_card, "card")]


def test_a_nested_bottom_line_is_refused_before_a_second_one() -> None:
    callouts = bottom_lines.found([_bluf(_paragraph("one")), _block("quote", _bluf(_paragraph("two")))])

    assert bottom_lines.problem(callouts, ["line 3", "line 7"])[:2] == (
        "[!bluf] callout, line 7", "it sits inside a quote, and a bottom line belongs to the note itself")


def test_two_bottom_lines_name_both_lines() -> None:
    callouts = bottom_lines.found([_bluf(_paragraph("one")), _bluf(_paragraph("two")), _bluf(_paragraph("three"))])

    assert bottom_lines.problem(callouts, ["line 3", "line 8", "line 12"])[0] == "[!bluf] callouts, lines 3 and 8"


def test_a_body_without_a_first_paragraph_names_what_it_begins_with() -> None:
    empty, listed = bottom_lines.found([_bluf()]), bottom_lines.found([_bluf(_block("list"))])

    assert "its body begins with nothing," in bottom_lines.problem(empty, ["line 3"])[1]
    assert "its body begins with a list," in bottom_lines.problem(listed, ["line 3"])[1]
    assert bottom_lines.problem(bottom_lines.found([_bluf(_paragraph("lead"))]), ["line 3"]) is None
    assert bottom_lines.problem([], []) is None


def test_assign_names_the_bottom_line_and_its_lead_only_where_a_note_has_one() -> None:
    child = {"id": "child", "content": [_bluf(_paragraph("lead", id="paragraph-1"), id="callouts-1")],
             "children": []}
    parent = {"id": "parent", "content": [_paragraph("prose", id="paragraph-2")], "children": [child]}
    document = {"manifest": {"abstract": []}, "chapters": [parent]}

    bottom_lines.assign(document)

    assert child["bottomLine"] == {"callout": "callouts-1", "lead": "paragraph-1"}
    assert "bottomLine" not in parent and "bottomLine" not in document["manifest"]
