from __future__ import annotations

from dataclasses import dataclass, replace
from importlib import import_module
from importlib.resources import files
from pkgutil import iter_modules
from types import ModuleType
from typing import Callable


@dataclass(frozen=True)
class BarDefinition:
    key: str
    label: str
    icon: str
    help: str
    order: int
    render: Callable[[], str]
    script: str = ""
    header_actions: str = ""


def discover_bars(package_name: str = __name__) -> tuple[BarDefinition, ...]:
    package = import_module(package_name)
    definitions = tuple(
        _load_definition(import_module(f"{package_name}.{module.name}"))
        for module in iter_modules(package.__path__)
        if not module.name.startswith("_")
    )
    ordered = tuple(sorted(definitions, key=lambda item: (item.order, item.key)))
    keys = [definition.key for definition in ordered]
    if len(keys) != len(set(keys)):
        raise ValueError(f"Dock bar keys must be unique: {keys}")
    return ordered


def _load_definition(module: ModuleType) -> BarDefinition:
    definition = getattr(module, "BAR", None)
    if not isinstance(definition, BarDefinition):
        raise TypeError(f"{module.__name__} must export one BarDefinition named BAR.")
    if not all((definition.key, definition.label, definition.icon, definition.help)):
        raise ValueError(f"{module.__name__} has incomplete dock bar metadata.")
    package, _, name = module.__name__.rpartition(".")
    runtime = files(package).joinpath(f"{name}.js")
    if definition.script:
        raise TypeError(f"{module.__name__} must keep its browser runtime in {name}.js, not a Python string.")
    return replace(definition, script=runtime.read_text(encoding="utf-8")) if runtime.is_file() else definition
