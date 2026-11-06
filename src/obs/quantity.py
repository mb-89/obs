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
