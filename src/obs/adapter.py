"""Discover adapter manifests without binding the contract to a runtime."""
import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

from obs.input import input_error


ADAPTER_SCHEMA_PATH = Path(__file__).with_name("adapter.schema.json")
ADAPTER_OPTIONS_OWNER = "spec/design_input/cli.md (Adapter options)"
_ID = re.compile(r"[a-z][a-z0-9-]*")


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
        error = best_match(_manifest_validator().iter_errors(manifest))
        if error is not None:
            raise error
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise AdapterError(f"Invalid adapter manifest {manifest_path}: {error}") from error
    if manifest["name"] != name:
        raise AdapterError(f"Adapter manifest {manifest_path} declares {manifest['name']!r}, not {name!r}.")
    return manifest


@cache
def _manifest_validator() -> Draft202012Validator:
    """adapter.schema.json's validator, checked against its meta-schema and compiled once per process."""
    schema = json.loads(ADAPTER_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@dataclass(frozen=True)
class VaultFile:
    """A vault-file option as the call gave it: ``--adapter-option NAME=ID=PATH``, PATH relative to
    the vault, which only a build from --source resolves (``resolved``)."""
    option: str
    name: str
    id: str
    path: str

    def resolved(self, vault: Path) -> tuple[list[str], str]:
        """The adapter's arguments, ``--NAME ID=<file>``, and the file's vault-relative POSIX path, for
        the build record and the source archive; a path that names no regular file inside ``vault``
        (missing, a folder, a link, or outside it) fails."""
        root = vault.resolve()
        path = root / self.path
        file = path.resolve()
        if path.is_symlink() or not file.is_file() or not file.is_relative_to(root):
            raise AdapterError(
                f"--adapter-option {self.option!r}: {self.path} is no regular file inside the vault {root}, "
                f"but a link, a folder, missing or outside it. Name a file below the manifest's folder by its "
                f"path relative to that folder; see {ADAPTER_OPTIONS_OWNER}.")
        return [f"--{self.name}", f"{self.id}={file}"], file.relative_to(root).as_posix()


def option_arguments(manifest: dict[str, object], manifest_path: Path, given: list[str]) -> list[str | VaultFile]:
    """The adapter's arguments for the ``given`` NAME=VALUE options, as its manifest declares them:
    a boolean option is ``--NAME`` when true and left out when false; a vault-file option, its value
    ID=PATH, stays a ``VaultFile`` until a build resolves it inside its vault. An option its manifest
    does not declare ``repeats`` fails when given twice."""
    declared = manifest.get("options", {})
    owner = f"adapter {manifest['name']!r} ({manifest_path})"
    arguments, first = [], {}
    for option in given:
        name, separator, value = option.partition("=")
        if name not in declared:
            raise AdapterError(
                f"--adapter-option {option!r}: {owner} declares no option {name!r}; it declares: "
                f"{', '.join(sorted(declared)) or 'none'}. Give a declared option, or drop it.")
        if name in first and not declared[name].get("repeats", False):
            raise input_error("--adapter-option", name, f"is given twice, as {first[name]!r} and {option!r}, but "
                              f"{owner} declares it single-valued", f"Give {name} once; see {ADAPTER_OPTIONS_OWNER}")
        first.setdefault(name, option)
        if declared[name]["type"] == "vault-file":
            file_id, has_path, path = value.partition("=")
            if not _ID.fullmatch(file_id) or not has_path or not path:
                raise AdapterError(f"--adapter-option {option!r}: option {name!r} of {owner} names a vault file. "
                                   f"Write {name}=ID=PATH, ID of lowercase letters, digits and hyphens, PATH "
                                   f"relative to the vault; see {ADAPTER_OPTIONS_OWNER}.")
            arguments.append(VaultFile(option, name, file_id, path))
            continue
        if not separator or value not in {"true", "false"}:
            raise AdapterError(f"--adapter-option {option!r}: option {name!r} of {owner} is boolean. "
                               f"Write {name}=true or {name}=false.")
        if value == "true":
            arguments.append(f"--{name}")
    return arguments
