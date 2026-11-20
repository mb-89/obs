from structure.naming import ROOT, says_document_presentation

NOTE = "spec/capabilities/profiles.md"


def test_no_capability_id_heading_or_link_says_document_presentation() -> None:
    assert says_document_presentation(NOTE) == []


def test_profiles_select_note_and_artifact_presentation() -> None:
    text = (ROOT / NOTE).read_text(encoding="utf-8")

    assert text.count("Select constrained note and artifact presentation profiles.") == 2
    assert "document presentation" not in text.lower()
