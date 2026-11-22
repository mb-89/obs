"""Discover adapter manifests without binding the contract to a runtime, and name the components a
build uses (spec/design_input/components.md, Recording what built a page)."""
import json
import re
import subprocess
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

from obs import components
from obs.input import input_error


ADAPTER_SCHEMA_PATH = Path(__file__).with_name("adapter.schema.json")
ADAPTER_OPTIONS_OWNER = "spec/design_input/cli.md (Adapter options)"
_ID = re.compile(r"[a-z][a-z0-9-]*")


class AdapterError(ValueError):
    """Raised when adapter configuration or a manifest violates the contract."""


@dataclass(frozen=True)
class AdapterLocation:
    """Where an adapter component lies: its manifest, and the folder its commands run from."""
    manifest: Path
    folder: Path


TREE_ADAPTERS = {"html": Path("adapters") / "html" / "adapter.json"}
"""The adapters that still live in obs's tree, each found as the component of its name where none is
installed (spec/design_input/components.md, Naming a component)."""


def adapter_location(name: str) -> AdapterLocation:
    """The installed adapter component ``name``, else the one of obs's tree; any other fails naming the
    remedy, to install it."""
    entry = components.installed().get(name)
    if entry is not None:
        if entry["kind"] != "adapter":
            raise AdapterError(f"--adapter: {name}: the installed component {name!r} is a {entry['kind']}, not an adapter. "
                               f"Name an installed adapter; see {components.OWNER} (Naming a component).")
        folder = components.local_folder() / "components" / name
        return AdapterLocation(folder / "adapter.json", folder)
    tree = TREE_ADAPTERS.get(name)
    if tree is not None and (components.CHECKOUT / tree).is_file():
        return AdapterLocation(components.CHECKOUT / tree, components.CHECKOUT)
    raise AdapterError(f"--adapter: {name}: no adapter component {name!r} is installed. Run obs-components install {name}; "
                       f"see {components.OWNER} (Naming a component).")


def component_record(name: str) -> dict[str, str] | None:
    """The component ``name`` a build uses, as its record names it: the installed one as components.json
    lists it, else the adapter of obs's tree at obs's version and commit; None where neither is there."""
    entry = components.installed().get(name)
    if entry is not None:
        return entry
    if name not in TREE_ADAPTERS or not (components.CHECKOUT / TREE_ADAPTERS[name]).is_file():
        return None
    project = tomllib.loads((components.CHECKOUT / "se.toml").read_text(encoding="utf-8"))["project"]
    try:
        head = subprocess.run(["git", "-C", str(components.CHECKOUT), "rev-parse", "HEAD"], capture_output=True,
                              text=True, encoding="utf-8", check=False)
    except OSError:
        head = None
    commit = head.stdout.strip() if head is not None and not head.returncode else ""
    return {"name": name, "kind": "adapter", "version": str(project["version"]),
            "commit": commit if re.fullmatch(r"[0-9a-f]{40}", commit) else "unknown"}


RECORDED = "--recorded-components"


def check_recorded(path: Path, warn: Callable[[str], None]) -> None:
    """Hold the installed components against the record ``path`` lists: another version warns naming
    the component and both versions; a component that is absent, or of another kind, fails."""
    remedy = f"see {components.OWNER} (Recording what built a page)"
    source = f"{RECORDED} {path}"
    try:
        recorded = json.loads(path.read_text(encoding="utf-8")).get("components")
    except (OSError, ValueError, AttributeError) as error:
        raise input_error(source, "components", f"cannot be read ({error})",
                          f"Name a source archive's build-config.json; {remedy}") from error
    if not isinstance(recorded, list):
        raise input_error(source, "components", "is no list of the components a build recorded",
                          f"Name a source archive's build-config.json; {remedy}")
    keys = ("name", "kind", "version", "commit")
    for index, entry in enumerate(recorded):
        if not isinstance(entry, dict) or not all(isinstance(entry.get(key), str) for key in keys):
            raise input_error(source, f"components[{index}]", f"is {entry!r}, not a component's {', '.join(keys)}",
                              f"Name a source archive's build-config.json; {remedy}")
    for index, entry in enumerate(recorded):
        field, name = f"components[{index}]", entry["name"]
        found = component_record(name)
        if found is None or found["kind"] != entry["kind"]:
            problem = (f"no {entry['kind']} component {name!r} is installed" if found is None
                       else f"the component {name!r} is installed as a {found['kind']}, not a {entry['kind']}")
            raise input_error(source, field, f"{problem}, but the recorded build used it",
                              f"Run obs-components install {name}; see {components.OWNER} (Naming a component)")
        if found["version"] != entry["version"]:
            warn(f"{source}: {field}: the {entry['kind']} component {name!r} is installed at "
                 f"{found['version']}, but the recorded build used {entry['version']}; the rebuild uses "
                 f"{found['version']}, {remedy}.")


def load_adapter(name: str) -> dict[str, object]:
    manifest_path = adapter_location(name).manifest
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
