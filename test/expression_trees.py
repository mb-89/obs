"""Expression trees (document.schema.json, $defs/expression) as SymPy expressions and as values.

Reader: a test that checks an equation figure's trees. A derivative node of order k becomes the
symbol ``d<k>_<name>``; ``evaluate`` is the trees' complex arithmetic with principal branches,
where a piecewise case's ``eq`` holds within the relative tolerance.
"""
from __future__ import annotations

import cmath
import math

import sympy


TOLERANCE = 1e-9
"""Relative: an imaginary part this small vanishes, and an ``eq`` relation holds within it."""

_RELATIONS = {"eq": sympy.Eq, "ne": sympy.Ne, "lt": sympy.Lt, "le": sympy.Le, "gt": sympy.Gt, "ge": sympy.Ge}
_SYMPY = {
    "add": sympy.Add, "mul": sympy.Mul, "pow": sympy.Pow, "exp": sympy.exp, "log": sympy.log,
    "sin": sympy.sin, "cos": sympy.cos, "tan": sympy.tan, "asin": sympy.asin, "acos": sympy.acos,
    "atan": sympy.atan, "atan2": sympy.atan2, "sinh": sympy.sinh, "cosh": sympy.cosh, "tanh": sympy.tanh,
    "abs": sympy.Abs, "sign": sympy.sign, "min": sympy.Min, "max": sympy.Max, "heaviside": sympy.Heaviside,
}


def sympy_expression(tree: dict) -> sympy.Expr:
    if "number" in tree:
        number = tree["number"]
        return sympy.Integer(number) if float(number).is_integer() else sympy.Float(number, 17)
    if "symbol" in tree:
        return sympy.Symbol(tree["symbol"])
    if "derivative" in tree:
        return sympy.Symbol(f"d{tree['order']}_{tree['derivative']}")
    if "constant" in tree:
        return sympy.I
    if "piecewise" in tree:
        return sympy.Piecewise(*((sympy_expression(case["value"]), sympy_condition(case["when"]) if "when" in case
                                  else True) for case in tree["piecewise"]))
    return _SYMPY[tree["op"]](*map(sympy_expression, tree["args"]))


def sympy_condition(condition: dict) -> sympy.Basic:
    if "relation" in condition:
        return _RELATIONS[condition["relation"]](*map(sympy_expression, condition["args"]))
    if "not" in condition:
        return sympy.Not(sympy_condition(condition["not"]))
    return (sympy.And if "all" in condition else sympy.Or)(*map(sympy_condition, next(iter(condition.values()))))


def _real(value: complex) -> float:
    if value.imag != 0:
        raise ValueError(f"{value} is not real")
    return value.real


_COMPLEX = {
    "exp": cmath.exp, "log": cmath.log, "sin": cmath.sin, "cos": cmath.cos, "tan": cmath.tan,
    "asin": cmath.asin, "acos": cmath.acos, "atan": cmath.atan, "sinh": cmath.sinh, "cosh": cmath.cosh,
    "tanh": cmath.tanh, "abs": abs,
    "sign": lambda value: 0 if value == 0 else value / abs(value),
    "atan2": lambda y, x: math.atan2(_real(y), _real(x)),
    "min": lambda *values: min(values, key=_real), "max": lambda *values: max(values, key=_real),
    "heaviside": lambda value, at_zero=0.5: _real(at_zero) if _real(value) == 0 else float(_real(value) > 0),
}


def _value(tree: dict, values: dict[str, float], derivatives: dict) -> complex:
    if "number" in tree:
        return complex(tree["number"])
    if "symbol" in tree:
        return complex(values[tree["symbol"]])
    if "derivative" in tree:
        return complex(derivatives[(tree["derivative"], tree["order"])])
    if "constant" in tree:
        return 1j
    if "piecewise" in tree:
        for case in tree["piecewise"]:
            holds = _holds(case["when"], values, derivatives) if "when" in case else True
            if holds is None:
                break
            if holds:
                return _value(case["value"], values, derivatives)
        return complex(math.nan, math.nan)
    args = [_value(arg, values, derivatives) for arg in tree["args"]]
    if tree["op"] == "add":
        return sum(args, 0j)
    if tree["op"] == "mul":
        return math.prod(args, start=1 + 0j)
    if tree["op"] == "pow":
        base, exponent = args
        return complex(0) if base == 0 and exponent.real > 0 else base ** exponent
    return complex(_COMPLEX[tree["op"]](*args))


def _holds(condition: dict, values: dict[str, float], derivatives: dict) -> bool | None:
    """Whether the condition holds; None where a relation compares a value that is not real."""
    if "relation" in condition:
        left, right = (_value(arg, values, derivatives) for arg in condition["args"])
        if any(abs(item.imag) > TOLERANCE * max(1.0, abs(item.real)) or math.isnan(item.real) for item in (left, right)):
            return None
        a, b, relation = left.real, right.real, condition["relation"]
        equal = abs(a - b) <= TOLERANCE * max(abs(a), abs(b))
        return {"eq": equal, "ne": not equal, "lt": a < b, "le": a <= b, "gt": a > b, "ge": a >= b}[relation]
    if "not" in condition:
        inner = _holds(condition["not"], values, derivatives)
        return None if inner is None else not inner
    found = [_holds(item, values, derivatives) for item in next(iter(condition.values()))]
    if None in found:
        return None
    return all(found) if "all" in condition else any(found)


def evaluate(tree: dict, values: dict[str, float], derivatives: dict | None = None,
             tolerance: float = 1e-9) -> float | None:
    """The tree's value, or None where its imaginary part does not vanish (no point)."""
    try:
        value = _value(tree, values, derivatives or {})
    except (ZeroDivisionError, OverflowError):
        return None
    if math.isnan(value.real) or math.isnan(value.imag):
        return None
    return value.real if abs(value.imag) <= tolerance * max(1.0, abs(value.real)) else None
