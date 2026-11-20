"""An adapter option given twice: refused unless the adapter declares that it repeats.

Owner: spec/design_input/cli.md ("Adapter options"). Errors are matched by their field path and
owner reference (AGENTS.md), never by wording.
"""
import json
from pathlib import Path

import pytest

from obs.adapter import ADAPTER_OPTIONS_OWNER
from obs.document import main
from test_document_contract import recording_adapter
from test_document_sources import source_vault

DECLARED = {
    "embed-attachments": {"type": "boolean", "summary": "A single-valued switch."},
    "bundle": {"type": "vault-file", "summary": "A single file of the vault."},
    "extra": {"type": "vault-file", "summary": "Files of the vault.", "repeats": True},
}


def _main(tmp_path: Path, *options: str) -> list[str]:
    vault = source_vault(tmp_path)
    (tmp_path / "adapter").mkdir(exist_ok=True)
    configuration = recording_adapter(tmp_path / "adapter", options=DECLARED)
    return ["--source", str(vault / "manifest.md"), "--adapter", "fixture", "--adapter-config",
            str(configuration), "--destination", str(tmp_path / "out.json"),
            *(item for option in options for item in ("--adapter-option", option))]


def _refused(tmp_path: Path, *options: str) -> str:
    with pytest.raises(SystemExit) as failure:
        main(_main(tmp_path, *options))
    assert not (tmp_path / "out.json").exists()  # Refused before the adapter runs.
    return str(failure.value.code)


def test_a_boolean_option_given_twice_is_refused_naming_both_values(tmp_path) -> None:
    message = _refused(tmp_path, "embed-attachments=true", "embed-attachments=false")

    assert "--adapter-option: embed-attachments:" in message and ADAPTER_OPTIONS_OWNER in message
    assert "embed-attachments=true" in message and "embed-attachments=false" in message


def test_a_vault_file_option_given_twice_is_refused_naming_both_values_as_given(tmp_path) -> None:
    message = _refused(tmp_path, "bundle=app-v1=scripts/produce.py", "bundle=app-v2=./scripts/produce.py")

    assert "--adapter-option: bundle:" in message and ADAPTER_OPTIONS_OWNER in message
    assert "bundle=app-v1=scripts/produce.py" in message and "bundle=app-v2=./scripts/produce.py" in message


def test_an_option_declared_as_repeating_passes_every_value(tmp_path) -> None:
    assert main(_main(tmp_path, "extra=one=scripts/produce.py", "extra=two=scripts/produce.py")) == 0

    arguments = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))["arguments"]
    assert [item.partition("=")[0] for item in arguments if item.startswith(("one=", "two="))] == ["one", "two"]
