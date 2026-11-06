"""Each of the core's schemas is compiled into its validator once per process, by the module that
owns it, and a Document schema's local references are resolved when it is compiled, not per node.
See architecture, The neutral Document."""
import pytest
from jsonschema import Draft202012Validator

from obs import document
from obs.discriminator import discriminating_validator
from test_document_contract import capability_reference, document_fixture


def test_two_validations_in_one_process_compile_the_document_validator_once(monkeypatch) -> None:
    compiled = []
    real = document.discriminating_validator
    monkeypatch.setattr(document, "discriminating_validator", lambda schema: compiled.append(schema) or real(schema))
    document.document_validators.cache_clear()
    try:
        reference = capability_reference()
        document.validate_document(document_fixture(), reference)
        document.validate_document(document_fixture(), reference)
    finally:
        document.document_validators.cache_clear()

    assert len(compiled) == 1


def test_a_local_reference_is_resolved_when_the_validator_is_compiled() -> None:
    with pytest.raises(ValueError, match=r"^#/items: .*src/obs/discriminator\.py\.$"):
        discriminating_validator({"items": {"$ref": "#/$defs/missing"}})


@pytest.mark.parametrize("keyword", ["$id", "$dynamicRef"])
def test_a_schema_whose_local_references_depend_on_scope_is_refused(keyword) -> None:
    schema = {"$defs": {"leaf": {keyword: "leaf", "type": "string"}}, "items": {"$ref": "#/$defs/leaf"}}

    with pytest.raises(ValueError, match=r"^#/\$defs/leaf: .*src/obs/discriminator\.py\.$"):
        discriminating_validator(schema)


def test_a_resolved_reference_reports_what_the_standard_reference_reports() -> None:
    schema = {"$defs": {"leaf": {"type": "string"}, "pair": {"type": "array", "items": {"$ref": "#/$defs/leaf"}}},
              "type": "array", "items": {"$ref": "#/$defs/pair"}}
    instance = [["a", 1], [2], "b"]

    def errors(validator: type[Draft202012Validator]) -> list[tuple[object, ...]]:
        found = validator(schema).iter_errors(instance)
        return sorted((list(error.absolute_path), list(error.absolute_schema_path), error.message) for error in found)

    assert errors(discriminating_validator(schema)) == errors(Draft202012Validator)
