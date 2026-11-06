"""The Document schema's ``discriminator`` keyword: dispatch by a node's type in one lookup.

``discriminator: {"propertyName": P}`` stands beside an ``allOf`` of ``if``/``then`` clauses whose
``if`` keys each clause by ``properties.P`` (``const`` or ``enum``), or beside an ``anyOf`` whose
branches are keyed the same way by their own ``properties.P``. A standard validator ignores the
keyword and tries every clause; this module's validator evaluates only the clauses keyed by the
instance's P, and checks an array's ``items: {not: {$ref: <a discriminated anyOf>}}`` once against
its items' P values, descending only into an item whose P keys a branch. Every other clause cannot
apply to that instance, so both validators refuse the same instances with the same errors. See
document.schema.json ($defs/node and $defs/blockNode).
"""
from collections.abc import Iterator

from jsonschema import Draft202012Validator, ValidationError, validators

OWNER = "src/obs/discriminator.py"
STANDARD = Draft202012Validator.VALIDATORS


def discriminating_validator(schema: dict[str, object]) -> type[Draft202012Validator]:
    """A Draft 2020-12 validator class for ``schema`` that evaluates its discriminators by lookup."""
    clauses: dict[int, tuple[str, dict[object, list[int]]]] = {}
    negations: dict[int, tuple[str, frozenset[object]]] = {}
    _collect(schema, schema, "#", clauses, negations)

    def all_of(validator, subschemas, instance, owner) -> Iterator[ValidationError]:
        keyed = clauses.get(id(owner))
        value = _value(instance, keyed)
        if value is None:
            yield from STANDARD["allOf"](validator, subschemas, instance, owner)
            return
        for index in keyed[1].get(value, ()):
            yield from validator.descend(instance, subschemas[index], schema_path=index)

    def items(validator, subschema, instance, owner) -> Iterator[ValidationError]:
        negated = negations.get(id(subschema))
        if negated is None or not validator.is_type(instance, "array") or owner.get("prefixItems"):
            yield from STANDARD["items"](validator, subschema, instance, owner)
            return
        name, keys = negated
        for index, item in enumerate(instance):
            value = _value(item, (name, keys))
            if value is None or value in keys:
                yield from validator.descend(item, subschema, path=index)

    return validators.extend(Draft202012Validator, {"allOf": all_of, "items": items})


def _value(instance: object, keyed: tuple[str, object] | None) -> str | None:
    """The instance's discriminating value, or None where lookup cannot decide (every clause applies)."""
    if keyed is None or not isinstance(instance, dict):
        return None
    value = instance.get(keyed[0])
    return value if isinstance(value, str) else None


def _collect(root: dict[str, object], node: object, pointer: str,
             clauses: dict[int, tuple[str, dict[object, list[int]]]],
             negations: dict[int, tuple[str, frozenset[object]]]) -> None:
    if isinstance(node, list):
        for index, item in enumerate(node):
            _collect(root, item, f"{pointer}/{index}", clauses, negations)
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
    negated = node.get("not")
    if set(node) <= {"not", "description"} and isinstance(negated, dict) and str(negated.get("$ref", "")).startswith("#/"):
        target = _resolve(root, negated["$ref"])
        if "discriminator" in target:
            name = target["discriminator"]["propertyName"]
            keys = frozenset(value for index, branch in enumerate(target["anyOf"])
                             for value in _keys(branch, name, f"{negated['$ref']}/anyOf/{index}"))
            negations[id(node)] = (name, keys)
    for key, value in node.items():
        _collect(root, value, f"{pointer}/{key}", clauses, negations)


def _keys(keyed: object, name: str, pointer: str) -> list[object]:
    """The values ``properties.<name>`` of a clause accepts; it must name them with const or enum."""
    rule = keyed.get("properties", {}).get(name, {}) if isinstance(keyed, dict) else {}
    if "const" in rule:
        return [rule["const"]]
    if "enum" in rule:
        return list(rule["enum"])
    raise ValueError(f"{pointer}: a discriminated clause names its {name} with properties.{name}.const "
                     f"or .enum. See {OWNER}.")


def _resolve(root: dict[str, object], reference: str) -> dict[str, object]:
    target: object = root
    for part in reference[2:].split("/"):
        target = target[part.replace("~1", "/").replace("~0", "~")]
    return target
