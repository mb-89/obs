"""Quantity units, ranges, SI values and arithmetic; capabilities/quantities owns the contract."""
import pytest

from obs.document import DocumentError, build_document

REFERENCE = {"capabilities": [], "schemaVersion": 1}


def _vault(tmp_path, fields: str):
    (tmp_path / "manifest.md").write_text("- [[load]]\n", encoding="utf-8")
    (tmp_path / "drawing.md").write_text("Drawing.\n", encoding="utf-8")
    (tmp_path / "load.md").write_text(
        f"---\nkind: quantity\naliases: [maxLoad]\nsource: '[[drawing]]'\n{fields}\n---\n", encoding="utf-8",
    )
    return tmp_path / "manifest.md"


def _failure(manifest) -> str:
    with pytest.raises(DocumentError) as raised:
        build_document(manifest, REFERENCE)
    return str(raised.value)


@pytest.mark.parametrize("unit", ["kN", "N*m", "rpm", "km/h", "%", "mm", "MPa", "degC", "1/s"])
def test_a_quantity_unit_is_a_parsed_physical_unit(tmp_path, unit) -> None:
    build_document(_vault(tmp_path, f"value: 2\nunit: '{unit}'"), REFERENCE)


@pytest.mark.parametrize("unit", ["furlongs-per-banana", "banana", "2 m", "m +"])
def test_an_unknown_unit_names_the_note_the_unit_and_the_remedy(tmp_path, unit) -> None:
    message = _failure(_vault(tmp_path, f"value: 2\nunit: '{unit}'"))

    assert message.startswith(f"{tmp_path / 'load.md'}: unit: ")
    assert repr(unit) in message
    assert message.endswith("; see capabilities/quantities.")


@pytest.mark.parametrize("fields", ["value: 2\nrange: [0, 5]", "value: 0\nrange: [0, 0]",
                                    "value: -1.5\nunit: mm\nrange: [-2, 3.5]"])
def test_a_quantity_may_carry_a_range_holding_its_value(tmp_path, fields) -> None:
    build_document(_vault(tmp_path, fields), REFERENCE)


@pytest.mark.parametrize(("fields", "field"), [
    ("value: 7\nunit: mm\nrange: [0, 5]", "value"),
    ("value: -1\nrange: [0, 5]", "value"),
    ("value: 2\nrange: [5, 0]", "range"),
    ("value: 2\nrange: [0]", "range"),
    ("value: 2\nrange: [0, '5 mm']", "range"),
    ("value: 2\nrange: [0, .inf]", "range"),
    ("value: 2\nrange: {minimum: 0, maximum: 5}", "range"),
])
def test_a_range_that_excludes_the_value_or_is_malformed_fails(tmp_path, fields, field) -> None:
    message = _failure(_vault(tmp_path, fields))

    assert message.startswith(f"{tmp_path / 'load.md'}: {field}: ")
    assert message.endswith("; see capabilities/quantities.")
