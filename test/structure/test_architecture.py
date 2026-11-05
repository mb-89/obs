from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_document_adapter_contract_points_to_note_records() -> None:
    architecture = (ROOT / "spec" / "design_input" / "architecture.md").read_text(encoding="utf-8")
    contract = architecture.split("## Document-adapter contract", 1)[1].split("\n## ", 1)[0]

    assert "[[capabilities/bases#Note records|" in contract


def test_architecture_links_the_document_to_the_glossary() -> None:
    architecture = (ROOT / "spec" / "design_input" / "architecture.md").read_text(encoding="utf-8")
    assert "[[quality#Glossary|" in architecture


def test_document_adapter_contract_records_why_assets_carry_their_bytes() -> None:
    architecture = (ROOT / "spec" / "design_input" / "architecture.md").read_text(encoding="utf-8")
    contract = architecture.split("## Document-adapter contract", 1)[1].split("\n## ", 1)[0]
    decision = contract.split("### Asset bytes", 1)[1]

    assert "base64 `data`" in decision
    assert "asset root" in decision
    assert "[[product#Goals]]" in decision
