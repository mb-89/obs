"""Pugh decision figures in the core: a pugh fence or a figure fence of kind pugh holds one matrix,
which the core checks and carries as data (input-model, Pugh decision figures).

Reader: whoever changes how the core reads a decision matrix.
"""
import json

import pytest
import yaml

from obs.document import DocumentError

from test_figure_node import _document, _figures


OWNER = "capabilities/pugh-decisions"
MATRIX = {
    "title": "Which queue",
    "chosen": "managed",
    "criteria": [
        {"key": "latency", "label": "p99 latency (ms)", "weight": 3, "better": "lower"},
        {"key": "ops", "label": "Ease of operation", "weight": 2, "better": "higher", "kind": "judged"},
    ],
    "candidates": [
        {"key": "current", "label": "Current queue", "short": "Current", "values": {"latency": 12}},
        {"key": "managed", "label": "Managed queue", "what": "A hosted queue we rent.",
         "wins": "No servers to run.", "losses": ["A bill every month", "Its latency"],
         "values": {"latency": 14}, "marks": {"ops": [2, 1, 2]}},
    ],
    "checklist": [
        {"item": "Does it keep our data in the EU?", "answer": "Both do.", "pass": True},
        {"item": "Can we leave it within a month?", "answer": "Not the managed one.", "pass": False,
         "options": ["B"]},
    ],
    "checklistWeight": 2,
    "gates": [{"criterion": "latency", "maxRatio": 2}],
    "datum": {"prefer": ["current"]},
}


def _changed(change) -> dict:
    matrix = json.loads(json.dumps(MATRIX))
    change(matrix)
    return matrix


def test_a_pugh_fence_and_a_figure_fence_of_kind_pugh_carry_the_matrix_as_data(tmp_path) -> None:
    document = _document(tmp_path, f"# Chapter\n\n```pugh\n{yaml.safe_dump(MATRIX)}```\n\n"
                         f"```figure\nversion: 1\nkind: pugh\ncaption: The queue.\nsource: queue.yaml\n```\n^queue\n",
                         {"queue.yaml": yaml.safe_dump(MATRIX)})

    plain, figure = _figures(document)

    assert plain["attrs"] == {"kind": "pugh"}
    assert plain["children"] == figure["children"] == [
        {"type": "pugh", "attrs": {"matrix": MATRIX, "shortNames": ["Current", "Managed queue"]}, "children": []}]
    assert figure["attrs"]["block"] == "queue"
    assert {"figures", "pugh-decisions"} <= set(document["capabilities"])


def test_the_core_resolves_each_options_short_name_once_into_the_figure_body(tmp_path) -> None:
    matrix = _changed(lambda m: m["candidates"].append(
        {"key": "rented", "label": "A queue rented from a vendor", "values": {"latency": 20}}))

    plain, = _figures(_document(tmp_path, f"```pugh\n{yaml.safe_dump(matrix)}```\n"))

    # Its short where given, else a label of at most 5 words, else none, and the letter stands alone.
    assert plain["children"][0]["attrs"]["shortNames"] == ["Current", "Managed queue", None]
    assert "shortNames" not in matrix and plain["children"][0]["attrs"]["matrix"] == matrix


