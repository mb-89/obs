"""Report settings: the packaged cfg.json, optionally merged with one override file."""
from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from jsonschema import Draft202012Validator


DEFAULT_CONFIG = Path(str(files("obs_html").joinpath("cfg.json")))
SCHEMA_PATH = Path(str(files("obs_html").joinpath("cfg.schema.json")))


class ConfigError(ValueError):
    """Raised when report settings are invalid."""


@dataclass(frozen=True)
class Config:
    command_timeout_seconds: int
    rendered_check_timeout_seconds: int
    print_default: dict[str, str]
    paper_sizes: dict[str, dict[str, float]]
    report: dict[str, object]


def load_config(override_path: Path | None = None) -> Config:
    config = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    if override_path is not None:
        try:
            override = json.loads(override_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ConfigError(f"Cannot read settings {override_path}: {error}") from error
        if not isinstance(override, dict):
            raise ConfigError(f"Settings {override_path} must be a JSON object.")
        config = _merge(config, override)
    error = next(_validator().iter_errors(config), None)
    if error is not None:
        location = ".".join(str(part) for part in error.absolute_path) or "settings"
        raise ConfigError(f"Invalid {location}: {error.message}")
    report = config["report"]
    return Config(
        command_timeout_seconds=config["execution"]["commandTimeoutSeconds"],
        rendered_check_timeout_seconds=config["execution"]["renderedCheckTimeoutSeconds"],
        print_default=report["print"]["default"],
        paper_sizes=report["print"]["paperSizes"],
        report={key: value for key, value in report.items() if key != "print"},
    )


def paper(choice: dict[str, str], config: Config) -> dict[str, float]:
    """Resolve a paper and margin choice to physical paper geometry."""
    if choice["paper"] not in config.paper_sizes:
        raise ConfigError(
            f"Print paper must be one of {', '.join(config.paper_sizes)}; got {choice['paper']!r}."
        )
    margin = float(choice["margin"].removesuffix("mm"))
    geometry = {**config.paper_sizes[choice["paper"]], "marginMillimeters": margin}
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    error = next(Draft202012Validator(schema["$defs"]["paper"]).iter_errors(geometry), None)
    if error is not None:
        raise ConfigError(f"Print margin {choice['margin']} is out of range: {error.message}.")
    return geometry


def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def _merge(defaults: dict[str, object], overrides: dict[str, object]) -> dict[str, object]:
    merged = dict(defaults)
    for key, value in overrides.items():
        default = merged.get(key)
        if isinstance(default, dict) and isinstance(value, dict):
            merged[key] = _merge(default, value)
        else:
            merged[key] = value
    return merged
