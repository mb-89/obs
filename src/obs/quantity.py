"""The unit system of quantity notes: parsing a display unit; see capabilities/quantities."""
from __future__ import annotations

from functools import cache

import pint


@cache
def _registry() -> pint.UnitRegistry:
    """Pint's default registry: SI, its prefixes and the common engineering units."""
    return pint.UnitRegistry()


class UnitError(ValueError):
    """A unit the unit system does not know; its message says what is wrong."""


def parse_unit(unit: str) -> pint.Unit:
    """The physical unit a display unit names, or UnitError."""
    try:
        return _registry().parse_units(unit)
    except (pint.PintError, ValueError, TypeError, AttributeError, SyntaxError) as error:
        raise UnitError(f"{unit!r} is not a known unit ({str(error).rstrip('.')})") from error


def _si(value: float, unit: str) -> float:
    """``value`` in ``unit`` as a value in SI base units, to 15 significant digits."""
    converted = _registry().Quantity(value, parse_unit(unit)).to_base_units().magnitude
    return float(f"{converted:.15g}")


def dimension(unit: str) -> dict[str, int | float]:
    """A unit's dimension: each base dimension's nonzero exponent, such as {"length": 1}."""
    return {name.strip("[]"): int(power) if float(power).is_integer() else float(power)
            for name, power in sorted(parse_unit(unit).dimensionality.items()) if power}


def document_quantity(metadata: dict[str, object]) -> dict[str, object]:
    """A validated quantity note's Document quantity; document.schema.json ($defs/quantity)."""
    unit = str(metadata.get("unit", ""))
    quantity: dict[str, object] = {"unit": unit, "dimension": dimension(unit)}
    if "value" in metadata:
        quantity["value"] = metadata["value"]
        quantity["siValue"] = _si(metadata["value"], unit)
    if "range" in metadata:
        quantity["range"] = list(metadata["range"])
        quantity["siRange"] = [_si(bound, unit) for bound in metadata["range"]]
    return quantity
