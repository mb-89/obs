from pathlib import Path

from obs_html.content import _split_frontmatter


ROOT = Path(__file__).parents[1]
CAPABILITIES = ROOT / "spec" / "capabilities"


def test_capability_notes_own_their_authored_contract() -> None:
    notes = sorted(CAPABILITIES.glob("*.md"))

    assert notes
    identifiers = set()
    for path in notes:
        frontmatter, body = _split_frontmatter(path.read_text(encoding="utf-8"), path)
        capability = frontmatter["capability"]

        assert set(capability) == {"id", "summary", "authoring", "dependsOn", "inputModel"}
        assert isinstance(capability["id"], str) and capability["id"]
        assert capability["id"] not in identifiers
        assert isinstance(capability["summary"], str) and capability["summary"]
        assert isinstance(capability["authoring"], str) and capability["authoring"]
        assert isinstance(capability["dependsOn"], list)
        assert capability["inputModel"].startswith("[[input-model#")
        assert body.strip()

        identifiers.add(capability["id"])

    dependencies = {
        dependency
        for path in notes
        for dependency in _split_frontmatter(path.read_text(encoding="utf-8"), path)[0][
            "capability"
        ]["dependsOn"]
    }
    assert dependencies <= identifiers
