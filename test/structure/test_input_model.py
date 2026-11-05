from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_markdown_body_section_points_to_the_markdown_document_nodes() -> None:
    model = (ROOT / "spec" / "design_input" / "input-model.md").read_text(encoding="utf-8")
    section = model.split("### Markdown body and frontmatter", 1)[1].split("\n### ", 1)[0]

    assert "[[capabilities/markdown#Document nodes]]" in section
    assert "structuralType" not in section


def test_chapter_content_states_the_one_contract_failure_message_form() -> None:
    model = (ROOT / "spec" / "design_input" / "input-model.md").read_text(encoding="utf-8")
    section = model.split("## Chapter content", 1)[1].split("\n## ", 1)[0]

    assert section.count("`<note path>: <field path>: <what is wrong>. <remedy>`") == 1
    assert "One formatter in the core" in section


CHAPTER_RULE = "A chapter is a non-hidden line of the manifest's TOC list"


def test_chapter_sequence_is_stated_once_in_the_manifest_contract() -> None:
    model = (ROOT / "spec" / "design_input" / "input-model.md").read_text(encoding="utf-8")
    contract = " ".join(model.split("\n## Manifest contract\n", 1)[1].split("\n## ", 1)[0].split())
    flat = " ".join(model.split())

    assert CHAPTER_RULE in contract
    assert flat.count(CHAPTER_RULE) == 1
    for clause in ("The table of contents and previous/next walk exactly the chapters, in manifest order",
                   "A note reached only through a link is not a chapter, gets no previous/next, "
                   "and stays reachable through its link."):
        assert clause in contract
    for restatement in ("Previous and next navigation follows that sequence in depth-first order.",
                        "Left and right controls move through all items in depth-first manifest order.",
                        "Unlisted notes never become TOC children or previous/next chapter stops."):
        assert restatement not in flat, f"input-model.md: point to [[#Manifest contract]] instead of '{restatement}'"
    assert flat.count("[[#Manifest contract|chapter sequence]]") >= 2
