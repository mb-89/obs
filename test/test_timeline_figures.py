"""Timeline figures in the core: a figure fence of kind timeline holds a query and the names of the
record fields that place each record; the core checks the content and every record it selects,
includes those records and carries the content as data (input-model, Timeline figures).

Reader: whoever changes how the core reads a timeline figure.
"""
import json

import pytest
import yaml

from obs.document import DocumentError

from test_figure_node import _document, _figures


OWNER = "capabilities/timeline-figures"
CONTENT = {
    "records": {"where": [{"field": "kind", "equals": "work-item"}]},
    "date": "when", "lane": "team", "today": "2026-11-16",
    "lanes": ["Build", "Review"],
    "band": "state",
    "bands": [{"value": "doing", "label": "Today", "at": "today"}, {"value": "later", "label": "Later", "at": "end"}],
    "anchor": "today", "label": "short", "text": "summary", "flags": "flags", "marker": "release",
}
RECORDS = {
    "work/draft.md": {"kind": "work-item", "when": "2026-11-02", "team": "Build", "short": "Draft",
                      "flags": [{"label": "review", "tone": "warning"}], "obs": {"document": False}},
    "work/doing.md": {"kind": "work-item", "state": "doing", "team": "Review"},
    "work/plan.md": {"kind": "work-item", "when": "2026-11-20", "team": "Review"},
    "work/release.md": {"kind": "work-item", "when": "2026-11-02", "team": "Build", "release": True},
    "work/other.md": {"kind": "note", "when": "not a day"},
}


def _fence(content: dict, field: str = "content") -> str:
    value = json.dumps(content) if field == "content" else content
    return f"# Chapter\n\n```figure\nversion: 1\nkind: timeline\ncaption: Work.\nalt: Work by day\n{field}: {value}\n```\n"


def _vault(tmp_path, records: dict[str, dict]) -> None:
    (tmp_path / "work").mkdir(exist_ok=True)
    for name, fields in records.items():
        (tmp_path / name).write_text(f"---\n{yaml.safe_dump(fields)}---\n# {name}\n", encoding="utf-8")


def _changed(change) -> dict:
    content = json.loads(json.dumps(CONTENT))
    change(content)
    return content


def test_a_timeline_figure_carries_its_content_and_includes_the_records_its_query_selects(tmp_path) -> None:
    _vault(tmp_path, RECORDS)
    (tmp_path / "timeline.yaml").write_text(yaml.safe_dump(CONTENT), encoding="utf-8")

    inline, = _figures(_document(tmp_path, _fence(CONTENT)))
    document = _document(tmp_path, _fence("timeline.yaml", "source"))
    external, = _figures(document)

    assert inline["children"] == external["children"] == [{"type": "timeline", "attrs": CONTENT, "children": []}]
    assert "timeline-figures" in document["capabilities"]
    # The selected records are included, a record-only note too; the note the query leaves out is not.
    chapters = {chapter["id"] for chapter in document["chapters"]}
    paths = sorted(record["path"] for record in document["records"] if record["type"] == "note" and record["id"] in chapters)
    assert paths == ["chapter.md", "work/doing.md", "work/draft.md", "work/plan.md", "work/release.md"]


def test_a_timeline_whose_query_selects_nothing_is_valid_input(tmp_path) -> None:
    content = _changed(lambda c: c.update(records={"where": [{"field": "kind", "equals": "nothing"}]}))

    figure, = _figures(_document(tmp_path, _fence(content)))

    assert figure["children"][0]["attrs"]["records"] == content["records"]


def test_a_timeline_query_narrows_its_from_owners_selection(tmp_path) -> None:
    _vault(tmp_path, RECORDS)
    (tmp_path / "work" / "owner.md").write_text(
        "---\nquery: {where: [{field: team, equals: Build}]}\n---\n# Owner\n", encoding="utf-8")
    content = _changed(lambda c: c.update(records={"from": "work/owner", "where": [{"field": "kind", "equals": "work-item"}]}))

    document = _document(tmp_path, _fence(content))

    titles = {chapter["title"] for chapter in document["chapters"]}
    assert {"work/draft.md", "work/release.md", "Owner"} <= titles
    assert not {"work/doing.md", "work/plan.md"} & titles


