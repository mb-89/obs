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
