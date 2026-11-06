"""Links inside a figure's SVG: an authored SVG's a element or wikilink text, a Mermaid click and a
PlantUML [[...]] link resolve like a prose link, include their note and warn or fail like one.

Reader: whoever changes how the core reads a figure's links (capabilities/wikilinks, Links inside
a figure; src/obs/svg_links.py).

The vault is built once for the module, and the module runs on the worker of the diagram tests,
so its diagrams are drawn in their browser session.
"""
from pathlib import Path

import pytest

from obs.document import DocumentError, build_document

from test_vault import capability_reference


SVG = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
       'viewBox="0 0 100 40"><text x="2" y="12">See [[target]] and [[other#Detail|the detail]]</text>'
       '<a xlink:href="drawn.md"><rect x="0" y="20" width="10" height="10"/></a>'
       '<a href="https://example.org/"><rect x="20" y="20" width="10" height="10"/></a>'
       '<a href="#local"><rect x="40" y="20" width="10" height="10"/></a></svg>')
CHAPTER = f"""# Figures

```figure
version: 1
kind: svg
caption: A drawing that links its notes.
content: '{SVG}'
```
^drawing

```mermaid
flowchart LR
  A[Alpha] --> B[Beta]
  click A href "mermaid-target.md"
```

```plantuml
@startuml
class Alpha [[plantuml-target]]
@enduml
```
"""
pytestmark = pytest.mark.xdist_group("test/test_diagram_figures.py")
NOTES = ("target", "other", "drawn", "mermaid-target", "plantuml-target")


def _vault(root: Path, chapter: str, notes: tuple[str, ...] = NOTES) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (root / "chapter.md").write_text(chapter, encoding="utf-8")
    for name in notes:
        (root / f"{name}.md").write_text(f"# {name}\n\n## Detail\n", encoding="utf-8")
    return root / "manifest.md"


@pytest.fixture(scope="module")
def document(tmp_path_factory) -> dict:
    return build_document(_vault(tmp_path_factory.mktemp("figure-links"), CHAPTER), capability_reference())


def _figure_links(document: dict) -> list[list[dict]]:
    chapter = next(chapter for chapter in document["chapters"] if chapter["id"] == "chapter")
    return [[link["attrs"] for link in node["children"][0]["children"]]
            for node in chapter["content"] if node["type"] == "figures"]


def test_an_authored_svg_s_wikilinks_and_a_elements_are_document_links_that_include_their_notes(document) -> None:
    svg, _, _ = _figure_links(document)

    assert svg == [
        {"target": "target", "heading": "", "label": "target", "chapter": "target", "svg": "[[target]]"},
        {"target": "other", "heading": "Detail", "label": "the detail", "chapter": "other",
         "svg": "[[other#Detail|the detail]]"},
        {"target": "drawn.md", "heading": "", "label": "drawn.md", "chapter": "drawn", "svg": "drawn.md"},
    ]
    assert {"target", "other", "drawn"} <= {chapter["id"] for chapter in document["chapters"]}
    assert "wikilinks" in document["capabilities"]
    assert document["diagnostics"] == []


def test_a_mermaid_click_and_a_plantuml_link_are_document_links_that_include_their_notes(document) -> None:
    _, mermaid, plantuml = _figure_links(document)

    assert [link["target"] for link in mermaid] == ["mermaid-target.md"]
    assert [link["chapter"] for link in mermaid] == ["mermaid-target"]
    assert [(link["target"], link["chapter"]) for link in plantuml] == [("plantuml-target", "plantuml-target")]
    assert {"mermaid-target", "plantuml-target"} <= {chapter["id"] for chapter in document["chapters"]}


def test_a_link_to_a_missing_note_inside_a_figure_warns_like_prose_naming_note_figure_and_target(tmp_path) -> None:
    chapter = CHAPTER.split("```mermaid")[0]

    document = build_document(_vault(tmp_path, chapter, ("other", "drawn")), capability_reference())

    assert [link["chapter"] for link in _figure_links(document)[0]] == [None, "other", "drawn"]
    [warning] = [diagnostic["message"] for diagnostic in document["diagnostics"]]
    assert "chapter.md" in warning and "figure fence 1" in warning and "[[target]]" in warning


def test_an_ambiguous_link_inside_a_figure_fails_the_build_naming_note_figure_and_target(tmp_path) -> None:
    manifest = _vault(tmp_path, CHAPTER.split("```mermaid")[0], ("other", "drawn"))
    for folder in ("a", "b"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "target.md").write_text("# target\n", encoding="utf-8")

    with pytest.raises(DocumentError) as raised:
        build_document(manifest, capability_reference())

    assert "chapter.md" in str(raised.value) and "figure fence 1" in str(raised.value)
    assert "[[target]]" in str(raised.value)


def test_a_block_link_inside_a_figure_targets_its_figure_like_prose(tmp_path) -> None:
    chapter = CHAPTER.split("```mermaid")[0].replace("[[target]] and", "[[#^drawing]] and")

    document = build_document(_vault(tmp_path, chapter), capability_reference())

    first = _figure_links(document)[0][0]
    assert (first["target"], first["chapter"], first["figure"], first["svg"]) == (
        "", "chapter", "drawing", "[[#^drawing]]")
