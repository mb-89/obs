from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_markdown_body_section_points_to_the_markdown_document_nodes() -> None:
    model = (ROOT / "spec" / "design_input" / "input-model.md").read_text(encoding="utf-8")
    section = model.split("### Markdown body and frontmatter", 1)[1].split("\n### ", 1)[0]

    assert "[[capabilities/markdown#Document nodes]]" in section
    assert "structuralType" not in section
