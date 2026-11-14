import json
import re
from pathlib import Path

from jsonschema import validate
import yaml

from obs.capabilities import build_capability_reference
from obs.figure import FIGURE_KINDS, validate_figure_descriptor


ROOT = Path(__file__).parents[1]
CAPABILITIES = ROOT / "spec" / "capabilities"


def _frontmatter(path: Path) -> dict[str, object]:
    _, raw, _ = path.read_text(encoding="utf-8").split("---", 2)
    return yaml.safe_load(raw)


def test_capability_notes_own_their_authored_contract() -> None:
    notes = [
        path for path in sorted(CAPABILITIES.glob("*.md"))
        if _frontmatter(path).get("kind") == "capability"
    ]

    assert notes
    identifiers = set()
    for path in notes:
        frontmatter = _frontmatter(path)
        body = path.read_text(encoding="utf-8").split("---", 2)[2]
        capability = frontmatter["capability"]

        assert set(capability) == {"id", "summary", "authoring", "dependsOn", "source"}
        assert isinstance(capability["id"], str) and capability["id"]
        assert capability["id"] not in identifiers
        assert isinstance(capability["summary"], str) and capability["summary"]
        assert isinstance(capability["authoring"], str) and capability["authoring"]
        assert all(
            re.fullmatch(r"\[\[capabilities/[a-z][a-z0-9-]*\]\]", dependency)
            for dependency in capability["dependsOn"]
        )
        assert capability["source"].startswith("[[input-model#")
        assert "## What it does" in body
        assert "## Authoring example" in body
        assert "```markdown" in body
        fences = re.findall(r"^(`{3,})", body, flags=re.MULTILINE)
        open_fences = []
        for fence in fences:
            if open_fences and fence == open_fences[-1]:
                open_fences.pop()
            else:
                open_fences.append(fence)
        assert open_fences == []

        identifiers.add(capability["id"])

    dependencies = {
        dependency
        for path in notes
        for dependency in _frontmatter(path)["capability"]["dependsOn"]
    }
    assert {
        dependency.removeprefix("[[capabilities/").removesuffix("]]")
        for dependency in dependencies
    } <= identifiers


def test_specification_registers_capabilities_as_an_authored_base(spec_document) -> None:
    """The spec's capability reference chapter holds one Bases table of every capability note, and
    the Document carries a record of kind capability for each of them."""
    def chapters(items):
        for chapter in items:
            yield chapter
            yield from chapters(chapter["children"])

    reference = next(chapter for chapter in chapters(spec_document["chapters"]) if chapter["id"] == "capability-reference")
    [definition] = [node["attrs"]["spec"] for node in reference["content"] if node["type"] == "bases"]

    assert definition["filters"] == 'kind == "capability"'
    assert definition["views"] == [{
        "type": "table",
        "name": "Capabilities",
        "order": ["capability.id", "capability.summary", "capability.authoring", "capability.dependsOn"],
    }]
    assert {
        Path(record["path"]).stem for record in spec_document["records"]
        if record["type"] == "note" and record["path"].startswith("capabilities/")
        and record["fields"].get("kind") == "capability"
    } == {
        path.stem for path in CAPABILITIES.glob("*.md")
        if _frontmatter(path).get("kind") == "capability"
    }


def test_capability_reference_is_schema_valid_and_covers_the_input_model() -> None:
    coverage = CAPABILITIES / "coverage.json"
    reference = build_capability_reference(CAPABILITIES, coverage)
    schema = json.loads((ROOT / "src" / "obs" / "capabilities.schema.json").read_text(encoding="utf-8-sig"))

    validate(reference, schema)

    referenced_sections = {
        capability["source"].removesuffix("]]").split("#", 1)[1]
        for capability in reference["capabilities"]
    }
    assert referenced_sections == {
        heading for heading, classification in json.loads(coverage.read_text(encoding="utf-8"))["sections"].items()
        if classification == "input"
    }


def test_figure_descriptor_capability_examples_show_each_data_shape_schema_valid() -> None:
    note = (CAPABILITIES / "figure-descriptor.md").read_text(encoding="utf-8")
    [example] = re.findall(r"^````markdown\n(.*?)^````$", note, flags=re.DOTALL | re.MULTILINE)
    fences = [yaml.safe_load(body) for body in re.findall(r"```figure\n(.*?)\n```", example, flags=re.DOTALL)]

    assert all(fence["kind"] == "plot" for fence in fences)
    for fence in fences:
        validate_figure_descriptor(fence["content"])
    assert sorted(shape for fence in fences for shape in fence["content"]["data"]
                  if shape != "countLabels") == ["sankey", "traces"]


def _nodes(nodes):
    for node in nodes:
        yield node
        yield from _nodes(node.get("children", []))


def _chapters(chapters):
    for chapter in chapters:
        yield chapter
        yield from _chapters(chapter.get("children", []))


