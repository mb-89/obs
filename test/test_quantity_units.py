"""Quantity units, ranges, SI values and arithmetic; capabilities/quantities owns the contract."""
import json

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


def _quantities(document) -> tuple[list[dict], list[dict]]:
    """The quantity of every quantities node, and of every quantity note's record."""
    nodes = [node["attrs"]["quantity"] for chapter in document["chapters"]
             for node in chapter["content"] if node["type"] == "quantities"]
    records = [record["quantity"] for record in document["records"]
               if record["type"] == "note" and record["fields"].get("kind") == "quantity"]
    return nodes, records


def test_two_kilometres_carry_two_thousand_metres_and_the_dimension_length(tmp_path) -> None:
    document = build_document(_vault(tmp_path, "value: 2\nunit: km"),
                              {"capabilities": [{"id": "quantities"}], "schemaVersion": 1})

    nodes, records = _quantities(document)
    expected = {"value": 2, "unit": "km", "siValue": 2000, "dimension": {"length": 1}}
    assert nodes == records == [expected]


QUANTITIES = {
    "torque": ("value: 3\nunit: kN*m\nrange: [0, 5]",
               {"value": 3, "unit": "kN*m", "siValue": 3000,
                "dimension": {"length": 2, "mass": 1, "time": -2}, "range": [0, 5], "siRange": [0, 5000]}),
    "speed": ("value: 36\nunit: km/h", {"value": 36, "unit": "km/h", "siValue": 10,
                                         "dimension": {"length": 1, "time": -1}}),
    "ratio": ("value: 50\nunit: '%'", {"value": 50, "unit": "%", "siValue": 0.5, "dimension": {}}),
    "plain": ("value: 4", {"value": 4, "unit": "", "siValue": 4, "dimension": {}}),
    "count": ("query: {where: []}", {"unit": "", "dimension": {}}),
}


def _quantity_vault(tmp_path):
    (tmp_path / "manifest.md").write_text("".join(f"- [[{name}]]\n" for name in QUANTITIES), encoding="utf-8")
    (tmp_path / "drawing.md").write_text("Drawing.\n", encoding="utf-8")
    for name, (fields, _) in QUANTITIES.items():
        (tmp_path / f"{name}.md").write_text(
            f"---\nkind: quantity\naliases: [{name}]\nsource: '[[drawing]]'\n{fields}\n---\n",
            encoding="utf-8")
    return build_document(tmp_path / "manifest.md", {"capabilities": [{"id": "quantities"}], "schemaVersion": 1})


def test_every_quantity_in_the_document_carries_its_value_unit_si_value_and_dimension(tmp_path) -> None:
    document = _quantity_vault(tmp_path)

    nodes, records = _quantities(document)
    expected = [quantity for _, quantity in QUANTITIES.values()]
    assert nodes == expected
    assert sorted(records, key=lambda item: json.dumps(item, sort_keys=True)) == sorted(
        expected, key=lambda item: json.dumps(item, sort_keys=True))


@pytest.mark.parametrize("missing", ["siValue", "dimension", "unit"])
def test_the_document_schema_requires_the_si_value_and_dimension_of_a_quantity(tmp_path, missing) -> None:
    from obs.document import validate_document
    document = _quantity_vault(tmp_path)
    reference = {"capabilities": [{"id": "quantities"}], "schemaVersion": 1}
    node = next(node for node in document["chapters"][0]["content"] if node["type"] == "quantities")
    del node["attrs"]["quantity"][missing]

    with pytest.raises(DocumentError) as raised:
        validate_document(document, reference)

    assert "quantity" in str(raised.value) and "src/obs/document.schema.json" in str(raised.value)
