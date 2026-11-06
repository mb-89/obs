from pathlib import Path

from structure.naming import says_document_presentation

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
    assert flat.count("[[#Manifest contract|chapter sequence]]") >= 1


def test_no_heading_or_link_says_document_presentation() -> None:
    assert says_document_presentation("spec/design_input/input-model.md") == []


REMOTE_IMAGE_RULE = "A remote image, one whose Markdown image target is an `http` or `https` URL"


def test_the_remote_image_rule_is_stated_once_where_assets_are_defined() -> None:
    model = (ROOT / "spec" / "design_input" / "input-model.md").read_text(encoding="utf-8")
    flat = " ".join(model.split())
    assets = " ".join(" ".join(
        model.split("Images are document content, not linked sources", 1)[1].split("\n\n", 3)[1:3]
    ).split())

    assert flat.count(REMOTE_IMAGE_RULE) == 1
    assert assets.startswith(REMOTE_IMAGE_RULE)
    for clause in ("becomes a Document asset with its bytes and media type",
                   "is a warning that names the note, the field, the URL and the remedy",
                   "save the image into the vault and embed it locally",
                   "its node keeps the alt text and the URL"):
        assert clause in assets


def _grammar() -> str:
    note = (ROOT / "spec" / "design_input" / "input-model.md").read_text(encoding="utf-8")
    return note.split("#### Bases filter grammar", 1)[1].split("\n### ", 1)[0]


def test_the_grammar_says_the_core_emits_every_projection_and_points_to_their_definition() -> None:
    grammar = _grammar()

    assert "exist only in the browser" not in grammar
    assert "The core emits every projection as records of its type" in grammar
    assert "`src/obs/document.schema.json` (`$defs/record`)" in grammar


def test_the_input_model_leaves_what_counts_as_a_change_to_the_adapter() -> None:
    input_model = (ROOT / "spec" / "design_input" / "input-model.md").read_text(encoding="utf-8")

    for restatement in ("Persisted reader-state changes do", "changed-HTML state", "as changed.",
                        "or an artifact change", "column or width changes"):
        assert restatement not in input_model


UNIT_SYSTEM = "Quantities carry a unit system"


def test_the_unit_system_is_stated_once_in_numeric_value_notes() -> None:
    model = (ROOT / "spec" / "design_input" / "input-model.md").read_text(encoding="utf-8")
    section = " ".join(model.split("### Numeric-value notes", 1)[1].split("\n### ", 1)[0].split())
    flat = " ".join(model.split())

    assert UNIT_SYSTEM in section and flat.count(UNIT_SYSTEM) == 1
    assert "[[capabilities/quantities]]" in section
    assert "Numeric notes will carry a unit system" not in flat
    assert "nodes-numeric-system" not in flat
    assert "designed separately" not in section


def test_the_core_spec_names_every_figure_kind_and_carries_no_plot_evaluator_of_its_own() -> None:
    """The equations kind replaced the interim's equation plot, whose bounded arithmetic language
    and sampling the core never had (input-model, Equation figures); the interim's own module
    documents it until obs#3."""
    from obs.figure import FIGURE_KINDS

    model = (ROOT / "spec" / "design_input" / "input-model.md").read_text(encoding="utf-8")
    direction = model.split("#### Figure input direction", 1)[1].split("\n#### ", 1)[0]
    figures = (ROOT / "spec" / "capabilities" / "figures.md").read_text(encoding="utf-8")
    core_spec = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "spec").rglob("*.md")
                          if "design_output" not in path.parts)

    for kind in FIGURE_KINDS:
        assert f"`{kind}`" in direction and f"`{kind}`" in figures, kind
    for evaluator in ("`samples`", "`traces`", "bounded arithmetic expression language", "parameters.json"):
        assert evaluator not in core_spec, evaluator


def test_the_null_chapter_rule_points_to_its_owner_wikilinks() -> None:
    model = (ROOT / "spec" / "design_input" / "input-model.md").read_text(encoding="utf-8")
    flat = " ".join(model.split())

    assert "`null` remains only for a target that does not exist" not in flat, (
        "input-model.md: point to [[capabilities/wikilinks#Document node]] instead of restating when "
        "`attrs.chapter` is `null`"
    )
    assert "`null` follows [[capabilities/wikilinks#Document node]]" in flat
