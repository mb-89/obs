"""What the core's contract tests check a Document against, each computed once per test process.

Reader: a core test that validates a value against a JSON Schema or reads obs's capability
reference built from spec/capabilities.

``validate`` is ``jsonschema.validate``: it checks the schema against its metaschema, then raises
the best-matching error of the instance, if any. It checks each schema once per process, not at
every call: the check alone costs far more than validating a Document. ``capability_reference``
is ``build_capability_reference`` of spec/capabilities and its coverage.json, built once per
process; each caller gets its own copy, which it may change.
"""
from __future__ import annotations

import copy
import functools
import json
from pathlib import Path

from jsonschema import validators
from jsonschema.exceptions import best_match

from obs.capabilities import build_capability_reference


ROOT = Path(__file__).parents[1]


@functools.cache
def _checked(schema: str):
    """The validator of the schema, given as JSON in its own key order, once its metaschema accepts it."""
    loaded = json.loads(schema)
    cls = validators.validator_for(loaded)
    cls.check_schema(loaded)
    return cls(loaded)


def validate(instance: object, schema: dict) -> None:
    """As ``jsonschema.validate(instance, schema)``, with the schema checked once per process."""
    error = best_match(_checked(json.dumps(schema)).iter_errors(instance))
    if error is not None:
        raise error


@functools.cache
def _capability_reference() -> dict[str, object]:
    capabilities = ROOT / "spec" / "capabilities"
    return build_capability_reference(capabilities, capabilities / "coverage.json")


def capability_reference() -> dict[str, object]:
    """obs's capability reference built from spec/capabilities and its coverage.json; a copy of its own."""
    return copy.deepcopy(_capability_reference())
