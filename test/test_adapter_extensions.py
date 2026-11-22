from pathlib import Path


SPEC = Path(__file__).parents[1] / "spec"
CAPABILITIES = SPEC / "capabilities"
INPUT_MODEL = SPEC / "design_input" / "input-model.md"
OWNER_LINK = "[[input-model#Adapter extensions"


def _body(name: str) -> str:
    return (CAPABILITIES / name).read_text(encoding="utf-8").split("---", 2)[2]


def test_the_input_model_owns_where_adapters_document_their_extensions() -> None:
    section = INPUT_MODEL.read_text(encoding="utf-8").split("### Adapter extensions", 1)[1].split("\n## ", 1)[0]

    assert "`spec/capabilities/`" in section
    assert "namespace" in section


def test_extensions_points_to_the_adapter_extension_rule() -> None:
    body = _body("extensions.md")

    assert OWNER_LINK in body
    assert "## Adapter extensions" not in body
