"""Sync records in the core (input-model, Sync records).

Reader: whoever changes the core's sync records, their record files, the sync results adapters
return, or how the core persists them.

A namespace's records live in ``<manifest stem>.sync.<namespace>.json`` next to the manifest. An
adapter returns a sync result; ``obs-document --sync-result`` applies it to the record file, and the
Document carries every record file as its ``sync``.
"""
import json
from pathlib import Path

import pytest

from obs.document import build_document, main
from obs.input import InputError
from obs.sync import apply_result
from test_vault import capability_reference

OWNER = "input-model#Sync records"
HASH = "sha256:" + "0" * 64


def _vault(tmp_path: Path) -> Path:
    (tmp_path / "manifest.md").write_text("- [[design]]\n", encoding="utf-8")
    (tmp_path / "design.md").write_text(
        "# Design\n\nThe design.\n\n```figure\nversion: 1\nkind: mermaid\ncaption: The flow.\nsource: flow.mmd\n```\n"
        "^flow\n", encoding="utf-8")
    (tmp_path / "flow.mmd").write_text("graph LR\n  A --> B\n", encoding="utf-8")
    return tmp_path / "manifest.md"


def _record(external: str, revision: str = "1", **node) -> dict:
    return {"node": {"chapter": "design", **node}, "external": [external], "revision": revision, "hash": HASH,
            "links": [], "base": {"type": "chapter"}}


def _result(path: Path, created=(), updated=(), conflicts=(), namespace: str = "example") -> Path:
    path.write_text(json.dumps({"version": 1, "namespace": namespace, "created": list(created),
                                "updated": list(updated), "conflicts": list(conflicts)}), encoding="utf-8")
    return path


def _records(manifest: Path, records=(), namespace: str = "example", **fields) -> Path:
    path = manifest.with_name(f"{manifest.stem}.sync.{namespace}.json")
    path.write_text(json.dumps({"version": 1, "namespace": namespace, "manifest": manifest.name,
                                "records": list(records), "conflicts": [], **fields}), encoding="utf-8")
    return path


def _document(manifest: Path) -> dict:
    return build_document(manifest, capability_reference())


def _refused(call, *arguments) -> str:
    with pytest.raises(InputError) as failure:
        call(*arguments)
    return str(failure.value)


def test_a_document_without_record_files_has_no_sync(tmp_path) -> None:
    assert "sync" not in _document(_vault(tmp_path))


def test_a_created_record_is_persisted_next_to_the_manifest_and_carried_by_the_document(tmp_path) -> None:
    manifest = _vault(tmp_path)

    apply_result(manifest, _result(tmp_path / "result.json", created=[_record("page-1", node="flow")]))

    stored = json.loads((tmp_path / "manifest.sync.example.json").read_text(encoding="utf-8"))
    assert stored["manifest"] == "manifest.md"
    assert stored["records"] == [_record("page-1", node="flow")]
    assert _document(manifest)["sync"] == {"example": {"file": "manifest.sync.example.json",
                                                       "records": [_record("page-1", node="flow")], "conflicts": []}}


def test_an_update_replaces_its_record_and_keeps_the_others(tmp_path) -> None:
    manifest = _vault(tmp_path)
    _records(manifest, [_record("page-1"), _record("page-2", node="flow")])

    apply_result(manifest, _result(tmp_path / "result.json", updated=[_record("page-1", "2")]))

    records = _document(manifest)["sync"]["example"]["records"]
    assert records == [_record("page-1", "2"), _record("page-2", node="flow")]


def test_an_update_without_a_record_is_refused_as_a_missing_record(tmp_path) -> None:
    manifest = _vault(tmp_path)
    result = _result(tmp_path / "result.json", updated=[_record("page-1")])

    assert _refused(apply_result, manifest, result).startswith(f"{result}: updated[0].node:")
    assert not (tmp_path / "manifest.sync.example.json").exists()


def test_a_creation_of_a_recorded_node_is_refused(tmp_path) -> None:
    manifest = _vault(tmp_path)
    _records(manifest, [_record("page-1")])
    result = _result(tmp_path / "result.json", created=[_record("page-2")])

    assert _refused(apply_result, manifest, result).startswith(f"{result}: created[0].node:")