@pytest.mark.parametrize(("change", "field"), [
    (lambda m: m["criteria"][0].update(better="smaller"), "content.criteria[0].better"),
    (lambda m: m["criteria"][1].update(key="latency"), "content.criteria[1].key"),
    (lambda m: m["candidates"][1].update(key="current"), "content.candidates[1].key"),
    (lambda m: m["candidates"][0].update(values={"ops": 1}), "content.candidates[0].values.ops"),
    (lambda m: m["candidates"][1].update(marks={"latency": 1}), "content.candidates[1].marks.latency"),
    (lambda m: m["candidates"][1].update(marks={"speed": 1}), "content.candidates[1].marks.speed"),
    (lambda m: m["candidates"][1].update(marks={"ops": 3}), "content.candidates[1].marks.ops"),
    (lambda m: m["candidates"][1].update(figures=[]), "content.candidates[1].figures"),
    (lambda m: m.update(overrides=[]), "content.overrides"),
    (lambda m: m["gates"][0].update(criterion="cost"), "content.gates[0].criterion"),
    (lambda m: m.update(gates=[{"criterion": "ops", "max": 1}]), "content.gates[0].max"),
    (lambda m: m["gates"][0].update(max=3), "content.gates[0]"),
    (lambda m: m["datum"].update(prefer=["later"]), "content.datum.prefer[0]"),
    (lambda m: m.update(chosen="later"), "content.chosen"),
    (lambda m: m.pop("criteria"), "content.criteria"),
    (lambda m: m["candidates"][0].update(short="The queue we run here today"), "content.candidates[0].short"),
    (lambda m: m["candidates"][0].update(short=""), "content.candidates[0].short"),
    (lambda m: m["checklist"][1].update(options=["C"]), "content.checklist[1].options[0]"),
    (lambda m: m["checklist"][0].pop("pass"), "content.checklist[0].pass"),
    (lambda m: m["criteria"][1].update(key="checklist"), "content.criteria[1].key"),
    (lambda m: m.update(checklistWeight=-1), "content.checklistWeight"),
    (lambda m: m["candidates"][1].update(marks={"ops": {"mark": 3, "because": "Too good"}}), "content.candidates[1].marks.ops.mark"),
    (lambda m: m["candidates"][1].update(marks={"ops": {"because": "No mark"}}), "content.candidates[1].marks.ops"),
    (lambda m: m["candidates"][1].update(marks={"ops": {"mark": 1, "because": ""}}), "content.candidates[1].marks.ops.because"),
    (lambda m: m["candidates"][1].update(marks={"ops": {"mark": 1, "why": "x"}}), "content.candidates[1].marks.ops"),
    (lambda m: m.update(context=""), "content.context"),
    (lambda m: m.update(concern=["a list"]), "content.concern"),
    (lambda m: m.update(confirmation="The check holds."), "content.confirmation"),
    (lambda m: m["candidates"][1].update(success=""), "content.candidates[1].success"),
    (lambda m: m.update(supersededBy=12), "content.supersededBy"),
    (lambda m: m.update(status="accepted"), "content.status"),
])
def test_a_matrix_the_core_refuses_names_the_note_the_fence_the_field_and_the_owner(tmp_path, change, field) -> None:
    content = json.dumps(_changed(change))
    with pytest.raises(DocumentError) as failure:
        _document(tmp_path, f"```figure\nversion: 1\nkind: pugh\ncaption: A decision.\ncontent: {content}\n```\n")

    message = str(failure.value)
    assert message.startswith(f"{tmp_path / 'chapter.md'}: figure fence 1, {field}:"), message
    assert f"see {OWNER}." in message


@pytest.mark.parametrize(("text", "field"), [
    ("criteria: [\n", "content"),
    ("- a list\n", "content"),
    (yaml.safe_dump(_changed(lambda m: m["criteria"][0].update(weight=-1))), "content.criteria[0].weight"),
])
def test_a_plain_pugh_fence_names_its_field_too(tmp_path, text, field) -> None:
    with pytest.raises(DocumentError) as failure:
        _document(tmp_path, f"```pugh\n{text}```\n")

    message = str(failure.value)
    assert message.startswith(f"{tmp_path / 'chapter.md'}: pugh fence 1, {field}:"), message
    assert f"see {OWNER}." in message


def test_a_source_file_names_its_field_below_source(tmp_path) -> None:
    with pytest.raises(DocumentError) as failure:
        _document(tmp_path, "```figure\nversion: 1\nkind: pugh\ncaption: A decision.\nsource: queue.json\n```\n",
                  {"queue.json": json.dumps(_changed(lambda m: m.update(chosen="later")))})

    message = str(failure.value)
    assert message.startswith(f"{tmp_path / 'chapter.md'}: figure fence 1, source.chosen:"), message
    assert f"see {OWNER}." in message


def test_a_mark_may_carry_its_reason_the_decision_its_context_concern_and_successor_and_an_option_its_success(tmp_path) -> None:
    """input-model, Pugh decision figures: a mark is a number, a rater list, or the mark with its
    reason; context, concern and supersededBy are optional text, and so is an option's success. The
    body carries them as written; an adapter hands ctrl's engine the marks alone."""
    matrix = _changed(lambda m: m.update(
        context="a team of three running its own servers", concern="the queue's upkeep", supersededBy="Decision 12"))
    matrix["candidates"][1]["success"] = "The on-call log shows no queue incident for a quarter."
    matrix["candidates"][1]["marks"] = {"ops": {"mark": [2, 1, 2], "because": "the vendor runs it"}}

    plain, = _figures(_document(tmp_path, f"```pugh\n{yaml.safe_dump(matrix)}```\n"))

    assert plain["children"][0]["attrs"]["matrix"] == matrix
