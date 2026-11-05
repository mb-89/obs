"""Every capability note's authoring example is valid input; see capability-reference."""
from pathlib import Path
import re

import pytest
import yaml

from obs.document import DocumentError, build_document
from test_vault import INPUT_CAPABILITY_GAPS, capability_reference


ROOT = Path(__file__).parents[1]
CAPABILITIES = ROOT / "spec" / "capabilities"
FENCE = re.compile(r"^(?P<fence>`{3,})(?P<language>\S*)[^\n]*\n(?P<body>.*?)^(?P=fence)[ \t]*$", re.M | re.S)


def _examples() -> list:
    examples = []
    for path in sorted(CAPABILITIES.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        identifier = yaml.safe_load(text.split("---", 2)[1])["capability"]["id"]
        for match in FENCE.finditer(text):
            if match["language"] == "markdown":
                line = text.count("\n", 0, match.start()) + 1
                place = f"{path.relative_to(ROOT).as_posix()}:{line}"
                examples.append(pytest.param(place, identifier, match["body"], id=place))
    return examples


def _note(example: str) -> str:
    """A Markdown example that is a YAML mapping alone is a frontmatter fragment."""
    try:
        fragment = isinstance(yaml.safe_load(example), dict) and not example.startswith("---\n")
    except yaml.YAMLError:
        fragment = False
    return f"---\n{example}---\n" if fragment else example


def _read(tmp_path: Path, example: str) -> dict[str, object]:
    (tmp_path / "example.md").write_text(_note(example), encoding="utf-8")
    (tmp_path / "manifest.md").write_text("- [[example]]\n", encoding="utf-8")
    return build_document(tmp_path / "manifest.md", capability_reference())


@pytest.mark.parametrize(("place", "capability", "example"), _examples())
def test_every_capability_example_is_input_the_core_reads_as_its_capability(
    tmp_path: Path, place: str, capability: str, example: str,
) -> None:
    try:
        document = _read(tmp_path, example)
    except DocumentError as error:
        pytest.fail(f"Authoring example at {place} is not valid input: {error}")

    if capability in INPUT_CAPABILITY_GAPS:
        assert capability not in document["capabilities"], (
            f"Authoring example at {place} is a counter-example, yet the core reads it as "
            f"{capability}; give the capability its input contract or correct the example."
        )
        return
    assert capability in document["capabilities"], (
        f"Authoring example at {place} does not use capability {capability}; "
        f"the core reads it as {sorted(document['capabilities'])}."
    )


def test_a_frontmatter_fragment_is_read_as_frontmatter_and_its_schema_error_is_reported(tmp_path: Path) -> None:
    with pytest.raises(DocumentError, match="'count' was unexpected"):
        _read(tmp_path, "query:\n  count: true\n  where: [{field: status, equals: open}]\n")
