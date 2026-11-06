"""Discover adapter manifests without binding the contract to a runtime."""
import json
from pathlib import Path

from jsonschema import validate


ADAPTER_SCHEMA_PATH = Path(__file__).with_name("adapter.schema.json")


class AdapterError(ValueError):
    """Raised when adapter configuration or a manifest violates the contract."""


def adapter_manifest_path(name: str, configuration_path: Path) -> Path:
    """The manifest file the adapter configuration registers for ``name``."""
    try:
        configuration = json.loads(configuration_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AdapterError(f"Cannot read adapter configuration {configuration_path}: {error}. Run from the "
                           f"folder that holds it, or name it with --adapter-config.") from error
    adapters = configuration.get("adapters") if isinstance(configuration, dict) else None
    manifest_name = adapters.get(name) if isinstance(adapters, dict) else None
    if not isinstance(manifest_name, str) or not manifest_name:
        raise AdapterError(f"Adapter {name!r} is not configured.")
    return configuration_path.parent / manifest_name


def load_adapter(name: str, configuration_path: Path) -> dict[str, object]:
    manifest_path = adapter_manifest_path(name, configuration_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        schema = json.loads(ADAPTER_SCHEMA_PATH.read_text(encoding="utf-8"))
        validate(manifest, schema)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise AdapterError(f"Invalid adapter manifest {manifest_path}: {error}") from error
    if manifest["name"] != name:
        raise AdapterError(f"Adapter manifest {manifest_path} declares {manifest['name']!r}, not {name!r}.")
    return manifest


def option_arguments(manifest: dict[str, object], manifest_path: Path, given: list[str]) -> list[str]:
    """The adapter's arguments for the ``given`` NAME=VALUE options, as its manifest declares them:
    a boolean option is ``--NAME`` when true and left out when false."""
    declared = manifest.get("options", {})
    owner = f"adapter {manifest['name']!r} ({manifest_path})"
    arguments = []
    for option in given:
        name, separator, value = option.partition("=")
        if name not in declared:
            raise AdapterError(
                f"--adapter-option {option!r}: {owner} declares no option {name!r}; it declares: "
                f"{', '.join(sorted(declared)) or 'none'}. Give a declared option, or drop it.")
        if not separator or value not in {"true", "false"}:
            raise AdapterError(f"--adapter-option {option!r}: option {name!r} of {owner} is boolean. "
                               f"Write {name}=true or {name}=false.")
        if value == "true":
            arguments.append(f"--{name}")
    return arguments
