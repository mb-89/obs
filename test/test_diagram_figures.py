"""Diagram figures: a Mermaid or PlantUML fence becomes a figure whose body is the SVG drawn at
build time, in a local browser, with no network.

Reader: whoever changes the diagram kinds or their renderers (input-model, Figure input
direction; capabilities/mermaid, capabilities/plantuml; src/obs/diagram.py).

The vault is built once for the module, so its diagrams are drawn in one browser session; the
error cases reuse that session. The network guard (test/conftest.py) fails a test whose process
reaches the network; the renderers' page refuses every request it does not serve from the
installed packages.
"""
from pathlib import Path
from xml.etree import ElementTree

import pytest

from obs import diagram
from obs.document import DocumentError, build_document

from test_vault import capability_reference


FLOW = "graph TD\n  Draft --> Review\n  Review -->|approved| Done\n"
SEQUENCE = "@startuml\nAuthor -> Reviewer : request review\nReviewer --> Author : approve\n@enduml\n"
CHAPTER = f"""---
title: Diagrams
---
# Diagrams

```mermaid
{FLOW}```

```plantuml
{SEQUENCE}```

```figure
version: 1
kind: mermaid
caption: The review flow, from its file.
source: diagrams/flow.mmd
```
^flow-file

```figure
version: 1
kind: mermaid
caption: The review flow, inline.
content: |
{"".join("  " + line + chr(10) for line in FLOW.splitlines())}```
^flow-inline

```figure
version: 1
kind: plantuml
source: diagrams/sequence.puml
```

```figure
version: 1
kind: plantuml
content: |
{"".join("  " + line + chr(10) for line in SEQUENCE.splitlines())}```
"""


def _vault(root: Path, chapter: str, files: dict[str, str] | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (root / "chapter.md").write_text(chapter, encoding="utf-8")
    for name, text in (files or {}).items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return root / "manifest.md"


@pytest.fixture(scope="module")
def figures(tmp_path_factory) -> list[dict]:
    manifest = _vault(tmp_path_factory.mktemp("diagrams"), CHAPTER,
                      {"diagrams/flow.mmd": FLOW, "diagrams/sequence.puml": SEQUENCE})
    document = build_document(manifest, capability_reference())
    assert {"figures", "mermaid", "plantuml"} <= set(document["capabilities"])
    return [node for node in document["chapters"][0]["content"] if node["type"] == "figures"]


def _svg(body: dict) -> ElementTree.Element:
    return ElementTree.fromstring(body["attrs"]["svg"])


def test_plain_mermaid_and_plantuml_fences_are_figures_whose_bodies_are_svg_drawn_at_build_time(figures) -> None:
    mermaid, plantuml = figures[:2]

    assert [mermaid["attrs"], plantuml["attrs"]] == [{"kind": "mermaid"}, {"kind": "plantuml"}]
    [mermaid_body], [plantuml_body] = mermaid["children"], plantuml["children"]
    assert [mermaid_body["type"], plantuml_body["type"]] == ["mermaid", "plantuml"]
    assert [mermaid_body["attrs"]["source"], plantuml_body["attrs"]["source"]] == [FLOW, SEQUENCE]
    assert {_svg(mermaid_body).tag, _svg(plantuml_body).tag} == {"{http://www.w3.org/2000/svg}svg"}
    assert "Review" in "".join(_svg(mermaid_body).itertext())
    assert "Reviewer" in "".join(_svg(plantuml_body).itertext())


def test_a_figure_fence_of_a_diagram_kind_adds_a_caption_and_a_block_id(figures) -> None:
    from_file = figures[2]

    assert from_file["attrs"]["kind"] == "mermaid"
    assert from_file["attrs"]["block"] == "flow-file"
    assert from_file["attrs"]["caption"][0]["type"] == "paragraph"


def test_the_same_diagram_inline_and_from_a_file_gives_identical_svg(figures) -> None:
    plain_flow, plain_sequence, flow_file, flow_inline, sequence_file, sequence_inline = figures

    assert flow_file["children"] == flow_inline["children"] == plain_flow["children"]
    assert sequence_file["children"] == sequence_inline["children"] == plain_sequence["children"]
    # Drawn again, not from the process's cache: the drawing depends on the text alone.
    assert diagram.render.__wrapped__("mermaid", FLOW) == flow_file["children"][0]["attrs"]["svg"]
    assert diagram.render.__wrapped__("plantuml", SEQUENCE) == sequence_file["children"][0]["attrs"]["svg"]


def _error(tmp_path: Path, chapter: str, files: dict[str, str] | None = None) -> str:
    with pytest.raises(DocumentError) as raised:
        build_document(_vault(tmp_path, chapter, files), capability_reference())
    return str(raised.value)


def test_a_mermaid_syntax_error_names_the_note_and_its_line(figures, tmp_path) -> None:
    message = _error(tmp_path, "---\ntitle: Broken\n---\n# Broken\n\n```mermaid\ngraph TD\n  A -->\n  B --> --> C\n```\n")

    assert message.startswith(f"{tmp_path / 'chapter.md'}: line 9, mermaid fence 1: ")
    assert message.endswith("; see capabilities/mermaid.")


def test_a_plantuml_syntax_error_in_inline_content_names_the_note_and_its_line(figures, tmp_path) -> None:
    message = _error(tmp_path, "# Broken\n\n```figure\nversion: 1\nkind: plantuml\ncontent: |\n"
                               "  @startuml\n  class A {\n  @enduml\n```\n")

    assert message.startswith(f"{tmp_path / 'chapter.md'}: line 8, figure fence 1, content: ")
    assert message.endswith("; see capabilities/plantuml.")


def test_a_syntax_error_in_a_source_file_names_the_note_the_fence_and_the_files_line(figures, tmp_path) -> None:
    message = _error(tmp_path, "# Broken\n\n```figure\nversion: 1\nkind: mermaid\nsource: broken.mmd\n```\n",
                     {"broken.mmd": "graph TD\n  A -->\n  B --> --> C\n"})

    assert message.startswith(f"{tmp_path / 'chapter.md'}: line 3, figure fence 1, source, line 3: ")
    assert message.endswith("; see capabilities/mermaid.")


def test_a_missing_renderer_names_the_install_command(figures, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(diagram, "PACKAGE", tmp_path / "not-installed")
    message = _error(tmp_path / "vault", "# Missing\n\n```plantuml\n@startuml\nMissing -> Renderer\n@enduml\n```\n")

    assert message.startswith(f"{tmp_path / 'vault' / 'chapter.md'}: line 3, plantuml fence 1: ")
    assert f"'npm --prefix {tmp_path / 'not-installed'} ci'" in message
    assert message.endswith("; see capabilities/plantuml.")
