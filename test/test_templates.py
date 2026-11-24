"""Template manifests, template nodes and filled documents; see capabilities/templates."""
from pathlib import Path
import re

import pytest

from obs.document import DocumentError, build_document
from test_capability_examples import FENCE
from test_vault import capability_reference


NOTE = Path(__file__).parents[1] / "spec" / "capabilities" / "templates.md"
OWNER = "capabilities/templates"


def _worked_example(root: Path) -> None:
    """The worked example's vaults, from the fences of the capability note that names their files."""
    text = NOTE.read_text(encoding="utf-8")
    for match in FENCE.finditer(text):
        if match["file"]:
            (root / match["file"]).parent.mkdir(parents=True, exist_ok=True)
            (root / match["file"]).write_text(match["body"], encoding="utf-8")


def _templates(nodes: list[dict]) -> list[dict]:
    found = []
    for node in nodes:
        if node["type"] == "templates":
            found.append(node)
        found.extend(_templates(node["children"]))
    return found


def _texts(nodes: list[dict]) -> str:
    return "".join(node.get("text", "") + _texts(node["children"]) for node in nodes)


def _vault(root: Path, notes: dict[str, str]) -> Path:
    for name, text in notes.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return root / "manifest.md"


FILLED = "---\nderived_from: {template: requirements, version: \"2\"}\n---\n- [[scope]]\n"
NODE = "---\nobs:\n  guidance: {contents: What it does., gate: mandatory}\n---\n\n"


def test_the_worked_example_template_shows_each_nodes_guidance_apart_from_its_slot(tmp_path: Path) -> None:
    _worked_example(tmp_path)

    document = build_document(tmp_path / "template" / "manifest.md", capability_reference())

    assert "templates" in document["capabilities"]
    [template] = _templates(document["manifest"]["abstract"])
    assert template["attrs"] == {"part": "template", "name": "requirements", "version": "2",
                                 "source": "an exported requirements template"}
    assert [chapter["title"] for chapter in document["chapters"]] == ["Purpose", "Scope", "Risks"]
    parts = [[node["attrs"]["part"] for node in _templates(chapter["content"])] for chapter in document["chapters"]]
    assert parts == [["guidance", "slot"]] * 3
    purpose, scope, risks = (_templates(chapter["content"]) for chapter in document["chapters"])
    guidance, slot = purpose
    assert guidance["attrs"] == {"part": "guidance", "gate": "mandatory"}
    assert [(field["type"], field["attrs"]["name"], _texts(field["children"])) for field in guidance["children"]] == [
        ("field", "contents", "The problem the product solves, and for whom."),
        ("field", "motivation", "Every later section is judged against it."),
        ("field", "form", "One paragraph of at most five sentences."),
        ("field", "sources", "The product brief."),
    ]
    assert slot == {"type": "templates", "attrs": {"part": "slot"}, "children": []}
    assert [field["attrs"]["name"] for field in scope[0]["children"]] == ["contents", "form"]
    assert risks[0]["attrs"]["gate"] == "judgment"
    content = document["chapters"][0]["content"]
    assert content.index(guidance) < content.index(slot)
    assert "{{slot}}" not in _texts(content)


def test_the_worked_example_document_names_its_template_and_holds_no_guidance(tmp_path: Path) -> None:
    _worked_example(tmp_path)

    document = build_document(tmp_path / "document" / "manifest.md", capability_reference())

    [derived] = _templates(document["manifest"]["abstract"])
    assert derived["attrs"] == {"part": "derived-from", "template": "requirements", "version": "2"}
    assert [chapter["title"] for chapter in document["chapters"]] == ["Purpose", "Scope", "Risks"]
    assert all(_templates(chapter["content"]) == [] for chapter in document["chapters"])
    assert "guidance" not in repr(document["chapters"])


def test_a_filled_note_that_still_holds_a_slot_fails_naming_the_note_and_its_section(tmp_path: Path) -> None:
    manifest = _vault(tmp_path, {"manifest.md": FILLED,
                                 "scope.md": "Lead.\n\n## Boundaries\n\nText.\n\n- {{slot}}\n"})

    with pytest.raises(DocumentError, match=rf"^scope\.md: section Boundaries: .*{re.escape(OWNER)}"):
        build_document(manifest, capability_reference())


def test_a_slot_above_every_heading_names_the_chapter_title_and_one_in_code_is_no_slot(tmp_path: Path) -> None:
    manifest = _vault(tmp_path, {"manifest.md": FILLED, "scope.md": "`{{slot}}`\n\n```text\n{{slot}}\n```\n"})
    build_document(manifest, capability_reference())

    (tmp_path / "scope.md").write_text("Filled, then {{slot}}.\n\n## Later\n", encoding="utf-8")
    with pytest.raises(DocumentError, match=rf"^scope\.md: section Scope: .*{re.escape(OWNER)}"):
        build_document(manifest, capability_reference())


