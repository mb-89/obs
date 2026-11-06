"""A property-editor fence's static projection, as capabilities/property-editors describes it.

The core validates the fence against input.schema.json (propertyEditor) and carries the mapping,
projection included, in the ``property-editors`` node's ``attrs.spec``.
"""
from pathlib import Path

import pytest

from obs.document import DocumentError, build_document
from test_vault import capability_reference

PROJECTION = {
    "blank": {"status": "finding", "accepted": "no", "outputs": []},
    "nonblank": {"status": "explained", "accepted": "yes", "outputs": ["System", "Labels"]},
}
FRONTMATTER = "explanation: Original\nstatus: explained\naccepted: \"yes\"\noutputs: [System]\n"


def _build(tmp_path: Path, projection: str) -> dict:
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "chapter.md").write_text(
        f"---\n{FRONTMATTER}---\n# Chapter\n\n"
        "```property-editor\nversion: 1\nfield: explanation\nlabel: Review\n"
        f"{projection}```\n", encoding="utf-8",
    )
    return build_document(tmp_path / "manifest.md", capability_reference())


def test_a_static_projection_is_carried_in_the_property_editors_node(tmp_path: Path) -> None:
    document = _build(tmp_path, "projection:\n"
                      "  blank: {status: finding, accepted: \"no\", outputs: []}\n"
                      "  nonblank: {status: explained, accepted: \"yes\", outputs: [System, Labels]}\n")

    [editor] = [node for node in document["chapters"][0]["content"] if node["type"] == "property-editors"]
    assert editor["attrs"]["spec"]["projection"] == PROJECTION
    assert "property-editors" in document["capabilities"]


@pytest.mark.parametrize(("projection", "field"), [
    ("projection:\n  blank: {status: finding}\n", "projection.nonblank"),
    ("projection:\n  blank: {status: finding}\n  nonblank: {}\n", "projection.nonblank"),
    ("projection:\n  blank: {status: {nested: value}}\n  nonblank: {status: ok}\n", "projection.blank.status"),
    ("projection:\n  blank: {status: [mixed, {a: 1}]}\n  nonblank: {status: ok}\n", "projection.blank.status"),
    ("projection:\n  blank: {status: ok}\n  nonblank: {status: ok}\n  other: {status: ok}\n",
     "projection.other"),
])
def test_an_invalid_projection_names_the_note_the_field_and_the_owner(
    tmp_path: Path, projection: str, field: str,
) -> None:
    with pytest.raises(DocumentError) as failure:
        _build(tmp_path, projection)

    message = str(failure.value)
    assert message.startswith(f"{tmp_path / 'chapter.md'}: property-editor fence 1, {field}"), message
    assert "; see capabilities/property-editors." in message
