"""The components that build a page: the Document and the source archive's build record carry them,
and a rebuild from a record warns on another installed version and fails on an absent component.

Owner: spec/design_input/components.md ("Recording what built a page"). Errors are matched by their
field path and owner reference (AGENTS.md), never by wording.
"""
import json
import subprocess
import tomllib
from pathlib import Path

import pytest

from obs import adapter, components
from obs.document import build_document, main
from test_document_contract import recording_adapter
from test_document_sources import source_vault
from test_vault import capability_reference


CHECKOUT = Path(__file__).resolve().parents[1]
FIXTURE = {"name": "fixture", "kind": "adapter", "version": "1.0.0", "commit": "0" * 40}
"""The recording adapter as test/installed_components.py installs it."""


def _build(tmp_path: Path, *extra: str) -> dict[str, object]:
    vault = source_vault(tmp_path)
    recording_adapter()
    kept = tmp_path / "document.json"
    assert main(["--source", str(vault / "manifest.md"), "--adapter", "fixture", "--destination",
                 str(tmp_path / "out.json"), "--document", str(kept), *extra]) == 0
    return json.loads(kept.read_text(encoding="utf-8"))


def _record(tmp_path: Path, *recorded: dict[str, str]) -> Path:
    path = tmp_path / "build-config.json"
    path.write_text(json.dumps({"components": list(recorded)}), encoding="utf-8")
    return path


def test_the_document_and_the_build_record_carry_the_adapter_component_that_built_it(tmp_path) -> None:
    document = _build(tmp_path, "--embed-source")

    assert document["components"] == [FIXTURE]
    assert document["sourceArchive"]["build"]["components"] == [FIXTURE]


def test_a_document_built_without_an_adapter_lists_no_component(tmp_path) -> None:
    document = build_document(source_vault(tmp_path) / "manifest.md", capability_reference(), embed_source=True)

    assert document["components"] == []
    assert document["sourceArchive"]["build"]["components"] == []


def test_an_html_that_is_not_installed_has_no_record() -> None:
    """obs keeps no adapter in its tree, so nothing records an html no one installed."""
    assert adapter.component_record("html") is None


def test_an_installed_html_is_recorded_as_installed(tmp_path) -> None:
    from installed_components import install_adapter
    install_adapter({"name": "html", "command": ["true"], "contractVersion": 1, "capabilities": []})

    assert adapter.component_record("html") == {"name": "html", "kind": "adapter", "version": "1.0.0",
                                                "commit": "0" * 40}


def test_a_rebuild_at_the_recorded_versions_warns_nothing(tmp_path, capsys) -> None:
    _build(tmp_path, "--recorded-components", str(_record(tmp_path, FIXTURE)))

    assert "fixture" not in capsys.readouterr().err


def test_a_rebuild_with_another_installed_version_warns_naming_the_component_and_both_versions(
        tmp_path, capsys) -> None:
    recorded = {**FIXTURE, "version": "0.9.0", "commit": "1" * 40}

    _build(tmp_path, "--recorded-components", str(_record(tmp_path, recorded)))

    warnings = [line for line in capsys.readouterr().err.splitlines() if "--recorded-components" in line]
    assert len(warnings) == 1
    assert "--recorded-components" in warnings[0] and "components[0]" in warnings[0]
    assert "fixture" in warnings[0] and "0.9.0" in warnings[0] and "1.0.0" in warnings[0]
    assert components.OWNER in warnings[0]


def test_a_rebuild_whose_recorded_component_is_absent_fails_naming_it(tmp_path) -> None:
    absent = {"name": "paper", "kind": "style", "version": "2.0.0", "commit": "2" * 40}

    with pytest.raises(SystemExit) as failed:
        _build(tmp_path, "--recorded-components", str(_record(tmp_path, FIXTURE, absent)))

    message = str(failed.value.code)
    assert "--recorded-components" in message and "components[1]" in message and "'paper'" in message
    assert f"{components.OWNER} (Naming a component)" in message
    assert not (tmp_path / "out.json").exists()


def test_a_recorded_component_of_another_kind_fails_naming_it(tmp_path) -> None:
    with pytest.raises(SystemExit) as failed:
        _build(tmp_path, "--recorded-components", str(_record(tmp_path, {**FIXTURE, "kind": "style"})))

    message = str(failed.value.code)
    assert "components[0]" in message and "'fixture'" in message and components.OWNER in message


def test_an_unreadable_record_fails_naming_the_option(tmp_path) -> None:
    broken = tmp_path / "build-config.json"
    broken.write_text('{"components": [{"name": "fixture"}]}', encoding="utf-8")

    with pytest.raises(SystemExit) as failed:
        _build(tmp_path, "--recorded-components", str(broken))

    message = str(failed.value.code)
    assert "--recorded-components" in message and "components[0]" in message and components.OWNER in message
