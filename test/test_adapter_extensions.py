from pathlib import Path


SPEC = Path(__file__).parents[1] / "spec"
CAPABILITIES = SPEC / "capabilities"
EXAMPLE_NOTE = SPEC / "appendix" / "references" / "obs-html-attachment-replacement.md"
EXAMPLE_LINK = "[[obs-html-attachment-replacement|"
EXAMPLE = (
    "https://github.com/mb-89/obs-html/blob/main/spec/capabilities/"
    "attachment-replacement.md"
)
OWNER_LINK = "[[capabilities/trusted-actions#Adapter extensions"


def _body(name: str) -> str:
    return (CAPABILITIES / name).read_text(encoding="utf-8").split("---", 2)[2]


def test_trusted_actions_owns_where_adapters_document_their_extensions() -> None:
    body = _body("trusted-actions.md")
    section = body.split("## Adapter extensions", 1)[1]

    assert "`spec/capabilities/`" in section
    assert "namespace" in section
    assert EXAMPLE_LINK in section


def test_extensions_points_to_the_adapter_extension_rule() -> None:
    body = _body("extensions.md")

    assert OWNER_LINK in body
    assert EXAMPLE_LINK in body
    assert "## Adapter extensions" not in body


def test_the_example_is_a_reference_note_that_holds_its_url() -> None:
    assert f"url: {EXAMPLE}" in EXAMPLE_NOTE.read_text(encoding="utf-8")