def test_a_duplicate_claim_is_refused_naming_both_records_and_leaves_the_file_unchanged(tmp_path) -> None:
    manifest = _vault(tmp_path)
    path = _records(manifest, [_record("page-1")])
    before = path.read_text(encoding="utf-8")

    message = _refused(apply_result, manifest,
                       _result(tmp_path / "result.json", created=[_record("page-1", node="flow")]))

    assert message.startswith(f"{path}: records[1].external[0]:"), message
    assert "records[0].external[0]" in message and OWNER in message
    assert path.read_text(encoding="utf-8") == before


def test_a_record_file_with_a_duplicate_claim_fails_the_build(tmp_path) -> None:
    manifest = _vault(tmp_path)
    path = _records(manifest, [_record("page-1"), _record("page-1", node="flow")])

    assert _refused(_document, manifest).startswith(f"{path}: records[1].external[0]:")


def test_two_records_of_one_node_fail_the_build(tmp_path) -> None:
    manifest = _vault(tmp_path)
    path = _records(manifest, [_record("page-1"), _record("page-2")])

    assert _refused(_document, manifest).startswith(f"{path}: records[1].node:")


def test_conflicts_of_a_result_replace_the_files(tmp_path) -> None:
    manifest = _vault(tmp_path)
    _records(manifest, [_record("page-1")], conflicts=[{"node": {}, "external": "old", "message": "Old."}])
    conflict = {"node": {"chapter": "design"}, "external": "page-1", "message": "Both sides changed."}

    apply_result(manifest, _result(tmp_path / "result.json", conflicts=[conflict]))

    assert _document(manifest)["sync"]["example"]["conflicts"] == [conflict]


@pytest.mark.parametrize(("node", "field"), [({"chapter": "gone"}, "records[0].node.chapter"),
                                             ({"chapter": "design", "node": "gone"}, "records[0].node.node")])
def test_a_record_of_a_node_the_document_lacks_is_a_warning(tmp_path, node, field) -> None:
    manifest = _vault(tmp_path)
    path = _records(manifest, [{**_record("page-1"), "node": node}])

    warnings = [item["message"] for item in _document(manifest)["diagnostics"] if item["level"] == "warning"]

    assert any(message.startswith(f"{path}: {field}:") and OWNER in message for message in warnings), warnings


@pytest.mark.parametrize(("fields", "field"), [
    ({"namespace": "other"}, "namespace"),
    ({"manifest": "other.md"}, "manifest"),
    ({"records": [{**_record("page-1"), "hash": "md5:0"}]}, "records[0].hash"),
    ({"records": [{**_record("page-1"), "external": []}]}, "records[0].external"),
])
def test_a_record_file_the_core_refuses_names_the_file_the_field_and_the_owner(tmp_path, fields, field) -> None:
    manifest = _vault(tmp_path)
    path = _records(manifest)
    path.write_text(json.dumps({**json.loads(path.read_text(encoding="utf-8")), **fields}), encoding="utf-8")

    message = _refused(_document, manifest)

    assert message.startswith(f"{path}: {field}:") and OWNER in message, message


def test_a_record_file_name_without_a_valid_namespace_names_the_file(tmp_path) -> None:
    manifest = _vault(tmp_path)
    path = tmp_path / "manifest.sync.Example.json"
    path.write_text("{}", encoding="utf-8")

    assert _refused(_document, manifest).startswith(f"{path}: top level:")


def test_a_result_the_core_refuses_names_the_result_and_its_field(tmp_path) -> None:
    manifest = _vault(tmp_path)
    result = _result(tmp_path / "result.json", created=[{**_record("page-1"), "revision": 1}])

    assert _refused(apply_result, manifest, result).startswith(f"{result}: created[0].revision:")


def test_the_cli_applies_a_sync_result_before_it_builds_the_document(tmp_path) -> None:
    (tmp_path / "vault").mkdir()
    manifest = _vault(tmp_path / "vault")
    result = _result(tmp_path / "result.json", created=[_record("page-1")])
    document = tmp_path / "document.json"

    assert main(["--source", str(manifest), "--document", str(document), "--sync-result", str(result)]) == 0
    assert json.loads(document.read_text(encoding="utf-8"))["sync"]["example"]["records"] == [_record("page-1")]


def test_the_cli_refuses_a_sync_result_without_a_source(tmp_path) -> None:
    with pytest.raises(SystemExit) as failure:
        main(["--document", str(tmp_path / "document.json"), "--adapter", "html",
              "--destination", str(tmp_path / "out.html"), "--sync-result", str(tmp_path / "result.json")])
    assert "--sync-result" in str(failure.value)
