"""The Document schema's ``discriminator`` keyword: dispatch by a node's type in one lookup.

``discriminator: {"propertyName": P}`` stands beside an ``allOf`` of ``if``/``then`` clauses whose
``if`` keys each clause by ``properties.P`` (``const`` or ``enum``). A standard validator ignores the
keyword and tries every clause; this module's validator evaluates only the clauses keyed by the
instance's P. Every other clause cannot apply to that instance, so both validators refuse the same instances with the same errors. See
document.schema.json ($defs/node).
"""
from collections.abc import Iterator

from jsonschema import Draft202012Validator, ValidationError, validators
from jsonschema import _keywords

OWNER = "src/obs/discriminator.py"


def discriminating_validator(schema: dict[str, object]) -> type[Draft202012Validator]:
    """A Draft 2020-12 validator class for ``schema`` that evaluates its discriminators by lookup."""
    clauses: dict[int, tuple[str, dict[object, list[int]]]] = {}
    _collect(schema, "#", clauses)

    def all_of(validator, subschemas, instance, owner) -> Iterator[ValidationError]:
        keyed = clauses.get(id(owner))
        value = _value(instance, keyed)
        if value is None:
            yield from _keywords.allOf(validator, subschemas, instance, owner)
            return
        for index in keyed[1].get(value, ()):
            yield from validator.descend(instance, subschemas[index], schema_path=index)

    return validators.extend(Draft202012Validator, {"allOf": all_of})


def _value(instance: object, keyed: tuple[str, object] | None) -> str | None:
    """The instance's discriminating value, or None where lookup cannot decide (every clause applies)."""
    if keyed is None or not isinstance(instance, dict):
        return None
    value = instance.get(keyed[0])
    return value if isinstance(value, str) else None


def _collect(node: object, pointer: str, clauses: dict[int, tuple[str, dict[object, list[int]]]]) -> None:
    if isinstance(node, list):
        for index, item in enumerate(node):
            _collect(item, f"{pointer}/{index}", clauses)
        return
    if not isinstance(node, dict):
        return
    if "discriminator" in node and "allOf" in node:
        name = node["discriminator"]["propertyName"]
        table: dict[object, list[int]] = {}
        for index, clause in enumerate(node["allOf"]):
            if "else" in clause:
                raise ValueError(f"{pointer}/allOf/{index}: a discriminated clause has no else; "
                                 f"key it by if.properties.{name}. See {OWNER}.")
            for value in _keys(clause.get("if"), name, f"{pointer}/allOf/{index}/if"):
                table.setdefault(value, []).append(index)
        clauses[id(node)] = (name, table)
    for key, value in node.items():
        _collect(value, f"{pointer}/{key}", clauses)


def _keys(keyed: object, name: str, pointer: str) -> list[object]:
    """The values ``properties.<name>`` of a clause accepts; it must name them with const or enum."""
    rule = keyed.get("properties", {}).get(name, {}) if isinstance(keyed, dict) else {}
    if "const" in rule:
        return [rule["const"]]
    if "enum" in rule:
        return list(rule["enum"])
    raise ValueError(f"{pointer}: a discriminated clause names its {name} with properties.{name}.const "
                     f"or .enum. See {OWNER}.")

