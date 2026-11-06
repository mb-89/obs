"""Equation figures: SymPy equations, their variables and the initial plot as a figure's body.

Reader: whoever changes the equations figure kind. input-model ("Equation figures") owns the
design, capabilities/equation-figures the authoring, document.schema.json the body
(``$defs/figureBodies/equations``) and the expression tree (``$defs/expression``).
"""
from __future__ import annotations

import json
import math
import re
from functools import cache
from pathlib import Path

import pint
import sympy
import yaml
from jsonschema import Draft202012Validator
from sympy.core.function import AppliedUndef
from sympy.parsing.sympy_parser import convert_equals_signs, parse_expr, standard_transformations

from obs.figure import FigureContentError, FigureContext
from obs.input import schema_error
from obs.quantity import UnitError, document_quantity, parse_unit, shown_dimension


OWNER = "capabilities/equation-figures"
SEE = f"; see {OWNER}"

OPERATORS: dict[type, str] = {
    sympy.Add: "add", sympy.Mul: "mul", sympy.Pow: "pow", sympy.exp: "exp", sympy.log: "log",
    sympy.sin: "sin", sympy.cos: "cos", sympy.tan: "tan", sympy.asin: "asin", sympy.acos: "acos",
    sympy.atan: "atan", sympy.atan2: "atan2", sympy.sinh: "sinh", sympy.cosh: "cosh", sympy.tanh: "tanh",
    sympy.Abs: "abs", sympy.sign: "sign", sympy.Min: "min", sympy.Max: "max", sympy.Heaviside: "heaviside",
}
"""SymPy's functions the expression tree has an operator for (document.schema.json, $defs/expression)."""

NAMES = {"Eq", "Derivative", "sqrt", "pi", "E", "I", "exp", "log", "sin", "cos", "tan", "asin", "acos", "atan",
         "atan2", "sinh", "cosh", "tanh", "Abs", "sign", "Min", "Max", "Heaviside"}
"""The SymPy names an equation may use besides its variables; ``.diff`` is its one method."""

_IDENTIFIER = re.compile(r"(?<![\w.])([A-Za-z_]\w*)(\s*\()?")
_METHOD = re.compile(r"\.\s*([A-Za-z_]\w*)")
_DIMENSIONLESS = (sympy.exp, sympy.log, sympy.sin, sympy.cos, sympy.tan, sympy.asin, sympy.acos, sympy.atan,
                  sympy.sinh, sympy.cosh, sympy.tanh)


def read(content: object, _media_type: str | None = None) -> dict[str, object]:
    """The authored mapping, from a YAML or JSON source file's bytes or inline; input.schema.json
    (``$defs/equationFigure``) checks it."""
    field = "source" if isinstance(content, bytes) else "content"
    if isinstance(content, bytes):
        try:
            content = yaml.safe_load(content.decode("utf-8"))
        except (UnicodeDecodeError, yaml.YAMLError) as error:
            raise FigureContentError("source", f"is not YAML or JSON: {error}", f"Write the file as YAML{SEE}") from error
    error = schema_error(list(_validator().iter_errors(content)), "", OWNER, field=field)
    if error:
        message = str(error).removeprefix(": ")
        path, _, rest = message.partition(": ")
        problem, _, remedy = rest.removesuffix(".").partition(". ")
        raise FigureContentError(path, problem, remedy)
    return content


