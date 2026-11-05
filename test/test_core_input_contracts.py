import json
import subprocess
import sys

import pytest

from obs.config import CoreConfigError, load_core_config
from obs.input import InputError, parse_card_spec, parse_callout, parse_property_editor, validate_command


def test_core_input_contracts_validate_without_loading_adapter(tmp_path) -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import obs.input; import sys; raise SystemExit('obs_html' in sys.modules)"],
        check=False,
    )
    assert result.returncode == 0

    config_path = tmp_path / "cfg.json"
    config_path.write_text(
        json.dumps(
            {
                "input": {
                    "manifestFilename": "manifest.md",
                    "projectConfigFilename": "project.json",
                },
                "execution": {"commandTimeoutSeconds": 5},
                "report": {"tablePageSize": 20},
            }
        ),
        encoding="utf-8",
    )

    config = load_core_config(config_path)

    assert config.manifest_filename == "manifest.md"
    assert config.project_config_filename == "project.json"
    assert config.command_timeout_seconds == 5


def test_core_input_contracts_reject_invalid_data_only_inputs(tmp_path) -> None:
    with pytest.raises(InputError, match=r"^A cmd fence cannot be empty\.$"):
        validate_command(" \t")
    with pytest.raises(InputError, match=r"^Cards: "):
        parse_card_spec('{"version": 1, "cards": []}')
    with pytest.raises(InputError, match=r"^Property editor: "):
        parse_property_editor("version: 1\nfield: title\n")
    with pytest.raises(CoreConfigError, match=r"^Invalid core configuration: "):
        load_core_config(tmp_path / "missing.json")


def test_core_input_contracts_parse_semantic_callout_and_queries() -> None:
    assert parse_callout("[!warning]- Investigate") == {
        "type": "warning",
        "tone": "warning",
        "fold": "-",
        "title": "Investigate",
    }
    assert parse_callout("[!unknown] Not a callout") is None

    spec = parse_card_spec(
        '{"version": 1, "cards": [{"title": "Coverage", "body": "", '
        '"metrics": [{"label": "Known", "where": []}]}]}'
    )
    assert spec["cards"][0]["metrics"][0]["where"] == []
