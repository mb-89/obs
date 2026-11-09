"""Comments and reviews in the core (input-model, Comments and reviews).

Reader: whoever changes the core's comment format, its overlay files, their union or the meaning of
a review.

Each principal's comments and decisions live in ``<manifest stem>.comments.<principal>.json`` next
to the manifest. The core validates every overlay file, forms their union by immutable id, resolves
replies across files and targets through the Document, and puts the resolved model in the
Document's ``comments``.
"""
import json
from pathlib import Path

import pytest

from obs.comments import review_state, validate_overlay
from obs.document import build_document, main
from obs.input import InputError
from test_vault import capability_reference

OWNER = "input-model#Comments and reviews"


def _vault(tmp_path: Path) -> Path:
    (tmp_path / "manifest.md").write_text("- [[design]]\n", encoding="utf-8")
    (tmp_path / "design.md").write_text(
        "# Design\n\nThe design.\n\n```figure\nversion: 1\nkind: mermaid\ncaption: The flow.\nsource: flow.mmd\n```\n"
        "^flow\n", encoding="utf-8")
    (tmp_path / "flow.mmd").write_text("graph LR\n  A --> B\n", encoding="utf-8")
    return tmp_path / "manifest.md"


def _comment(identifier: str, created: str = "2026-11-09T08:00:00Z", **fields) -> dict:
    entry = {"id": identifier, "author": "Alice", "created": created,
             "body": {"mediaType": "text/plain", "text": f"Comment {identifier}."}, "state": "open"}
    if "inReplyTo" not in fields:
        entry["target"] = {"chapter": "design"}
    return {**entry, **fields}


def _decision(identifier: str, reviewer: str = "Alice", state: str = "accepted", **target) -> dict:
    return {"id": identifier, "reviewer": reviewer, "created": "2026-11-09T08:00:00Z",
            "target": {"chapter": "design", **target}, "state": state}


def _overlay(manifest: Path, principal: str, comments=(), decisions=()) -> Path:
    path = manifest.with_name(f"{manifest.stem}.comments.{principal}.json")
    path.write_text(json.dumps({"version": 1, "principal": principal, "comments": list(comments),
                                "decisions": list(decisions)}), encoding="utf-8")
    return path


def _document(manifest: Path) -> dict:
    return build_document(manifest, capability_reference())


def _failure(manifest: Path) -> str:
    with pytest.raises(InputError) as failure:
        _document(manifest)
    return str(failure.value)


def test_a_document_without_overlay_files_has_no_comments(tmp_path) -> None:
    assert "comments" not in _document(_vault(tmp_path))


def test_the_union_of_every_principals_file_is_the_documents_comments_ordered_by_time_then_id(tmp_path) -> None:
    manifest = _vault(tmp_path)
    _overlay(manifest, "bob", [_comment("b-1", "2026-11-09T09:00:00Z")], [_decision("d-b", "Bob", "rejected")])
    _overlay(manifest, "alice", [_comment("a-2", "2026-11-09T07:00:00Z"), _comment("a-1", "2026-11-09T07:00:00Z")],
             [_decision("d-a", node="flow")])

    comments = _document(manifest)["comments"]

    assert comments["version"] == 1
    assert comments["files"] == ["manifest.comments.alice.json", "manifest.comments.bob.json"]
    assert [comment["id"] for comment in comments["comments"]] == ["a-1", "a-2", "b-1"]
    assert [decision["id"] for decision in comments["decisions"]] == ["d-a", "d-b"]


def test_one_id_with_the_same_payload_in_two_files_is_one_entry(tmp_path) -> None:
    manifest = _vault(tmp_path)
    _overlay(manifest, "alice", [_comment("c-1")])
    _overlay(manifest, "bob", [_comment("c-1")])

    assert [comment["id"] for comment in _document(manifest)["comments"]["comments"]] == ["c-1"]


def test_a_duplicate_id_with_different_payloads_fails_naming_both_files(tmp_path) -> None:
    manifest = _vault(tmp_path)
    first = _overlay(manifest, "alice", [_comment("c-0"), _comment("c-1")])
    second = _overlay(manifest, "bob", [_comment("c-1", state="resolved")])

    message = _failure(manifest)

    assert message.startswith(f"{second}: comments[0]:"), message
    assert f"{first} comments[1]" in message and OWNER in message


def test_a_reply_resolves_to_its_comment_in_another_file(tmp_path) -> None:
    manifest = _vault(tmp_path)
    _overlay(manifest, "alice", [_comment("c-1")])
    _overlay(manifest, "bob", [_comment("r-1", "2026-11-09T09:00:00Z", author="Bob", inReplyTo="c-1")])

    comments = _document(manifest)["comments"]["comments"]

    assert [(comment["id"], comment.get("inReplyTo")) for comment in comments] == [("c-1", None), ("r-1", "c-1")]
    assert "target" not in comments[1]


def test_a_reply_to_no_comment_names_its_file_and_field(tmp_path) -> None:
    manifest = _vault(tmp_path)
    overlay = _overlay(manifest, "bob", [_comment("c-1"), _comment("r-1", inReplyTo="missing")])

    message = _failure(manifest)

    assert message.startswith(f"{overlay}: comments[1].inReplyTo:"), message
    assert OWNER in message


def test_replies_that_reach_no_root_name_their_file_and_field(tmp_path) -> None:
    manifest = _vault(tmp_path)
    overlay = _overlay(manifest, "bob", [_comment("r-1", inReplyTo="r-2"), _comment("r-2", inReplyTo="r-1")])

    message = _failure(manifest)

    assert message.startswith(f"{overlay}: comments[0].inReplyTo:"), message
    assert OWNER in message


