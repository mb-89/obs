"""The shared expression-tree vectors against SymPy; an adapter's live evaluator runs the same file.

Reader: whoever changes the expression tree (document.schema.json, $defs/expression) or its
evaluation rule (input-model, Equation figures). Each vector is a tree, its SI variable values,
derivative values for a state form, and the expected value, null where none is plotted.
"""
import json
from pathlib import Path

import pytest
import sympy
from jsonschema import Draft202012Validator

from expression_trees import evaluate, sympy_expression


ROOT = Path(__file__).parents[1]
VECTORS = json.loads((ROOT / "test" / "fixtures" / "expression-vectors.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((ROOT / "src" / "obs" / "document.schema.json").read_text(encoding="utf-8"))


def _sympy_value(vector: dict) -> float | None:
    substitutions = {sympy.Symbol(name): sympy.nsimplify(value, rational=True) for name, value in vector["values"].items()}
    substitutions |= {sympy.Symbol(f"d{item['order']}_{item['of']}"): sympy.nsimplify(item["value"], rational=True)
                      for item in vector.get("derivatives", [])}
    value = complex(sympy.N(sympy_expression(vector["tree"]).subs(substitutions), 30))
    return value.real if abs(value.imag) <= VECTORS["tolerance"] * max(1.0, abs(value.real)) else None


@pytest.mark.parametrize("vector", VECTORS["vectors"], ids=[vector["name"] for vector in VECTORS["vectors"]])
def test_each_vector_holds_against_sympy_and_the_complex_evaluation_rule(vector) -> None:
    Draft202012Validator({"$ref": "#/$defs/expression", "$defs": SCHEMA["$defs"]}).validate(vector["tree"])
    expected = vector["expected"]
    derivatives = {(item["of"], item["order"]): item["value"] for item in vector.get("derivatives", [])}

    for found in (_sympy_value(vector), evaluate(vector["tree"], vector["values"], derivatives)):
        if expected is None:
            assert found is None
        else:
            assert found == pytest.approx(expected, rel=VECTORS["tolerance"], abs=1e-12)


def test_the_vectors_use_every_operator_and_node_of_the_tree() -> None:
    seen = set()

    def walk(tree: dict) -> None:
        seen.add(tree.get("op") or next(iter(tree)))
        for arg in tree.get("args", []):
            walk(arg)

    for vector in VECTORS["vectors"]:
        walk(vector["tree"])
    [*_, operators] = SCHEMA["$defs"]["expression"]["oneOf"]
    assert seen == {*operators["properties"]["op"]["enum"], "number", "symbol", "derivative", "constant"}
