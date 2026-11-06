"""Equation figures: SymPy equations, their variables and ranges, the solution and the initial plot.

Reader: whoever changes the equations figure kind (input-model, Equation figures;
capabilities/equation-figures). One vault holds every figure that builds; it is built once, since
SymPy's solving dominates the time. Each error case builds its own small vault and fails before
anything is solved.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
import sympy

from obs.document import DocumentError, build_document

from expression_trees import evaluate, sympy_expression
from test_vault import capability_reference


OWNER = "capabilities/equation-figures"
SPEED = ("---\nkind: quantity\nvalue: 3000\nunit: rpm\nrange: [800, 6000]\naliases: [engineSpeed]\n"
         "source: '[[chapter]]'\n---\n# Engine speed\n")
LOAD = "---\nkind: quantity\nvalue: 2\nunit: kN\nrange: [0, 5]\naliases: [load]\nsource: '[[chapter]]'\n---\n"
PLAIN = "---\nkind: quantity\nvalue: 4\nunit: m\naliases: [span]\nsource: '[[chapter]]'\n---\n"
TORQUE = """\
equations: T = T_max*throttle*(1 - (n/n_max)**2)
variables:
  n: "[[engineSpeed]]"
  n_max: {default: 6000, unit: rpm}
  T_max: {default: 250, unit: N*m}
  throttle: {default: 1, range: [0, 1]}
  T: {unit: N*m}
plot:
  x: n
  y: [T, {expression: T*n, axis: secondary}]
  family: {variable: throttle, values: [0.25, 0.5, 1]}
  parallelCoordinates: true
"""
OSCILLATOR = """\
equations: y'' + 2*zeta*w*y' + w**2*y = w**2*u
variables:
  t: {default: 0, range: [0, 10], unit: s}
  y: {of: t, initial: [0, 0]}
  zeta: {default: 0.3, range: [0.1, 1.9]}
  w: {default: 2, range: [0.5, 5], unit: 1/s}
  u: {default: 1, range: [0, 2]}
plot:
  x: t
  y: y
  family: {variable: zeta, steps: 7}
  grid: {zeta: {values: [0.2, 0.5, 0.8, 1.3]}, u: {steps: 3}}
  computed:
    - {name: settling, summary: settlingTime, of: y, tolerance: 0.02}
    - {name: error, summary: absoluteArea, of: u - y}
    - {expression: zeta*w}
    - {summary: valueAt, of: y, at: 2}
"""
SATURATED = OSCILLATOR.replace("w**2*y =", "w**2*Min(Max(y, -1), 1) =")
RANGES = """\
equations: Eq(F, load*k + 0*span)
variables:
  load: {quantity: "[[load]]", range: [1, 8]}
  span: "[[span]]"
  k: {default: 2, range: [1, 3]}
  c: {default: 5}
  s: {quantity: "[[span]]", range: [3, 6]}
  F: {unit: kN}
