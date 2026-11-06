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
DEFAULT_FIGURE_LABELS: tuple[str, ...] = tuple(
    _SCHEMA["properties"]["input"]["properties"]["figureReferences"]["properties"]["labels"]["default"]
)
"""The typed-figure-number labels of a build without core configuration; the schema owns them."""
_LONG_PARAGRAPHS = _SCHEMA["properties"]["input"]["properties"]["longParagraphs"]["properties"]
DEFAULT_LONG_PARAGRAPHS: tuple[int, int] = (
    _LONG_PARAGRAPHS["warningLines"]["default"], _LONG_PARAGRAPHS["lineCharacters"]["default"])
"""The long-paragraph lint's line limit and line width where core configuration names none; the
schema owns them."""


class CoreConfigError(ValueError):
    """Raised when core configuration cannot be read or validated."""


@dataclass(frozen=True)
class CoreConfig:
    manifest_filename: str
    project_config_filename: str
    command_timeout_seconds: int
    css_snippet_folder: str = DEFAULT_CSS_SNIPPET_FOLDER
    figure_labels: tuple[str, ...] = DEFAULT_FIGURE_LABELS
    long_paragraphs: tuple[int, int] = DEFAULT_LONG_PARAGRAPHS
    """The long-paragraph lint's warningLines and lineCharacters."""


def load_core_config(path: Path) -> CoreConfig:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CoreConfigError(f"Invalid core configuration: {path}: {error}") from error
    errors = list(Draft202012Validator(_SCHEMA).iter_errors(value))
    if errors:
        error = errors[0]
        field = ".".join(str(part) for part in error.absolute_path) or "(root)"
        raise CoreConfigError(f"Invalid core configuration: {path}: {field}: {error.message}; "
                              "see the core's config.schema.json")
    return CoreConfig(
        manifest_filename=value["input"]["manifestFilename"],
        project_config_filename=value["input"]["projectConfigFilename"],
        command_timeout_seconds=value["execution"]["commandTimeoutSeconds"],
        css_snippet_folder=value["input"].get("cssSnippetFolder", DEFAULT_CSS_SNIPPET_FOLDER),
        figure_labels=tuple(value["input"].get("figureReferences", {}).get("labels", DEFAULT_FIGURE_LABELS)),
        long_paragraphs=(value["input"].get("longParagraphs", {}).get("warningLines", DEFAULT_LONG_PARAGRAPHS[0]),
                         value["input"].get("longParagraphs", {}).get("lineCharacters", DEFAULT_LONG_PARAGRAPHS[1])),
    )
