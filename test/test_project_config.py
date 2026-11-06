"""The vault's project configuration on every build: the core applies its own keys and carries the
rest unread to the adapter.

Owner: spec/design_input/architecture.md ("Project configuration"). Errors are matched by their
source, field path and owner reference (AGENTS.md), never by wording.
"""
import base64
import json
from pathlib import Path

import pytest

from obs.document import DocumentError, build_document, main
from test_document_contract import recording_adapter
from test_vault import capability_reference


OWNER = "spec/design_input/architecture.md (Project configuration)"


def project_vault(tmp_path: Path, settings: object, name: str = "vault") -> Path:
    vault = tmp_path / name
    (vault / "styles").mkdir(parents=True)
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text("# Chapter\n", encoding="utf-8")
    (vault / "styles" / "wide.css").write_text("body {}\n", encoding="utf-8")
    (vault / "cfg.json").write_text(json.dumps(settings), encoding="utf-8")
    return vault


def core_config(tmp_path: Path, **input_keys: object) -> Path:
    path = tmp_path / "core.json"
    path.write_text(json.dumps({"input": {"manifestFilename": "manifest.md", "projectConfigFilename": "cfg.json",
                                          **input_keys},
                                "execution": {"commandTimeoutSeconds": 15}}), encoding="utf-8")
    return path


def test_the_vault_s_core_keys_take_effect_without_core_configuration(tmp_path) -> None:
    vault = project_vault(tmp_path, {"schemaVersion": 1, "input": {"cssSnippetFolder": "styles"}})

    document = build_document(vault / "manifest.md", capability_reference())

    assert [snippet["path"] for snippet in document["cssSnippets"]] == ["styles/wide.css"]


def test_the_vault_s_file_overrides_the_core_configuration_key_by_key(tmp_path) -> None:
    vault = project_vault(tmp_path, {"input": {"cssSnippetFolder": "styles"}})
    (vault / "other").mkdir()
    (vault / "other" / "narrow.css").write_text("p {}\n", encoding="utf-8")

    document = build_document(vault / "manifest.md", capability_reference(),
                              core_config(tmp_path, cssSnippetFolder="other"))

    assert [snippet["path"] for snippet in document["cssSnippets"]] == ["styles/wide.css"]


def test_the_vault_s_manifest_filename_names_the_note_of_a_vault_folder(tmp_path) -> None:
    vault = project_vault(tmp_path, {"input": {"manifestFilename": "index.md"}})
    (vault / "manifest.md").rename(vault / "index.md")
    destination = tmp_path / "out.json"

    assert main(["--adapter", "fixture", "--adapter-config", str(recording_adapter(tmp_path)),
                 "--source", str(vault), "--destination", str(destination)]) == 0

    assert json.loads(destination.read_text(encoding="utf-8"))["manifest"] == "index.md"


def test_every_other_key_rides_unread_in_the_document(tmp_path) -> None:
    settings = {"$schema": "x.json", "schemaVersion": 1, "input": {"cssSnippetFolder": "styles"},
                "execution": {"commandTimeoutSeconds": 20},
                "artifact": {"filterPresets": [{"label": "Mine", "expression": "depth: /^1$/"}]},
                "anything": [1, {"unread": True}]}
    vault = project_vault(tmp_path, settings)

    document = build_document(vault / "manifest.md", capability_reference())

    assert document["projectConfig"] == {"path": "cfg.json", "settings": {
        "artifact": settings["artifact"], "anything": settings["anything"]}}


def test_a_vault_without_the_file_carries_no_project_configuration(tmp_path) -> None:
    vault = project_vault(tmp_path, {})
    (vault / "cfg.json").unlink()

    assert "projectConfig" not in build_document(vault / "manifest.md", capability_reference())


@pytest.mark.parametrize(("settings", "field"), [
    ({"input": {"styleFolder": "styles"}}, "input.styleFolder"),
    ({"execution": {"commandTimeoutSeconds": 0}}, "execution.commandTimeoutSeconds"),
    ({"schemaVersion": 2}, "schemaVersion"),
    ([], "top level"),
])
def test_an_invalid_core_key_names_the_vault_file_and_its_field(tmp_path, settings, field) -> None:
    vault = project_vault(tmp_path, settings)

    with pytest.raises(DocumentError) as refused:
        build_document(vault / "manifest.md", capability_reference())

    message = str(refused.value)
    assert message.startswith(f"{vault / 'cfg.json'}: {field}"), message
    assert "; see configuration." in message


def test_a_file_that_is_not_json_names_the_file_and_the_owner(tmp_path) -> None:
    vault = project_vault(tmp_path, {})
    (vault / "cfg.json").write_text("{", encoding="utf-8")

    with pytest.raises(DocumentError) as refused:
        build_document(vault / "manifest.md", capability_reference())

    message = str(refused.value)
    assert message.startswith(f"{vault / 'cfg.json'}: top level: "), message
    assert OWNER in message


def test_the_source_archive_holds_the_file_and_a_rebuild_from_it_applies_it(tmp_path) -> None:
    settings = {"input": {"cssSnippetFolder": "styles"}, "artifact": {"tablePageSize": 7}}
    reference = capability_reference()
    built = build_document(project_vault(tmp_path, settings) / "manifest.md", reference, embed_source=True)
    files = {entry["path"]: entry for entry in built["sourceArchive"]["files"]}
    assert json.loads(base64.b64decode(files["cfg.json"]["data"])) == settings

    rebuilt_vault = tmp_path / "rebuilt"
    assets = {asset["id"]: asset for asset in built["assets"]}
    for path, entry in files.items():
        (rebuilt_vault / path).parent.mkdir(parents=True, exist_ok=True)
        (rebuilt_vault / path).write_bytes(base64.b64decode(entry.get("data") or assets[entry["asset"]]["data"]))
    rebuilt = build_document(rebuilt_vault / "manifest.md", reference)

    assert rebuilt["projectConfig"] == built["projectConfig"]
    assert rebuilt["cssSnippets"] == built["cssSnippets"]