def test_a_note_that_carries_derived_from_is_filled_in_any_document(tmp_path: Path) -> None:
    manifest = _vault(tmp_path, {
        "manifest.md": "- [[scope]]\n",
        "scope.md": "---\nderived_from: {template: requirements, version: \"2\"}\n---\n{{slot}}\n",
    })

    with pytest.raises(DocumentError, match=rf"^scope\.md: section Scope: .*{re.escape(OWNER)}"):
        build_document(manifest, capability_reference())


def test_the_abstract_of_a_filled_manifest_names_the_documents_title(tmp_path: Path) -> None:
    manifest = _vault(tmp_path, {"manifest.md": "---\ntitle: Pump\nderived_from: {template: r, version: \"1\"}\n"
                                                "---\n- [[scope]]\n\n{{slot}}\n", "scope.md": "Text.\n"})

    with pytest.raises(DocumentError, match=rf"^manifest\.md: section Pump: .*{re.escape(OWNER)}"):
        build_document(manifest, capability_reference())


def test_guidance_outside_a_template_manifest_fails_naming_the_note_and_field(tmp_path: Path) -> None:
    manifest = _vault(tmp_path, {"manifest.md": FILLED, "scope.md": NODE + "Filled.\n"})

    with pytest.raises(DocumentError, match=rf"^scope\.md: obs\.guidance: .*{re.escape(OWNER)}"):
        build_document(manifest, capability_reference())


@pytest.mark.parametrize("body", ["Text.\n", "{{slot}}\n\n{{slot}}\n", "{{slot}}\n\nAnd {{slot}} again.\n"])
def test_a_template_node_holds_exactly_one_slot_paragraph(tmp_path: Path, body: str) -> None:
    manifest = _vault(tmp_path, {"manifest.md": "---\nobs: {template: {name: r, version: \"1\"}}\n---\n- [[scope]]\n",
                                 "scope.md": NODE + body})

    with pytest.raises(DocumentError, match=rf"^scope\.md: obs\.guidance: .*{re.escape(OWNER)}"):
        build_document(manifest, capability_reference())


def test_a_template_manifest_chapter_without_guidance_is_an_ordinary_chapter(tmp_path: Path) -> None:
    manifest = _vault(tmp_path, {"manifest.md": "---\nobs: {template: {name: r, version: \"1\"}}\n---\n- [[use]]\n",
                                 "use.md": "Copy this template, then fill each {{slot}}.\n"})

    document = build_document(manifest, capability_reference())

    assert _templates(document["chapters"][0]["content"]) == []


@pytest.mark.parametrize(("notes", "field"), [
    ({"manifest.md": "- [[scope]]\n", "scope.md": "---\nobs: {template: {name: r, version: \"1\"}}\n---\n"},
     r"obs\.template"),
    ({"manifest.md": "---\nobs: {template: {name: r, version: 1}}\n---\n"}, r"obs\.template\.version"),
    ({"manifest.md": "---\nobs: {template: {version: \"1\"}}\n---\n"}, r"obs\.template\.name"),
    ({"manifest.md": "---\nobs: {guidance: {contents: x, gate: mandatory}}\n---\n"}, r"obs\.guidance"),
    ({"manifest.md": "---\nobs: {template: {name: r, version: \"1\"}}\n---\n- [[scope]]\n",
      "scope.md": "---\nobs: {guidance: {contents: x, gate: maybe}}\n---\n{{slot}}\n"}, r"obs\.guidance\.gate"),
    ({"manifest.md": "---\nobs: {template: {name: r, version: \"1\"}}\n---\n- [[scope]]\n",
      "scope.md": "---\nobs: {guidance: {gate: mandatory}}\n---\n{{slot}}\n"}, r"obs\.guidance\.contents"),
    ({"manifest.md": "---\nderived_from: {template: r}\n---\n"}, r"derived_from\.version"),
    ({"manifest.md": "---\nderived_from: {template: r, version: \"1\", by: me}\n---\n"}, r"derived_from\.by"),
])
def test_a_malformed_template_field_fails_naming_its_field_path(tmp_path: Path, notes: dict[str, str],
                                                               field: str) -> None:
    manifest = _vault(tmp_path, notes)

    with pytest.raises(DocumentError, match=rf"\.md: {field}: .*{re.escape(OWNER)}"):
        build_document(manifest, capability_reference())