@cache
def _validator() -> Draft202012Validator:
    schema = json.loads(Path(__file__).with_name("input.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator({"$ref": "#/$defs/equationFigure", "$defs": schema["$defs"]})


class _Figure:
    """One equation figure being resolved: its variables, their SymPy objects and dimensions."""

    def __init__(self, content: dict[str, object], context: FigureContext) -> None:
        self.content, self.context, self.field = content, context, context.field
        self.functions = {name: spec["of"] for name, spec in content["variables"].items()
                          if isinstance(spec, dict) and "of" in spec}
        self.symbols = {name: sympy.Symbol(name) for name in content["variables"]}
        self.notes: dict[str, str] = {}
        self.dimensions: dict[str, dict[str, float]] = {}

    def fail(self, field: str, problem: str, remedy: str) -> FigureContentError:
        return FigureContentError(f"{self.field}.{field}" if field else self.field, problem, remedy + SEE)

    # Variables and the range rule.

    def variables(self, unknowns: list[str]) -> dict[str, dict[str, object]]:
        result = {}
        for name, spec in self.content["variables"].items():
            spec = {"quantity": spec} if isinstance(spec, str) else spec
            if name in NAMES:
                raise self.fail(f"variables.{name}", "is a SymPy name", "Rename the variable")
            result[name] = self.variable(name, spec, name in unknowns)
            self.dimensions[name] = result[name]["quantity"]["dimension"]
        for name, of in self.functions.items():
            if of not in result or of in self.functions:
                raise self.fail(f"variables.{name}.of", f"is {of!r}, which is no variable of the figure",
                                "Name the variable the function is a function of, such as t")
            result[name]["of"] = of
        return result

    def variable(self, name: str, spec: dict[str, object], unknown: bool) -> dict[str, object]:
        field = f"variables.{name}"
        if "quantity" in spec:
            target = spec["quantity"][2:-2]
            note = self.context.quantity(target)
            if note is None:
                raise self.fail(field, f"names [[{target}]], which is no note", "Link an existing quantity note")
            path, metadata = note
            if metadata.get("kind") != "quantity":
                raise self.fail(field, f"names {path}, which is no quantity note",
                                "Link a quantity note (kind: quantity), or give the variable its own default")
            if "value" not in metadata:
                raise self.fail(field, f"names {path}, a count without a value",
                                "Link a quantity note with a value, or give the variable its own default")
            self.notes[name] = path
            unit, default, origin = metadata.get("unit", ""), metadata["value"], f"the value of {path}"
            own = metadata.get("range")
        else:
            unit, default, origin, own = spec.get("unit", ""), spec.get("default"), "the default", None
            try:
                parse_unit(unit)
            except UnitError as error:
                raise self.fail(f"{field}.unit", str(error), "Write an SI or common engineering unit, such as N*m") from error
            if default is None and not unknown:
                raise self.fail(f"{field}.default", "is missing",
                                "Give the variable a default, or list it as an unknown the equations determine")
        span = self.range(field, own, spec.get("range"), self.notes.get(name))
        if span is not None and default is not None and not span[0] <= default <= span[1]:
            where = f"{field}.default" if "quantity" not in spec else f"{field}.range"
            raise self.fail(where, f"puts {origin}, {default}, outside the range {list(span)}",
                            "Give a default inside the range, or widen the range")
        quantity = {"unit": unit}
        if default is not None:
            quantity["value"] = default
        if span is not None:
            quantity["range"] = list(span)
        return {"quantity": document_quantity(quantity), **({"note": self.notes[name]} if name in self.notes else {})}

    def range(self, field: str, note: list | None, fence: list | None, path: str | None) -> tuple | None:
        """The range rule (input-model, Equation figures): the note's and the fence's intersect."""
        if fence is not None and fence[0] > fence[1]:
            raise self.fail(f"{field}.range", f"is {fence}, whose minimum exceeds its maximum", "Write [minimum, maximum]")
        if note is None or fence is None:
            return None if note is None and fence is None else tuple(note or fence)
        span = (max(note[0], fence[0]), min(note[1], fence[1]))
        if span[0] > span[1]:
            raise self.fail(f"{field}.range", f"is {fence}, which does not overlap the range {note} of {path}",
                            f"Give a range that overlaps {path}'s, or correct the range of {path}")
        return span

    # Parsing and dimensions.

    def parse(self, text: str, field: str) -> sympy.Expr | sympy.Eq:
        where = self.context.line(text)
        located = f" ({where})" if where else ""
        for match in _IDENTIFIER.finditer(text):
            name, call = match[1], match[2]
            if name in self.symbols or name in NAMES:
                continue
            kind = "undefined function" if call else "unknown symbol"
            raise self.fail(field, f"uses the {kind} {name}{located}",
                            f"Declare {name} under variables with of, or use a function the expression tree carries" if call
                            else f"Declare {name} under variables")
        for method in _METHOD.findall(text):
            if method != "diff":
                raise self.fail(field, f"calls the method {method}{located}", "Use .diff or Derivative only")
        for name, of in self.functions.items():
            text = re.sub(rf"(?<![\w.]){name}('*)(?!\w)(?!\s*\()",
                          lambda match: f"Derivative({name}({of}), {of}, {len(match[1])})" if match[1] else f"{name}({of})",
                          text)
        names = {**self.symbols, **{name: sympy.Function(name) for name in self.functions}}
        try:
            expression = parse_expr(text, local_dict=names,
                                    transformations=standard_transformations + (convert_equals_signs,))
        except Exception as error:  # SymPy raises many kinds for text it cannot parse.
            raise self.fail(field, f"is not SymPy syntax{located}: {error}",
                            "Write the expression as SymPy writes it, such as T = k*n**2") from error
        if not isinstance(expression, sympy.Basic) or expression.is_Boolean and not isinstance(expression, sympy.Eq):
            raise self.fail(field, f"is not an expression{located}", "Write an equation, such as T = k*n**2")
        for function in expression.atoms(AppliedUndef):
            name = type(function).__name__
            if name not in self.functions or function.args != (self.symbols[self.functions[name]],):
                raise self.fail(field, f"applies {function}{located}, which is not a declared function of its variable",
                                f"Declare {name} with of, and apply it to that variable only")
        for function in expression.atoms(sympy.Function):
            if not isinstance(function, AppliedUndef) and type(function) not in OPERATORS:
                raise self.fail(field, f"uses the function {type(function).__name__}{located}, which the "
                                "expression tree has no operator for", "Use a function the expression tree carries")
        return expression

    def dimension(self, expression: sympy.Basic, field: str) -> dict[str, float]:
        """The expression's dimension; a sum or an equation of different dimensions fails naming both."""
        def of(item):
            if isinstance(item, sympy.Eq) or isinstance(item, (sympy.Add, sympy.Min, sympy.Max)):
                dimensions = [of(arg) for arg in item.args]
                for arg, found in zip(item.args[1:], dimensions[1:]):
                    if found != dimensions[0]:
                        raise self.fail(field, f"combines {self.named(item.args[0], dimensions[0])} and "
                                        f"{self.named(arg, found)}, whose dimensions differ",
                                        "Correct the equation, or the unit of one of them")
                return {} if isinstance(item, sympy.Eq) else dimensions[0]
            if item.is_Number or item in (sympy.pi, sympy.E, sympy.I):
                return {}
            if item.is_Symbol:
                return self.dimensions[item.name]
            if isinstance(item, AppliedUndef):
                return self.dimensions[type(item).__name__]
            if isinstance(item, sympy.Derivative):
                result = dict(of(item.expr))
                for variable, count in item.variable_count:
                    result = _combine(result, of(variable), -count)
                return result
            if isinstance(item, sympy.Mul):
                result = {}
                for arg in item.args:
                    result = _combine(result, of(arg), 1)
                return result
            if isinstance(item, sympy.Pow):
                base, exponent = of(item.base), of(item.exp)
                if exponent or base and not item.exp.is_Number:
                    raise self.fail(field, f"raises {self.named(item.base, base)} to {self.named(item.exp, exponent)}; "
                                    "a power with a dimension needs a dimensionless number as its exponent",
                                    "Correct the equation, or the unit of one of them")
                return _combine({}, base, float(item.exp)) if base else {}
            if isinstance(item, sympy.atan2):
                of(sympy.Add(*item.args, evaluate=False))  # Its two arguments agree; the angle has none.
                return {}
            if isinstance(item, sympy.Abs):
                return of(item.args[0])
            if isinstance(item, (sympy.sign, sympy.Heaviside)):
                of(item.args[0])
                return {}
            for arg in item.args:
                found = of(arg)
                if found:
                    raise self.fail(field, f"applies {type(item).__name__} to {self.named(arg, found)}, which has a "
                                    "dimension", "Make its argument dimensionless, such as n/n_max")
            return {}
        return of(expression)

    def named(self, expression: sympy.Basic, found: dict[str, float]) -> str:
        notes = sorted({self.notes[symbol.name] for symbol in expression.free_symbols if symbol.name in self.notes})
        source = f" from {', '.join(notes)}" if notes else ""
        return f"{expression} ({shown_dimension(found)}{source})"

    # Expression trees.

    def tree(self, expression: sympy.Basic, nodes: dict | None = None) -> dict[str, object]:
        """The expression as a tree (document.schema.json, $defs/expression), or _Unsupported."""
        if nodes and expression in nodes:
            return nodes[expression]
        if expression is sympy.I:
            return {"constant": "i"}
        if expression.is_Number or isinstance(expression, sympy.NumberSymbol):
            if not expression.is_real or not expression.is_finite:
                raise _Unsupported(expression)
            value = float(expression)
            return {"number": int(value) if value.is_integer() and abs(value) < 2 ** 53 else value}
        if expression.is_Symbol and expression.name in self.symbols:
            return {"symbol": expression.name}
        if isinstance(expression, AppliedUndef):
            return {"symbol": type(expression).__name__}
        if isinstance(expression, sympy.Derivative) and isinstance(expression.expr, AppliedUndef):
            [(_, order)] = expression.variable_count
            return {"derivative": type(expression.expr).__name__, "order": int(order)}
        operator = OPERATORS.get(type(expression))
        if operator is None:
            raise _Unsupported(expression)
        return {"op": operator, "args": [self.tree(arg, nodes) for arg in expression.args]}


class _Unsupported(ValueError):
    """An expression the tree has no node for, such as a Piecewise solution."""


def _combine(left: dict[str, float], right: dict[str, float], power: float) -> dict[str, float]:
    result = dict(left)
    for name, exponent in right.items():
        total = round(result.get(name, 0) + power * exponent, 12)
        result[name] = int(total) if float(total).is_integer() else total
        if not result[name]:
            del result[name]
    return dict(sorted(result.items()))


def resolve(content: dict[str, object], context: FigureContext) -> dict[str, object]:
    """The equations body (document.schema.json, $defs/figureBodies/equations) of a checked mapping."""
    figure = _Figure(content, context)
    plot = content["plot"]
    y_items = [item if isinstance(item, dict) else {"expression": item}
               for item in (plot["y"] if isinstance(plot["y"], list) else [plot["y"]])]
    sources = content["equations"] if isinstance(content["equations"], list) else [content["equations"]]
    unknowns = content.get("unknowns") or [item["expression"] for item in y_items
                                           if item["expression"] in content["variables"]]
    for unknown in unknowns:
        if unknown not in content["variables"]:
            raise figure.fail("unknowns", f"lists {unknown}, which is no variable", "List variables of the figure")
    variables = figure.variables(unknowns)
    equations = []
    for index, source in enumerate(sources):
        field = f"equations[{index}]"
        parsed = figure.parse(source, field)
        equation = parsed if isinstance(parsed, sympy.Eq) else sympy.Eq(parsed, 0, evaluate=False)
        figure.dimension(equation, field)
        equations.append((source, equation))
    used = set().union(*(equation.free_symbols | {sympy.Symbol(type(item).__name__)
                                                  for item in equation.atoms(AppliedUndef)}
                         for _, equation in equations))
    unknowns = [name for name in unknowns if content.get("unknowns") or sympy.Symbol(name) in used]
    if len(unknowns) != len(equations):
        raise figure.fail("unknowns", f"has {len(unknowns)} unknowns ({', '.join(unknowns) or 'none'}) for "
                          f"{len(equations)} equations", "List one unknown per equation under unknowns")
    differential = any(equation.has(sympy.Derivative) for _, equation in equations)
    for name in unknowns:
        if (name in figure.functions) != differential:
            raise figure.fail(f"variables.{name}", "is an unknown " + (
                "of a differential system but no function" if differential else "with of, but no equation has a derivative"),
                "Give each unknown of a differential system of: <variable> and initial, and no other variable of")
    body: dict[str, object] = {
        "equations": [{"source": source, "lhs": figure.tree(equation.lhs), "rhs": figure.tree(equation.rhs)}
                      for source, equation in equations],
        "variables": variables, "unknowns": unknowns,
        "solution": (_differential if differential else _algebraic)(figure, [eq for _, eq in equations], unknowns,
                                                                    variables),
    }
    body["plot"] = _plot(figure, plot, y_items, variables, unknowns, differential)
    return body


def _algebraic(figure: _Figure, equations: list, unknowns: list[str], variables: dict) -> dict[str, object]:
    symbols = [figure.symbols[name] for name in unknowns]
    try:
        solutions = sympy.solve(equations, symbols, dict=True)
    except (NotImplementedError, ValueError, TypeError):
        solutions = []
    branches = []
    allowed = set(figure.symbols.values()) - set(symbols)
    for solution in solutions:
        try:
            if set(solution) == set(symbols) and all(value.free_symbols <= allowed for value in solution.values()):
                branches.append({name: figure.tree(solution[figure.symbols[name]]) for name in unknowns})
        except _Unsupported:
            continue
    if branches:
        return {"method": "exact", "branches": branches}
    guess = {}
    for name in unknowns:
        if "siValue" not in variables[name]["quantity"]:
            raise figure.fail(f"variables.{name}.default", "is missing; SymPy finds no explicit solution, and a "
                              "numeric solution starts from each unknown's default", "Give the unknown a default")
        guess[name] = variables[name]["quantity"]["siValue"]
    return {"method": "algebraic", "residuals": [figure.tree(equation.lhs - equation.rhs) for equation in equations],
            "guess": guess}


def _differential(figure: _Figure, equations: list, unknowns: list[str], variables: dict) -> dict[str, object]:
    independents = {figure.functions[name] for name in unknowns}
    if len(independents) != 1:
        raise figure.fail("unknowns", f"are functions of {', '.join(sorted(independents))}",
                          "Make every function of a differential system a function of one variable")
    [independent] = independents
    span = variables[independent]["quantity"].get("siRange")
    if span is None:
        raise figure.fail(f"variables.{independent}.range", "is missing; a differential system starts at the "
                          "start of its independent variable's range", f"Give {independent} a range")
    t, start = figure.symbols[independent], span[0]
    functions = {name: sympy.Function(name)(t) for name in unknowns}
    orders = {name: max([0, *(int(dict(item.variable_count)[t]) for equation in equations
                              for item in equation.atoms(sympy.Derivative) if item.expr == functions[name])])
              for name in unknowns}
    initial = {}
    for name in unknowns:
        values = figure.content["variables"][name].get("initial", [])
        if len(values) != orders[name]:
            raise figure.fail(f"variables.{name}.initial", f"has {len(values)} values for a function whose equation "
                              f"is of order {orders[name]}",
                              f"Give {name} and its derivatives below order {orders[name]} at the start of {independent}'s range")
        unit = parse_unit(variables[name]["quantity"]["unit"])
        per = parse_unit(variables[independent]["quantity"]["unit"])
        initial[name] = [_si(value, unit / per ** order) for order, value in enumerate(values)]
    conditions = {}
    for name, values in initial.items():
        for order, value in enumerate(values):
            point = functions[name] if order == 0 else functions[name].diff(t, order)
            conditions[point.subs(t, start)] = sympy.nsimplify(value, rational=True)
    try:
        solved = sympy.dsolve(equations[0] if len(equations) == 1 else equations,
                              functions[unknowns[0]] if len(unknowns) == 1 else list(functions.values()), ics=conditions)
        solved = solved if isinstance(solved, list) else [solved]
        allowed = set(figure.symbols.values()) - {figure.symbols[name] for name in unknowns}
        if all(solution.rhs.free_symbols <= allowed and not solution.rhs.atoms(AppliedUndef) for solution in solved):
            return {"method": "exact", "branches": [{type(solution.lhs).__name__: figure.tree(solution.rhs)
                                                     for solution in solved}]}
    except (NotImplementedError, ValueError, TypeError, _Unsupported, AttributeError):
        pass
    return _state_form(figure, equations, unknowns, functions, orders, independent, start, initial)


def _state_form(figure, equations, unknowns, functions, orders, independent, start, initial) -> dict[str, object]:
    t = figure.symbols[independent]
    nodes, replacements = {}, {}
    for name in unknowns:
        for order in range(orders[name] + 1):
            item = functions[name] if order == 0 else functions[name].diff(t, order)
            placeholder = sympy.Dummy(f"{name}_{order}")
            replacements[item] = placeholder
            nodes[placeholder] = {"symbol": name} if order == 0 else {"derivative": name, "order": order}
    # Highest derivatives first, so that y'' becomes its placeholder before y(t) inside it does.
    ordered = sorted(replacements, key=lambda item: -nodes[replacements[item]].get("order", 0))
    replaced = [equation.subs([(item, replacements[item]) for item in ordered]) for equation in equations]
    highest = [replacements[functions[name].diff(t, orders[name])] for name in unknowns]
    try:
        solutions = sympy.solve(replaced, highest, dict=True)
    except (NotImplementedError, ValueError, TypeError):
        solutions = []
    if len(solutions) != 1 or set(solutions[0]) != set(highest):
        raise figure.fail("equations", "cannot be written in state form: SymPy finds neither an explicit solution "
                          "nor each unknown's highest derivative", "Write each equation so that it gives the "
                          "highest derivative of one unknown once, such as y'' = f(t, y, y')")
    state, derivatives, values = [], [], []
    for name, top in zip(unknowns, highest):
        for order in range(orders[name]):
            state.append({"of": name, "order": order})
            values.append(initial[name][order])
            derivatives.append(nodes[replacements[functions[name].diff(t, order + 1)]] if order + 1 < orders[name]
                               else _tree(figure, solutions[0][top], nodes, "equations"))
    return {"method": "differential", "independent": independent, "start": start, "state": state,
            "derivatives": derivatives, "initial": values}


def _tree(figure: _Figure, expression: sympy.Basic, nodes: dict, field: str) -> dict[str, object]:
    try:
        return figure.tree(expression, nodes)
    except _Unsupported as error:
        raise figure.fail(field, f"gives {error.args[0]}, which the expression tree cannot carry",
                          "Use only functions the expression tree carries") from error


def _plot(figure: _Figure, plot: dict, y_items: list[dict], variables: dict, unknowns: list[str],
          differential: bool) -> dict[str, object]:
    def plotted(source: str, field: str) -> dict[str, object]:
        expression = figure.parse(source, field)
        if isinstance(expression, sympy.Eq):
            raise figure.fail(field, "is an equation", "Plot an expression, such as T or T*n")
        return {"source": source, "tree": _tree(figure, expression, {}, field),
                "dimension": figure.dimension(expression, field), "expression": expression}

    x = plotted(plot["x"], "plot.x")
    ys = [{**plotted(item["expression"], f"plot.y[{index}]"), "axis": item.get("axis", "primary")}
          for index, item in enumerate(y_items)]
    movable = [name for name, variable in variables.items() if "range" in variable["quantity"]
               and name not in unknowns]
    if differential:
        sweep = figure.functions[unknowns[0]]
    else:
        candidates = [name for name in movable if figure.symbols[name] in x["expression"].free_symbols]
        named = [symbol.name for symbol in x["expression"].free_symbols if symbol.name not in unknowns]
        if len(named) != 1 or len(candidates) != 1:
            raise figure.fail("plot.x", f"is {plot['x']}, which sweeps {', '.join(sorted(named)) or 'nothing'}; "
                              "x sweeps exactly one variable over its range, and that variable must have a range",
                              "Plot x over one variable that has a range")
        [sweep] = candidates
    result: dict[str, object] = {"sweep": sweep, "x": _strip(x), "y": [_strip(item) for item in ys]}
    if "family" in plot:
        result["family"] = _family(figure, plot["family"], variables, unknowns, sweep)
    if plot.get("parallelCoordinates"):
        axes = [{"source": name, "tree": {"symbol": name}, "dimension": variables[name]["quantity"]["dimension"]}
                for name in movable if name not in figure.functions]
        result["parallelCoordinates"] = {"axes": axes + [_strip(item, axis=False) for item in ys]}
    return result


def _strip(item: dict, axis: bool = True) -> dict[str, object]:
    return {key: value for key, value in item.items() if key != "expression" and (axis or key != "axis")}


def _family(figure: _Figure, family: dict, variables: dict, unknowns: list[str], sweep: str) -> dict[str, object]:
    name = family["variable"]
    if name not in variables or name in unknowns or name == sweep:
        raise figure.fail("plot.family.variable", f"is {name}, which is no variable the reader can set apart "
                          "from the x sweep", "Name a variable that is neither an unknown nor swept on x")
    quantity = variables[name]["quantity"]
    span = quantity.get("range")
    if "steps" in family:
        if span is None:
            raise figure.fail("plot.family.steps", f"spreads values over the range of {name}, which has none",
                              f"Give {name} a range, or list values")
        steps = family["steps"]
        values = [float(f"{span[0] + (span[1] - span[0]) * index / (steps - 1):.15g}") for index in range(steps)]
    else:
        values = family["values"]
        for index, value in enumerate(values):
            if span is not None and not span[0] <= value <= span[1]:
                raise figure.fail(f"plot.family.values[{index}]", f"is {value}, outside the range {span} of {name}",
                                  f"Give values inside the range of {name}")
    unit = parse_unit(quantity["unit"])
    return {"variable": name, "values": values, "siValues": [_si(value, unit) for value in values]}


def _si(value: float, unit: pint.Unit) -> float:
    """``value`` in ``unit`` in SI base units, to 15 significant digits, as obs.quantity gives it."""
    converted = (value * unit).to_base_units().magnitude
    result = float(f"{converted:.15g}")
    return int(result) if result.is_integer() and math.isfinite(result) else result

