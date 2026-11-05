from pathlib import Path


CAPABILITIES = Path(__file__).parents[1] / "spec" / "capabilities"
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


def test_extensions_points_to_the_adapter_extension_rule() -> None:
    body = _body("extensions.md")

    assert OWNER_LINK in body
    assert "## Adapter extensions" not in body