@pytest.mark.parametrize(("change", "field"), [
    (lambda c: c.pop("today"), "content.today"),
    (lambda c: c.update(today="16 Nov 2026"), "content.today"),
    (lambda c: c.update(today="2026-02-30"), "content.today"),
    (lambda c: c.pop("date"), "content.date"),
    (lambda c: c.update(records={"where": [{"field": "kind"}]}), "content.records.where[0]"),
    (lambda c: c.update(lanes=["A", "B", "C", "D", "E", "F", "G", "H", "I"]), "content.lanes"),
    (lambda c: c["bands"][1].update(at="soon"), "content.bands[1].at"),
    (lambda c: c["bands"][1].update(value="doing"), "content.bands[1].value"),
    (lambda c: c.update(anchor="someday"), "content.anchor"),
    (lambda c: c.update(colour="#ff0000"), "content.colour"),
])
def test_content_the_core_refuses_names_the_note_the_fence_the_field_and_the_owner(tmp_path, change, field) -> None:
    with pytest.raises(DocumentError) as failure:
        _document(tmp_path, _fence(_changed(change)))

    message = str(failure.value)
    assert message.startswith(f"{tmp_path / 'chapter.md'}: figure fence 1, {field}"), message
    assert f"see {OWNER}." in message


def test_a_band_field_without_bands_is_refused(tmp_path) -> None:
    with pytest.raises(DocumentError) as failure:
        _document(tmp_path, _fence(_changed(lambda c: c.pop("bands"))))

    message = str(failure.value)
    assert message.startswith(f"{tmp_path / 'chapter.md'}: figure fence 1, content"), message
    assert "bands" in message and f"see {OWNER}." in message


@pytest.mark.parametrize(("record", "field"), [
    ({"when": "2026-13-02"}, "when"),
    ({"when": "next week"}, "when"),
    ({"when": None}, "when"),
    ({"team": "Ops"}, "team"),
    ({"team": None}, "team"),
    ({"flags": [{"label": "late", "tone": "red"}]}, "flags[0].tone"),
    ({"flags": [{"tone": "warning"}]}, "flags[0]"),
    ({"flags": "late"}, "flags"),
    ({"state": "paused"}, "state"),
])
def test_a_record_the_core_refuses_names_the_record_its_field_and_the_owner(tmp_path, record, field) -> None:
    _vault(tmp_path, {"work/draft.md": {**RECORDS["work/draft.md"], **record}})

    with pytest.raises(DocumentError) as failure:
        _document(tmp_path, _fence(CONTENT))

    message = str(failure.value)
    assert message.startswith(f"{tmp_path / 'work' / 'draft.md'}: {field}:"), message
    assert "chapter.md" in message and f"see {OWNER}." in message


def test_a_record_in_a_listed_band_needs_no_day(tmp_path) -> None:
    _vault(tmp_path, {"work/doing.md": RECORDS["work/doing.md"]})

    figure, = _figures(_document(tmp_path, _fence(CONTENT)))

    assert figure["children"][0]["type"] == "timeline"


def test_without_lanes_the_records_may_name_at_most_eight(tmp_path) -> None:
    _vault(tmp_path, {f"work/{index}.md": {"kind": "work-item", "when": "2026-11-02", "team": f"Team {index}"}
                      for index in range(9)})

    with pytest.raises(DocumentError) as failure:
        _document(tmp_path, _fence(_changed(lambda c: c.pop("lanes"))))

    message = str(failure.value)
    assert "figure fence 1, content.lane:" in message and f"see {OWNER}." in message