@pytest.mark.parametrize(("target", "field"), [
    ({"chapter": "gone"}, "comments[0].target.chapter"),
    ({"chapter": "design", "node": "gone"}, "comments[0].target.node"),
], ids=["chapter", "node"])
def test_an_unmapped_target_is_a_warning_naming_the_file_the_comment_and_the_target(tmp_path, target, field) -> None:
    manifest = _vault(tmp_path)
    overlay = _overlay(manifest, "alice", [_comment("c-1", target=target)])

    document = _document(manifest)

    [warning] = [item["message"] for item in document["diagnostics"] if "c-1" in item["message"]]
    assert warning.startswith(f"{overlay}: {field}:"), warning
    assert "'gone'" in warning and OWNER in warning
    assert [comment["id"] for comment in document["comments"]["comments"]] == ["c-1"]


def test_targets_that_resolve_raise_no_warning(tmp_path) -> None:
    manifest = _vault(tmp_path)
    _overlay(manifest, "alice", [_comment("c-1", target={}), _comment("c-2", target={"chapter": "design", "node": "flow"})],
             [_decision("d-1", node="flow")])

    assert not [item for item in _document(manifest)["diagnostics"] if OWNER in item["message"]]


def test_two_decisions_of_one_reviewer_on_one_target_fail_naming_both(tmp_path) -> None:
    manifest = _vault(tmp_path)
    first = _overlay(manifest, "alice", [], [_decision("d-1", node="flow")])
    second = _overlay(manifest, "bob", [], [_decision("d-2", state="rejected", node="flow")])

    message = _failure(manifest)

    assert message.startswith(f"{second}: decisions[0]:"), message
    assert f"{first} decisions[0]" in message and OWNER in message


@pytest.mark.parametrize(("overlay", "field"), [
    ({"version": 2}, "version"),
    ({"principal": "bob"}, "principal"),
    ({"comments": [_comment("c-1", state="closed")]}, "comments[0].state"),
    ({"comments": [{**_comment("c-1"), "inReplyTo": "c-0"}]}, "comments[0]"),
    ({"decisions": [_decision("d-1", state="waiting")]}, "decisions[0].state"),
], ids=["version", "principal", "state", "root and reply", "decision state"])
def test_an_overlay_the_core_refuses_names_the_file_the_field_and_the_owner(tmp_path, overlay, field) -> None:
    manifest = _vault(tmp_path)
    path = _overlay(manifest, "alice")
    path.write_text(json.dumps({"version": 1, "principal": "alice", "comments": [], "decisions": [], **overlay}),
                    encoding="utf-8")

    message = _failure(manifest)

    assert message.startswith(f"{path}: {field}"), message
    assert OWNER in message


def test_an_overlay_file_name_without_a_valid_principal_names_the_file(tmp_path) -> None:
    manifest = _vault(tmp_path)
    path = manifest.with_name("manifest.comments.Alice Smith.json")
    path.write_text("{}", encoding="utf-8")

    message = _failure(manifest)

    assert message.startswith(f"{path}: top level:"), message
    assert OWNER in message


def test_validate_overlay_is_the_import_check_adapters_use(tmp_path) -> None:
    path = tmp_path / "manifest.comments.alice.json"
    validate_overlay({"version": 1, "principal": "alice", "comments": [_comment("c-1")], "decisions": []}, path)
    with pytest.raises(InputError) as failure:
        validate_overlay({"version": 1, "principal": "alice", "comments": [_comment("c-1", state="closed")],
                          "decisions": []}, path)

    assert str(failure.value).startswith(f"{path}: comments[0].state"), str(failure.value)


def test_the_review_state_is_per_reviewer_and_rejection_wins_the_aggregate() -> None:
    decisions = [_decision("d-1", "Alice", "accepted", node="flow"), _decision("d-2", "Bob", "rejected", node="flow"),
                 _decision("d-3", "Bob", "accepted")]
    flow, chapter = {"chapter": "design", "node": "flow"}, {"chapter": "design"}

    assert review_state(decisions, flow, "Alice") == "accepted"
    assert review_state(decisions, flow, "Bob") == "rejected"
    assert review_state(decisions, flow, "Carol") == "waiting"
    assert review_state(decisions, flow) == "rejected"
    assert review_state(decisions, chapter) == "accepted"
    assert review_state(decisions, {}) == "waiting"


def test_the_cli_writes_the_resolved_comments_into_the_document(tmp_path) -> None:
    (tmp_path / "vault").mkdir()
    manifest = _vault(tmp_path / "vault")
    _overlay(manifest, "alice", [_comment("c-1")])
    document = tmp_path / "document.json"

    assert main(["--source", str(manifest), "--document", str(document)]) == 0
    assert [comment["id"] for comment in json.loads(document.read_text(encoding="utf-8"))["comments"]["comments"]] \
        == ["c-1"]


def test_the_shared_review_state_fixture_holds_for_the_core() -> None:
    """The cases adapters/html/test/comment-model.test.js runs against the HTML adapter's browser mapping."""
    fixture = json.loads((Path(__file__).parent / "fixtures" / "review-state-conformance.json").read_text(
        encoding="utf-8"))
    for case in fixture["cases"]:
        assert review_state(fixture["decisions"], case["target"], case.get("reviewer")) == case["expected"], case