def test_the_spec_shows_one_real_figure_descriptor_in_its_capability_note(spec_document) -> None:
    [node_type] = [kind for kind, figure in FIGURE_KINDS.items() if figure.capability == "figure-descriptor"]
    shown = [(chapter["id"], node) for chapter in _chapters(spec_document["chapters"])
             for node in _nodes(chapter["content"]) if node["type"] == node_type]

    assert [chapter for chapter, _ in shown] == ["capabilities-figure-descriptor"]
    validate_figure_descriptor(shown[0][1]["attrs"]["descriptor"])
    assert "figure-descriptor" in spec_document["capabilities"]


def test_adapter_notes_can_depend_on_a_supplied_reference(tmp_path) -> None:
    notes = tmp_path / "adapter"
    notes.mkdir()
    (notes / "feature.md").write_text(
        "---\nkind: capability\ncapability:\n  id: adapter-feature\n"
        "  summary: Adapter feature.\n  authoring: Example.\n"
        "  dependsOn: [\"[[core/manifest]]\"]\n  source: \"[[adapter-doc#Feature]]\"\n---\n",
        encoding="utf-8",
    )
    external = tmp_path / "core.json"
    external.write_text(json.dumps({"schemaVersion": 1, "capabilities": [{"id": "manifest"}]}), encoding="utf-8")

    reference = build_capability_reference(notes, references=[external])

    assert reference["capabilities"][0]["dependsOn"] == ["manifest"]


def test_the_packaged_capability_reference_is_current_with_the_capability_notes() -> None:
    """The build writes it from spec/capabilities (hatch_build.py); `uv sync` writes it again."""
    from importlib.resources import files

    packaged = json.loads(files("obs").joinpath("capability-reference.json").read_text(encoding="utf-8"))

    assert packaged == build_capability_reference(CAPABILITIES, CAPABILITIES / "coverage.json"), (
        "src/obs/capability-reference.json is stale against spec/capabilities; remedy: uv sync "
        "--reinstall-package obs, which writes it again from the notes (hatch_build.py)")


SKILL = ROOT / "skills" / "obs-authoring"
"""The authoring skill, generated from the capability notes (spec/design_input/cli.md, Authoring skill)."""


def _committed_skill() -> dict[str, str]:
    return {path.relative_to(SKILL).as_posix(): path.read_text(encoding="utf-8")
            for path in sorted(SKILL.rglob("*")) if path.is_file()}


def test_the_authoring_skill_is_current_with_the_capability_notes() -> None:
    from obs.authoring_skill import REGENERATE, build_skill

    generated = build_skill(CAPABILITIES, CAPABILITIES / "coverage.json")

    assert _committed_skill() == generated, (
        f"skills/obs-authoring is stale against spec/capabilities; remedy: {REGENERATE}")


def test_the_authoring_skill_check_fails_on_a_changed_authoring_line_or_example(tmp_path) -> None:
    """The check above compares the committed folder with the notes: a changed authoring line or
    example changes what the notes generate, so the committed folder no longer equals it."""
    import shutil
    from obs.authoring_skill import build_skill

    for old, new in (("authoring: Use a base fence", "authoring: Write a base fence"),
                     ("    order: [file.name]", "    order: [file.path]")):
        notes = tmp_path / old.split(":")[0].strip()
        shutil.copytree(CAPABILITIES, notes)
        bases = notes / "bases.md"
        text = bases.read_text(encoding="utf-8")
        assert old in text
        bases.write_text(text.replace(old, new), encoding="utf-8")

        generated = build_skill(notes, notes / "coverage.json")

        assert generated != _committed_skill()
        assert new.split(": ", 1)[-1].strip() in generated["references/capabilities.md"]


def test_the_authoring_skill_follows_the_agent_skills_format() -> None:
    """Agent Skills (agentskills.io): the name equals the folder's name, lowercase and hyphenated; a
    description under 1,024 characters; a body under 500 lines; reference files one level deep;
    every link stays inside the folder and finds its file and heading."""
    files = _committed_skill()
    _, raw, body = files["SKILL.md"].split("---", 2)
    frontmatter = yaml.safe_load(raw)

    assert frontmatter["name"] == SKILL.name
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", frontmatter["name"]) and len(frontmatter["name"]) <= 64
    assert 0 < len(frontmatter["description"]) < 1024 and "Use when" in frontmatter["description"]
    assert len(body.splitlines()) < 500
    assert all(path == "SKILL.md" or re.fullmatch(r"references/[^/]+\.md", path) for path in files)

    for path, text in files.items():
        prose = re.sub(r"^(`{3,})[^\n]*\n.*?^\1[ \t]*$", "", text, flags=re.M | re.S)
        for target in re.findall(r"\]\(([^)\s]+)\)", prose):
            file, _, anchor = target.partition("#")
            resolved = (Path(path).parent / file).as_posix() if file else path
            assert "://" not in target and not file.startswith("/") and ".." not in Path(resolved).parts, (path, target)
            assert resolved in files, (path, target)
            if anchor:
                headings = re.findall(r"^#{1,6} (.+)$", re.sub(r"^(`{3,})[^\n]*\n.*?^\1[ \t]*$", "",
                                                               files[resolved], flags=re.M | re.S), re.M)
                assert anchor in {re.sub(r"[^a-z0-9 -]", "", heading.lower()).replace(" ", "-")
                                  for heading in headings}, (path, target)
