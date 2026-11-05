"""Validate the language-neutral FigureDescriptor contract."""
import json
from pathlib import Path

from jsonschema import validate
from jsonschema.exceptions import ValidationError


FIGURE_SCHEMA_PATH = Path(__file__).with_name("figure.schema.json")


class FigureDescriptorError(ValueError):
    """Raised when a FigureDescriptor violates the neutral contract."""


def validate_figure_descriptor(descriptor: dict[str, object]) -> None:
    schema = json.loads(FIGURE_SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        validate(descriptor, schema)
    except (ValidationError, ValueError) as error:
        raise FigureDescriptorError(f"Invalid FigureDescriptor: {error}") from error


def read_figure_descriptor(path: Path) -> dict[str, object]:
    try:
        descriptor = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FigureDescriptorError(f"Invalid FigureDescriptor {path}: {error}") from error
    if not isinstance(descriptor, dict):
        raise FigureDescriptorError(f"Invalid FigureDescriptor {path}.")
    validate_figure_descriptor(descriptor)
    return descriptor


def write_figure_descriptor(descriptor: dict[str, object], path: Path) -> None:
    validate_figure_descriptor(descriptor)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(descriptor, indent=2) + "\n", encoding="utf-8")
