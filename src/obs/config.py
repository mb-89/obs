"""Load the output-neutral portion of cross-cutting configuration."""
from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
import json
from pathlib import Path

from jsonschema import Draft202012Validator


_SCHEMA = json.loads(files("obs").joinpath("config.schema.json").read_text(encoding="utf-8"))
DEFAULT_COMMAND_TIMEOUT_SECONDS: int = (
    _SCHEMA["properties"]["execution"]["properties"]["commandTimeoutSeconds"]["default"]
)
"""The cmd fence timeout of a build without core configuration; the schema owns the value."""
DEFAULT_CSS_SNIPPET_FOLDER: str = _SCHEMA["properties"]["input"]["properties"]["cssSnippetFolder"]["default"]
"""The vault's CSS snippet folder where core configuration names none; the schema owns the value."""


class CoreConfigError(ValueError):
    """Raised when core configuration cannot be read or validated."""


@dataclass(frozen=True)
class CoreConfig:
    manifest_filename: str
    project_config_filename: str
    command_timeout_seconds: int
    css_snippet_folder: str = DEFAULT_CSS_SNIPPET_FOLDER


def load_core_config(path: Path) -> CoreConfig:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CoreConfigError(f"Invalid core configuration: {path}: {error}") from error
    errors = list(Draft202012Validator(_SCHEMA).iter_errors(value))
    if errors:
        raise CoreConfigError(f"Invalid core configuration: {errors[0].message}")
    return CoreConfig(
        manifest_filename=value["input"]["manifestFilename"],
        project_config_filename=value["input"]["projectConfigFilename"],
        command_timeout_seconds=value["execution"]["commandTimeoutSeconds"],
        css_snippet_folder=value["input"].get("cssSnippetFolder", DEFAULT_CSS_SNIPPET_FOLDER),
    )
