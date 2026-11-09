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

from obs.comments import comment_state, import_comments, review_state, validate_overlay
from obs.document import build_document, main
from obs.input import InputError
from test_vault import capability_reference

OWNER = "input-model#Comments and reviews"


def _vault(tmp_path: Path, abstract: str = "") -> Path:
    (tmp_path / "manifest.md").write_text(f"- [[design]]\n\n{abstract}", encoding="utf-8")
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


def _state(identifier: str, comment: str, state: str, created: str, author: str = "Alice") -> dict:
    return {"id": identifier, "author": author, "created": created, "target": comment, "state": state}


def _overlay(manifest: Path, principal: str, comments=(), decisions=(), states=()) -> Path:
    path = manifest.with_name(f"{manifest.stem}.comments.{principal}.json")
    overlay = {"version": 1, "principal": principal, "comments": list(comments), "decisions": list(decisions)}
    path.write_text(json.dumps({**overlay, "states": list(states)} if states else overlay), encoding="utf-8")
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
    comments = {comment["id"]: comment for comment in fixture["comments"]}
    for case in fixture["commentCases"]:
        assert comment_state(comments[case["comment"]], fixture["states"]) == case["expected"], case


def _warnings(document: dict) -> list[str]:
    return [diagnostic["message"] for diagnostic in document["diagnostics"] if ".comments." in diagnostic["message"]]


def test_a_target_in_the_manifest_abstract_resolves_and_one_it_lacks_warns(tmp_path) -> None:
    manifest = _vault(tmp_path, "The abstract. ^summary\n")
    path = _overlay(manifest, "alice", [
        _comment("c-1", target={"abstract": True}),
        _comment("c-2", target={"abstract": True, "node": "summary", "quote": "abstract"}),
        _comment("c-3", target={"abstract": True, "node": "gone"}),
    ], [{**_decision("d-1"), "target": {"abstract": True, "node": "summary"}}])

    warnings = _warnings(_document(manifest))

    assert len(warnings) == 1 and warnings[0].startswith(f"{path}: comments[2].target.node: "), warnings
    assert "'c-3'" in warnings[0] and OWNER in warnings[0]


@pytest.mark.parametrize("target, field", [
    ({"abstract": True, "chapter": "design"}, "comments[0].target"),
    ({"node": "summary"}, "comments[0].target"),
    ({"abstract": False}, "comments[0].target.abstract"),
])
def test_a_target_is_in_the_abstract_or_a_chapter_never_both(tmp_path, target, field) -> None:
    path = tmp_path / "manifest.comments.alice.json"
    with pytest.raises(InputError) as failure:
        validate_overlay({"version": 1, "principal": "alice", "comments": [_comment("c-1", target=target)],
                          "decisions": []}, path)
    assert str(failure.value).split(": ")[1] == field and OWNER in str(failure.value)


def test_state_entries_across_files_resolve_then_reopen_a_comment(tmp_path) -> None:
    manifest = _vault(tmp_path)
    _overlay(manifest, "alice", [_comment("c-1")])
    _overlay(manifest, "bob", states=[_state("s-bob", "c-1", "resolved", "2026-11-09T09:00:00Z", "Bob")])

    resolved = _document(manifest)["comments"]
    assert [state["id"] for state in resolved["states"]] == ["s-bob"]
    assert comment_state(resolved["comments"][0], resolved["states"]) == "resolved"

    _overlay(manifest, "carol", states=[_state("s-carol", "c-1", "open", "2026-11-09T10:00:00Z", "Carol")])
    reopened = _document(manifest)["comments"]
    assert [state["id"] for state in reopened["states"]] == ["s-bob", "s-carol"]
    assert reopened["comments"][0]["state"] == "open"
    assert comment_state(reopened["comments"][0], reopened["states"]) == "open"


def test_state_entries_of_the_same_time_resolve_by_author_then_id() -> None:
    comment, at = _comment("c-1"), "2026-11-09T09:00:00Z"
    assert comment_state(comment, [_state("s-1", "c-1", "resolved", at, "Bob"),
                                   _state("s-2", "c-1", "open", at, "Alice")]) == "open"
    assert comment_state(comment, [_state("s-2", "c-1", "open", at), _state("s-1", "c-1", "resolved", at)]) \
        == "resolved"
    assert comment_state(comment, [_state("s-1", "c-2", "resolved", at)]) == "open"


def test_a_state_entry_naming_no_comment_names_its_file_and_field(tmp_path) -> None:
    manifest = _vault(tmp_path)
    path = _overlay(manifest, "bob", states=[_state("s-1", "missing", "resolved", "2026-11-09T09:00:00Z")])

    message = _failure(manifest)

    assert message.startswith(f"{path}: states[0].target: ") and "'missing'" in message and OWNER in message


def _returned(path: Path, comments=(), decisions=(), states=()) -> Path:
    """What an adapter returns: the comments of a reviewed copy in the core's resolved shape."""
    path.write_text(json.dumps({"version": 1, "files": [], "comments": list(comments),
                                "decisions": list(decisions), "states": list(states)}), encoding="utf-8")
    return path


