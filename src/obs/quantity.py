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


Operand = tuple[object, dict[str, object]]
"""A quantity in arithmetic: the note it comes from and its Document quantity."""


def add(left: Operand, right: Operand) -> dict[str, object]:
    """``left + right`` as a Document quantity in left's unit; the dimensions must agree."""
    return _combine("add", left, right)


def subtract(left: Operand, right: Operand) -> dict[str, object]:
    """``left - right`` as a Document quantity in left's unit; the dimensions must agree."""
    return _combine("subtract", left, right)


def _combine(operation: str, left: Operand, right: Operand) -> dict[str, object]:
    from obs.input import input_error  # obs.input validates units with this module.

    (left_source, left_quantity), (right_source, right_quantity) = left, right
    sources = f"{left_source} and {right_source}"
    shown = [f"{quantity.get('value')} {quantity['unit']}".strip() for quantity in (left_quantity, right_quantity)]
    if "value" not in left_quantity or "value" not in right_quantity:
        raise input_error(sources, "value", f"cannot {operation} a count without a value",
                          "Combine quantities that have a value; see capabilities/quantities")
    if left_quantity["dimension"] != right_quantity["dimension"]:
        raise input_error(sources, "unit", f"cannot {operation} {shown[0]} and {shown[1]}: their dimensions "
                          f"{shown_dimension(left_quantity['dimension'])} and {shown_dimension(right_quantity['dimension'])} differ",
                          "Combine only quantities of one dimension, or correct the unit of one note; "
                          "see capabilities/quantities")
    quantities = [_registry().Quantity(quantity["value"], parse_unit(quantity["unit"]))
                  for quantity in (left_quantity, right_quantity)]
    try:
        result = quantities[0] + quantities[1] if operation == "add" else quantities[0] - quantities[1]
    except pint.PintError as error:
        raise input_error(sources, "unit", f"cannot {operation} {shown[0]} and {shown[1]} ({str(error).rstrip('.')})",
                          "Write such quantities in an absolute unit, such as K for a temperature; "
                          "see capabilities/quantities") from error
    value = float(f"{result.to(parse_unit(left_quantity['unit'])).magnitude:.15g}")
    return document_quantity({"value": value, "unit": left_quantity["unit"]})


def shown_dimension(dimension: dict[str, int | float]) -> str:
    """A dimension for a message, such as length*time^-1; a plain number is dimensionless."""
    return "*".join(name if power == 1 else f"{name}^{power}" for name, power in dimension.items()) \
        or "dimensionless"
