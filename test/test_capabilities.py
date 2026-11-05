import json
import re
from pathlib import Path

from jsonschema import validate

from obs_html.capabilities import build_capability_reference
from obs_html.content import Chapter, _split_frontmatter, collect_notes, read_chapter_content, read_manifest


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


def test_specification_registers_capabilities_as_an_authored_base() -> None:
    manifest_path = ROOT / "spec" / "manifest.md"
    manifest = read_manifest(manifest_path)
    home = Chapter(0, "Home", "home", manifest_path, "", "home")
    home_document = read_chapter_content(home, manifest.metadata["subtitle"])
    notes, documents, _ = collect_notes(
        manifest_path, manifest.chapters, home, home_document, manifest.metadata,
    )

    reference = next(note for note in notes if note.slug == "capability-reference")
    definition = documents[reference.source_path].tables[0].definition

    assert definition["filters"] == 'kind == "capability"'
    assert definition["views"] == [{
        "type": "table",
        "name": "Capabilities",
        "order": ["capability.id", "capability.summary", "capability.authoring", "capability.dependsOn"],
    }]
    assert {
        note.source_path.stem for note in notes
        if documents[note.source_path].frontmatter.get("kind") == "capability"
    } == {
        path.stem for path in CAPABILITIES.glob("*.md")
    }


def test_capability_reference_is_schema_valid_and_covers_the_input_model() -> None:
    reference = build_capability_reference(CAPABILITIES, ROOT / "spec" / "design_input" / "input-model.md")
    schema = json.loads((ROOT / "src" / "obs_html" / "capabilities.schema.json").read_text(encoding="utf-8"))

    validate(reference, schema)

    headings = set(re.findall(
        r"^#{2,3} (.+)$",
        (ROOT / "spec" / "design_input" / "input-model.md").read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    ))
    referenced_sections = {
        capability["inputModel"].removesuffix("]]").split("#", 1)[1]
        for capability in reference["capabilities"]
    }
    assert headings <= referenced_sections