def test_an_import_writes_the_principals_file_without_what_other_files_hold(tmp_path) -> None:
    (tmp_path / "vault").mkdir()
    manifest = _vault(tmp_path / "vault")
    reply = _comment("b-1", "2026-11-09T09:00:00Z", author="Bob", inReplyTo="a-1")
    _overlay(manifest, "bob", [reply])
    returned = _returned(tmp_path / "returned.json", [_comment("a-1"), reply], [_decision("d-1")])

    assert main(["--source", str(manifest), "--import-comments", str(returned), "--principal", "alice",
                 "--document", str(tmp_path / "doc.json")]) == 0

    written = json.loads(manifest.with_name("manifest.comments.alice.json").read_text(encoding="utf-8"))
    assert written == {"version": 1, "principal": "alice", "comments": [_comment("a-1")], "decisions": [_decision("d-1")]}
    assert [comment["id"] for comment in json.loads((tmp_path / "doc.json").read_text())["comments"]["comments"]] \
        == ["a-1", "b-1"]


def test_an_import_that_changes_another_principals_entry_names_both_files(tmp_path) -> None:
    (tmp_path / "vault").mkdir()
    manifest = _vault(tmp_path / "vault")
    other = _overlay(manifest, "bob", [_comment("b-1", author="Bob")])
    returned = _returned(tmp_path / "returned.json", [_comment("b-1", author="Bob", state="resolved")])

    with pytest.raises(InputError) as failure:
        import_comments(manifest, returned, "alice")

    assert str(failure.value).startswith(f"{returned}: comments[0]: ") and str(other) in str(failure.value)
    assert OWNER in str(failure.value)
    assert not manifest.with_name("manifest.comments.alice.json").exists()


def test_an_import_writes_a_readers_resolve_of_another_principals_comment_as_their_own_entry(tmp_path) -> None:
    (tmp_path / "vault").mkdir()
    manifest = _vault(tmp_path / "vault")
    theirs = _comment("b-1", author="Bob")
    _overlay(manifest, "bob", [theirs])
    resolve = _state("s-1", "b-1", "resolved", "2026-11-09T09:00:00Z")
    returned = _returned(tmp_path / "returned.json", [theirs], states=[resolve])

    import_comments(manifest, returned, "alice")

    written = json.loads(manifest.with_name("manifest.comments.alice.json").read_text(encoding="utf-8"))
    assert written == {"version": 1, "principal": "alice", "comments": [], "decisions": [], "states": [resolve]}
    resolved = _document(manifest)["comments"]
    assert comment_state(resolved["comments"][0], resolved["states"]) == "resolved"


def test_an_import_refuses_a_body_edit_to_another_principals_comment(tmp_path) -> None:
    (tmp_path / "vault").mkdir()
    manifest = _vault(tmp_path / "vault")
    _overlay(manifest, "bob", [_comment("b-1", author="Bob")])
    edited = _comment("b-1", author="Bob", body={"mediaType": "text/plain", "text": "Alice's words."})
    returned = _returned(tmp_path / "returned.json", [edited])

    with pytest.raises(InputError) as failure:
        import_comments(manifest, returned, "alice")

    message = str(failure.value)
    assert message.split(": ")[:2] == [str(returned), "comments[0].body"], message
    assert all(name in message for name in ("'b-1'", "'Bob'", "'alice'", OWNER)), message
    assert not manifest.with_name("manifest.comments.alice.json").exists()


@pytest.mark.parametrize("returned, principal, field", [
    ({"version": 1, "files": [], "comments": [_comment("c", state="done")], "decisions": []}, "alice",
     "comments[0].state"),
    ({"version": 2, "annotations": []}, "alice", "version"),
    ({"version": 1, "files": [], "comments": [], "decisions": []}, "Alice Smith", "principal"),
])
def test_an_import_the_core_refuses_names_the_field_and_the_owner(tmp_path, returned, principal, field) -> None:
    (tmp_path / "vault").mkdir()
    manifest = _vault(tmp_path / "vault")
    path = tmp_path / "returned.json"
    path.write_text(json.dumps(returned), encoding="utf-8")

    with pytest.raises(InputError) as failure:
        import_comments(manifest, path, principal)

    assert str(failure.value).split(": ")[1] == field and OWNER in str(failure.value)


def test_a_keyed_rows_target_may_name_a_field_and_a_sync_key_may_not(tmp_path) -> None:
    path = tmp_path / "manifest.comments.alice.json"
    detail = _comment("c-1", target={"chapter": "design", "node": "registers-1:alpha", "field": "status"})
    validate_overlay({"version": 1, "principal": "alice", "comments": [detail], "decisions": []}, path)
    with pytest.raises(InputError) as failure:
        validate_overlay({"version": 1, "principal": "alice", "decisions": [],
                          "comments": [_comment("c-2", target={"chapter": "design", "field": "status"})]}, path)
    assert str(failure.value).startswith(f"{path}: comments[0].target")
    sync = json.loads((Path(__file__).parents[1] / "src" / "obs" / "sync.schema.json").read_text(encoding="utf-8"))
    assert "field" not in sync["$defs"]["node"]["properties"]
    assert sync["$defs"]["node"].get("additionalProperties") is False
