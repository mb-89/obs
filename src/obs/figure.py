"""Validate the language-neutral FigureDescriptor contract."""
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from obs.input import schema_error


FIGURE_SCHEMA_PATH = Path(__file__).with_name("figure.schema.json")


class FigureDescriptorError(ValueError):
    """Raised when a FigureDescriptor violates the neutral contract."""


def validate_figure_descriptor(
    descriptor: dict[str, object], source: object = "FigureDescriptor", place: str = "",
) -> None:
    schema = json.loads(FIGURE_SCHEMA_PATH.read_text(encoding="utf-8"))
    error = schema_error(list(Draft202012Validator(schema).iter_errors(descriptor)), source,
                         "capabilities/figure-descriptor", place=place)
    if error:
        raise FigureDescriptorError(str(error))


def read_figure_descriptor(path: Path) -> dict[str, object]:
    try:
        descriptor = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FigureDescriptorError(f"Invalid FigureDescriptor {path}: {error}") from error
    if not isinstance(descriptor, dict):
        raise FigureDescriptorError(f"Invalid FigureDescriptor {path}.")
    validate_figure_descriptor(descriptor, path)
    return descriptor


def write_figure_descriptor(descriptor: dict[str, object], path: Path) -> None:
    validate_figure_descriptor(descriptor, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(descriptor, indent=2) + "\n", encoding="utf-8")
