"""A vault-file adapter option: the call names a file inside the vault, the core resolves it.

Owner: spec/design_input/cli.md ("Adapter options"). Errors are matched by their field path and
owner reference (AGENTS.md), never by wording.
"""
import json
import os
from pathlib import Path

import pytest

from obs.adapter import ADAPTER_OPTIONS_OWNER
from obs.document import main
from test_document_contract import recording_adapter
from test_document_sources import source_vault

DECLARED = {"bundle": {"type": "vault-file", "summary": "A file of the vault."}}


def _call(tmp_path: Path, vault: Path, *option: str, document: Path | None = None) -> list[str]:
    """The arguments the recording adapter received from a one-call build of ``vault``."""
    (tmp_path / "adapter").mkdir(exist_ok=True)
    configuration = recording_adapter(tmp_path / "adapter", options=DECLARED)
    out = tmp_path / "out.json"
    assert main(["--source", str(vault / "manifest.md"), "--adapter", "fixture", "--adapter-config",
                 str(configuration), "--destination", str(out), *option,
                 *(["--document", str(document), "--embed-source"] if document else [])]) == 0
    return json.loads(out.read_text(encoding="utf-8"))["arguments"]


def _refused(tmp_path: Path, vault: Path, option: str) -> str:
    (tmp_path / "adapter").mkdir(exist_ok=True)
    configuration = recording_adapter(tmp_path / "adapter", options=DECLARED)
    with pytest.raises(SystemExit) as failure:
        main(["--source", str(vault / "manifest.md"), "--adapter", "fixture", "--adapter-config",
              str(configuration), "--destination", str(tmp_path / "out.json"), "--adapter-option", option])
    assert not (tmp_path / "out.json").exists()
    return str(failure.value.code)


def test_a_vault_file_option_passes_the_resolved_file_inside_the_vault(tmp_path) -> None:
    vault = source_vault(tmp_path)

    arguments = _call(tmp_path, vault, "--adapter-option", "bundle=app-v1=scripts/produce.py")

    at = arguments.index("--bundle")
    assert arguments[at + 1] == f"app-v1={(vault / 'scripts' / 'produce.py').resolve()}"


def test_the_build_record_names_the_vault_file_by_its_vault_path_and_the_archive_holds_it(tmp_path) -> None:
    vault = source_vault(tmp_path)
    (vault / ".obsidian" / "app.js").write_text("globalThis.app = 1;\n", encoding="utf-8")
    kept = tmp_path / "document.json"

    _call(tmp_path, vault, "--adapter-option", "bundle=app-v1=./scripts/../.obsidian/app.js", document=kept)

    archive = json.loads(kept.read_text(encoding="utf-8"))["sourceArchive"]
    assert archive["build"]["arguments"][4:6] == ["--adapter-option", "bundle=app-v1=.obsidian/app.js"]
    assert ".obsidian/app.js" in {item["path"] for item in archive["files"]}
    assert ".obsidian/workspace.json" not in {item["path"] for item in archive["files"]}
    assert str(tmp_path) not in json.dumps(archive["build"])


@pytest.mark.parametrize("value", ["app-v1", "app-v1=", "Bad=scripts/produce.py", "=scripts/produce.py"])
def test_a_vault_file_option_without_the_form_id_path_names_the_option_and_its_owner(tmp_path, value) -> None:
    message = _refused(tmp_path, source_vault(tmp_path), f"bundle={value}")

    assert "--adapter-option" in message and "bundle" in message and ADAPTER_OPTIONS_OWNER in message


@pytest.mark.parametrize("path", ["missing.js", "scripts", "../outside.js", "link.js"])
def test_a_vault_file_option_naming_no_regular_file_inside_the_vault_names_it_and_the_owner(tmp_path, path) -> None:
    vault = source_vault(tmp_path)
    (tmp_path / "outside.js").write_text("1;\n", encoding="utf-8")
    os.symlink(tmp_path / "outside.js", vault / "link.js")

    message = _refused(tmp_path, vault, f"bundle=app-v1={path}")

    assert "--adapter-option" in message and path in message and str(vault) in message
    assert ADAPTER_OPTIONS_OWNER in message


def test_a_vault_file_option_needs_a_build_from_source(tmp_path) -> None:
    from obs.document import write_document
    from test_document_contract import document_fixture
    from test_vault import capability_reference

    document = tmp_path / "document.json"
    write_document(document_fixture(), document, capability_reference())
    configuration = recording_adapter(tmp_path, options=DECLARED)

    with pytest.raises(SystemExit) as failure:
        main(["--document", str(document), "--adapter", "fixture", "--adapter-config", str(configuration),
              "--destination", str(tmp_path / "out.json"), "--adapter-option", "bundle=app-v1=app.js"])

    message = str(failure.value.code)
    assert "--adapter-option" in message and "--source" in message and ADAPTER_OPTIONS_OWNER in message


def test_each_source_resolves_the_vault_file_inside_its_own_vault(tmp_path) -> None:
    first, second = source_vault(tmp_path / "a"), source_vault(tmp_path / "b")
    (tmp_path / "adapter").mkdir()
    configuration = recording_adapter(tmp_path / "adapter", options=DECLARED)
    assert main(["--source", str(first / "manifest.md"), "--destination", str(tmp_path / "1.json"),
                 "--source", str(second / "manifest.md"), "--destination", str(tmp_path / "2.json"),
                 "--adapter", "fixture", "--adapter-config", str(configuration),
                 "--adapter-option", "bundle=app-v1=data.csv"]) == 0

    for vault, out in ((first, tmp_path / "1.json"), (second, tmp_path / "2.json")):
        arguments = json.loads(out.read_text(encoding="utf-8"))["arguments"]
        assert arguments[arguments.index("--bundle") + 1] == f"app-v1={(vault / 'data.csv').resolve()}"