unknowns: [F]
plot: {x: load, y: F + 0*c*k + 0*s}
"""


def _figure(content: str, kind: str = "equations") -> str:
    indented = "".join(f"  {line}\n" for line in content.splitlines())
    return f"```figure\nversion: 1\nkind: {kind}\ncaption: An equation figure.\ncontent:\n{indented}```\n"


def _build(root: Path, chapter: str) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (root / "chapter.md").write_text(chapter, encoding="utf-8")
    for name, text in {"speed.md": SPEED, "load.md": LOAD, "span.md": PLAIN}.items():
        (root / name).write_text(text, encoding="utf-8")
    return build_document(root / "manifest.md", capability_reference())


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> tuple[dict, dict[str, dict]]:
    """The Document of one vault with the torque, oscillator, saturated and range figures."""
    figures = {"torque": TORQUE, "oscillator": OSCILLATOR, "saturated": SATURATED, "ranges": RANGES}
    document = _build(tmp_path_factory.mktemp("equations"), "\n".join(map(_figure, figures.values())))
    nodes = [node for node in document["chapters"][0]["content"] if node["type"] == "figures"]
    return document, {name: node["children"][0]["attrs"] for name, node in zip(figures, nodes)}


def _fails(tmp_path: Path, content: str, field: str) -> str:
    with pytest.raises(DocumentError) as failure:
        _build(tmp_path, _figure(content))
    message = str(failure.value)
    assert message.startswith(f"{tmp_path / 'chapter.md'}: figure fence 1, {field}:"), message
    assert f"see {OWNER}." in message, message
    return message


def test_a_torque_figure_yields_expression_trees_variable_ranges_and_the_initial_plot(built) -> None:
    document, bodies = built
    body = bodies["torque"]
    symbols = sympy.symbols("T T_max throttle n n_max")
    torque, maximum, throttle, speed, top = symbols

    assert "equation-figures" in document["capabilities"]
    [equation] = body["equations"]
    assert equation["source"] == "T = T_max*throttle*(1 - (n/n_max)**2)"
    assert sympy_expression(equation["lhs"]) == torque
    assert sympy.simplify(sympy_expression(equation["rhs"]) - maximum * throttle * (1 - (speed / top) ** 2)) == 0
    assert body["unknowns"] == ["T"]
    assert body["solution"]["method"] == "exact"
    [branch] = body["solution"]["branches"]
    assert sympy.simplify(sympy_expression(branch["T"]) - maximum * throttle * (1 - (speed / top) ** 2)) == 0
    # n comes from its quantity note: default, unit and range; throttle moves; n_max is fixed.
    assert body["variables"]["n"]["note"] == "speed.md"
    assert body["variables"]["n"]["quantity"]["range"] == [800, 6000]
    assert body["variables"]["n"]["quantity"]["siRange"] == pytest.approx([83.7758041, 628.3185307])
    assert body["variables"]["throttle"]["quantity"]["range"] == [0, 1]
    assert "range" not in body["variables"]["n_max"]["quantity"]
    assert body["variables"]["T"]["quantity"] == {"unit": "N*m", "dimension": {"length": 2, "mass": 1, "time": -2}}
    plot = body["plot"]
    assert plot["sweep"] == "n"
    assert plot["x"] == {"source": "n", "tree": {"symbol": "n"}, "dimension": {"time": -1}}
    assert [(item["source"], item["axis"]) for item in plot["y"]] == [("T", "primary"), ("T*n", "secondary")]
    assert plot["family"] == {"variable": "throttle", "values": [0.25, 0.5, 1], "siValues": [0.25, 0.5, 1]}
    # The fence shows the plot; its one grid axis is throttle, the one movable variable besides the x sweep.
    assert plot["parallelCoordinates"]["shown"] is True
    assert plot["parallelCoordinates"]["axes"] == [{
        "label": "throttle", "variable": "throttle", "dimension": {},
        "values": [0, 0.25, 0.5, 0.75, 1], "siValues": [0, 0.25, 0.5, 0.75, 1]}]
    values = {"T_max": 250, "throttle": 0.5, "n": 300, "n_max": 600}
    assert evaluate(branch["T"], values) == pytest.approx(93.75)


def test_parallel_coordinates_carry_the_grid_and_the_computed_axes(built) -> None:
    _, bodies = built
    plot = bodies["oscillator"]["plot"]
    parallel = plot["parallelCoordinates"]
    axes = {axis["label"]: axis for axis in parallel["axes"]}

    # Without parallelCoordinates: true the reader opens the plot from the menu.
    assert parallel["shown"] is False
    # Grid variables in the order of variables (t is the sweep), then the computed axes as authored.
    assert list(axes) == ["zeta", "w", "u", "settling", "error", "zeta*w", "valueAt(y)"]
    assert axes["zeta"]["values"] == [0.2, 0.5, 0.8, 1.3]  # explicit values
    assert axes["u"]["values"] == [0, 1, 2]  # steps
    assert axes["w"]["values"] == [0.5, 1.625, 2.75, 3.875, 5]  # 5 steps by default
    assert axes["w"]["siValues"] == axes["w"]["values"] and axes["w"]["dimension"] == {"time": -1}
    settling = axes["settling"]
    assert (settling["summary"], settling["tolerance"], settling["dimension"]) == ("settlingTime", 0.02, {"time": 1})
    assert settling["of"] == {"source": "y", "tree": {"symbol": "y"}, "dimension": {}}
    error = axes["error"]
    assert error["summary"] == "absoluteArea" and error["dimension"] == {"time": 1}
    assert evaluate(error["of"]["tree"], {"u": 1, "y": 0.25}) == pytest.approx(0.75)
    product = axes["zeta*w"]
    assert product["dimension"] == {"time": -1} and "summary" not in product
    assert evaluate(product["tree"], {"zeta": 0.5, "w": 3}) == pytest.approx(1.5)
    assert (axes["valueAt(y)"]["summary"], axes["valueAt(y)"]["at"], axes["valueAt(y)"]["siAt"]) == ("valueAt", 2, 2)


@pytest.mark.parametrize(
    ("content", "field"),
    [
        (TORQUE.replace("parallelCoordinates: true", "grid: {n_max: {steps: 3}}"), "content.plot.grid.n_max"),
        (TORQUE.replace("parallelCoordinates: true", "grid: {n: {steps: 3}}"), "content.plot.grid.n"),
        (TORQUE.replace("parallelCoordinates: true", "grid: {throttle: {values: [0.5, 2]}}"),
         "content.plot.grid.throttle.values[1]"),
        (TORQUE.replace("parallelCoordinates: true", "computed: [{expression: throttle*n}]"),
         "content.plot.computed[0].expression"),
        (TORQUE.replace("parallelCoordinates: true", "computed: [{expression: 2*T}]"),
         "content.plot.computed[0].expression"),
        (TORQUE.replace("parallelCoordinates: true", "computed: [{summary: valueAt, of: T, at: 9000}]"),
         "content.plot.computed[0].at"),
        (TORQUE.replace("parallelCoordinates: true", "computed: [{summary: maximum, of: T + q}]"),
         "content.plot.computed[0].of"),
        (TORQUE.replace("parallelCoordinates: true", "computed: [{summary: settlingTime, of: T}]"),
         "content.plot.computed[0]"),
    ],
    ids=["fixed-variable", "sweep", "value-outside", "expression-of-x", "expression-of-unknown", "at-outside",
         "unknown-name", "no-tolerance"],
)
def test_a_parallel_coordinates_input_error_names_the_field_and_the_owner(tmp_path, content, field) -> None:
    _fails(tmp_path, content, field)


def test_a_second_order_linear_system_yields_an_exact_solution(built) -> None:
    _, bodies = built
    body = bodies["oscillator"]

    assert body["unknowns"] == ["y"]
    assert body["variables"]["y"]["of"] == "t"
    lhs, rhs = (sympy_expression(body["equations"][0][side]) for side in ("lhs", "rhs"))
    names = {name: sympy.Symbol(name) for name in ("d2_y", "d1_y", "y", "zeta", "w", "u")}
    assert sympy.expand(lhs - sympy.sympify("d2_y + 2*zeta*w*d1_y + w**2*y", locals=names)) == 0
    assert rhs == sympy.sympify("w**2*u", locals=names)
    assert body["solution"]["method"] == "exact"
    [branch] = body["solution"]["branches"]
    # Underdamped (complex intermediates) and overdamped both give the real response.
    for zeta in (0.3, 2.0):
        expected = _oscillator(zeta, 2.0, 1.0, 1.5)
        assert evaluate(branch["y"], {"t": 1.5, "zeta": zeta, "w": 2.0, "u": 1.0}) == pytest.approx(expected, rel=1e-9)


def test_an_oscillator_family_through_critical_damping_draws_every_curve(built) -> None:
    _, bodies = built
    body = bodies["oscillator"]
    family = body["plot"]["family"]
    [branch] = body["solution"]["branches"]
    start, end = body["variables"]["t"]["quantity"]["siRange"]

    # 7 steps over [0.1, 1.9] hit zeta = 1, where the general solution is 0/0.
    assert 1 in family["siValues"]
    for zeta in family["siValues"]:
        for index in range(241):
            t = start + (end - start) * index / 240
            assert evaluate(branch["y"], {"t": t, "zeta": zeta, "w": 2.0, "u": 1.0}) is not None, (zeta, t)
    for t in (0.25, 1.5, 6.0):
        critical = 1 - (1 + 2.0 * t) * math.exp(-2.0 * t)
        assert evaluate(branch["y"], {"t": t, "zeta": 1, "w": 2.0, "u": 1.0}) == pytest.approx(critical, rel=1e-9)


def test_where_sympy_finds_no_limit_the_document_marks_the_value_for_the_numeric_solver(tmp_path, monkeypatch) -> None:
    def no_limit(*_):
        raise NotImplementedError("no limit")

    monkeypatch.setattr(sympy, "limit", no_limit)
    document = _build(tmp_path, _figure(OSCILLATOR))

    [node] = [node for node in document["chapters"][0]["content"] if node["type"] == "figures"]
    solution = node["children"][0]["attrs"]["solution"]
    assert solution["method"] == "exact"
    assert solution["numeric"]["when"] == {"relation": "eq", "args": [{"symbol": "zeta"}, {"number": 1}]}
    system = solution["numeric"]["system"]
    assert (system["method"], system["state"], system["initial"]) == (
        "differential", [{"of": "y", "order": 0}, {"of": "y", "order": 1}], [0, 0])


def _oscillator(zeta: float, w: float, u: float, t: float) -> float:
    """The unit step response of the second-order system, written out by hand."""
    import cmath
    root = cmath.sqrt(zeta ** 2 - 1)
    first, second = w * (-zeta + root), w * (-zeta - root)
    value = u * (1 + (second * cmath.exp(first * t) - first * cmath.exp(second * t)) / (first - second))
    return value.real


def test_a_nonlinear_system_with_saturation_yields_a_numeric_system_with_initial_conditions(built) -> None:
    _, bodies = built
    solution = bodies["saturated"]["solution"]

    assert solution["method"] == "differential"
    assert solution["independent"] == "t"
    assert solution["start"] == 0
    assert solution["state"] == [{"of": "y", "order": 0}, {"of": "y", "order": 1}]
    assert solution["initial"] == [0, 0]
    assert solution["derivatives"][0] == {"derivative": "y", "order": 1}
    state = {"y": 2.0, "zeta": 0.5, "w": 2.0, "u": 1.0}
    acceleration = evaluate(solution["derivatives"][1], state, derivatives={("y", 1): 0.5})
    assert acceleration == pytest.approx(4 * (1 - 1) - 2 * 0.5 * 2 * 0.5)


def test_the_range_rule_intersects_takes_one_side_or_fixes_the_variable(built) -> None:
    _, bodies = built
    variables = bodies["ranges"]["variables"]

    assert variables["load"]["quantity"]["range"] == [1, 5]  # note [0, 5] and fence [1, 8] intersect
    assert variables["load"]["quantity"]["siRange"] == [1000, 5000]
    assert variables["k"]["quantity"]["range"] == [1, 3]  # the fence's alone
    assert variables["s"]["quantity"]["range"] == [3, 6]  # the fence's, the note has none
    assert "range" not in variables["c"]["quantity"]  # neither: fixed at its default
    assert variables["c"]["quantity"]["value"] == 5
    assert "range" not in variables["span"]["quantity"]


@pytest.mark.parametrize(
    ("content", "field"),
    [
        (RANGES.replace("range: [1, 8]", "range: [6, 8]"), "content.variables.load.range"),
        (RANGES.replace("k: {default: 2, range: [1, 3]}", "k: {default: 4, range: [1, 3]}"), "content.variables.k.default"),
        (RANGES.replace("s: {quantity: \"[[span]]\", range: [3, 6]}", "s: {quantity: \"[[span]]\", range: [5, 6]}"),
         "content.variables.s.range"),
        (RANGES.replace("k: {default: 2, range: [1, 3]}", "k: {default: 2, range: [3, 1]}"), "content.variables.k.range"),
    ],
    ids=["empty-intersection", "default-outside", "note-value-outside", "reversed"],
)
def test_a_range_rule_violation_names_the_note_the_fence_and_the_remedy(tmp_path, content, field) -> None:
    message = _fails(tmp_path, content, field)

    if "load" in field or ".s." in field:
        assert ("load.md" if "load" in field else "span.md") in message


def test_a_unit_mismatch_inside_an_equation_names_both_quantities(tmp_path) -> None:
    message = _fails(tmp_path, TORQUE.replace("(1 - (n/n_max)**2)", "(1 - n)"), "content.equations[0]")

    assert "1" in message and "n" in message and "speed.md" in message
    message = _fails(tmp_path / "sides", TORQUE.replace("T = T_max", "T = n*T_max"), "content.equations[0]")
    assert "T_max" in message and "speed.md" in message


@pytest.mark.parametrize(
    ("content", "field", "name"),
    [
        (TORQUE.replace("T_max*throttle", "T_max*throttle*k"), "content.equations[0]", "k"),
        (TORQUE.replace("T_max*throttle", "T_max*f(n)"), "content.equations[0]", "f"),
        (TORQUE.replace("T_max*throttle", "T_max*gamma(throttle)"), "content.equations[0]", "gamma"),
        (TORQUE.replace("(1 - (n/n_max)**2)", "(1 - (n/n_max)**2"), "content.equations[0]", "SymPy"),
        (TORQUE.replace("y: [T, {expression: T*n, axis: secondary}]", "y: [T, q]"), "content.plot.y[1]", "q"),
    ],
    ids=["unknown-symbol", "undefined-function", "unsupported-function", "syntax", "plot-symbol"],
)
def test_an_unknown_name_is_refused_with_the_note_and_line(tmp_path, content, field, name) -> None:
    message = _fails(tmp_path, content, field)

    assert name in message
    if field.startswith("content.equations"):
        assert "line 6" in message  # the note's line of the equation


@pytest.mark.parametrize(
    ("content", "field"),
    [
        (TORQUE.replace('n: "[[engineSpeed]]"', 'n: "[[missing]]"'), "content.variables.n"),
        (TORQUE.replace('n: "[[engineSpeed]]"', 'n: "[[chapter]]"'), "content.variables.n"),
        (TORQUE.replace("n_max: {default: 6000, unit: rpm}", "n_max: {unit: rpm}"), "content.variables.n_max.default"),
        (TORQUE.replace("n_max: {default: 6000, unit: rpm}", "n_max: {default: 6000, unit: flubs}"),
         "content.variables.n_max.unit"),
        (TORQUE.replace("x: n", "x: n_max"), "content.plot.x"),
        (TORQUE.replace("variable: throttle, values: [0.25, 0.5, 1]", "variable: throttle, values: [2]"),
         "content.plot.family.values[0]"),
        (OSCILLATOR.replace("initial: [0, 0]", "initial: [0]"), "content.variables.y.initial"),
        (TORQUE.replace("plot:", "unknowns: [T, n]\nplot:"), "content.unknowns"),
        (TORQUE.replace("plot:", "extra: 1\nplot:"), "content.extra"),
    ],
    ids=["missing-note", "not-a-quantity", "no-default", "unknown-unit", "fixed-sweep", "family-outside",
         "initial-order", "unknown-count", "schema"],
)
def test_an_equation_figure_input_error_names_the_field_and_the_owner(tmp_path, content, field) -> None:
    _fails(tmp_path, content, field)


def test_content_from_a_source_file_gives_the_same_body(tmp_path, built) -> None:
    _, bodies = built
    root = tmp_path / "vault"
    root.mkdir()
    (root / "torque.yaml").write_text(TORQUE, encoding="utf-8")

    document = _build(root, "```figure\nversion: 1\nkind: equations\ncaption: An equation figure.\n"
                            "source: torque.yaml\n```\n")

    [node] = [node for node in document["chapters"][0]["content"] if node["type"] == "figures"]
    assert node["children"][0]["attrs"] == bodies["torque"]
    assert json.dumps(node)  # plain JSON, nothing to execute
