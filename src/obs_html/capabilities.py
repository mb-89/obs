"""Generate the language-neutral capability reference from its owning notes."""

import argparse
import json
import re
from pathlib import Path
from typing import Sequence

import yaml


INPUT_MODEL_CLASSIFICATION = {
    "Trusted presentation projections": "adapter",
    "Manifest contract": "input",
    "Document home and abstract": "input",
    "Profiles": "input",
    "Document presentation profile": "adapter",
    "Registers": "input",
    "Report behavior": "adapter",
    "Optional reproduction archive": "adapter",
    "Cover metadata and history": "adapter",
    "Chapter content": "input",
    "Callouts": "input",
    "Reusable query ownership": "input",
    "Numeric-value notes": "input",
    "Reference notes and link text": "input",
    "Remaining chapter content": "input",
    "Markdown body and frontmatter": "input",
    "Mark tags": "input",
    "Base fences": "input",
    "Bottom line and glossary": "input",
    "Command-derived content": "input",
    "Reviewed copy": "adapter",
    "One count query": "input",
    "Next Obsidian extension": "input",
    "Canonical reference presentation": "adapter",
    "Named icon resources": "adapter",
    "Compact declarative table presentation": "adapter",
    "Shared source-archive link": "adapter",
    "Trusted runtime and canonical replacement": "adapter",
    "Trusted floating-content actions": "adapter",
    "Current source projection after a trusted update": "adapter",
}


def _frontmatter(path: Path) -> dict[str, object]:
    source = path.read_text(encoding="utf-8")
    if not source.startswith("---\n"):
        raise ValueError(f"Capability note has no frontmatter: {path}")
    _, raw, _ = source.split("---", 2)
    loaded = yaml.safe_load(raw)
    if not isinstance(loaded, dict):
        raise ValueError(f"Capability frontmatter is not a mapping: {path}")
    return loaded


def build_capability_reference(notes_root: Path, input_model: Path) -> dict[str, object]:
    """Return the validated capability document owned by the supplied Markdown notes."""
    capabilities = []
    for path in sorted(notes_root.glob("*.md")):
        frontmatter = _frontmatter(path)
        if frontmatter.get("kind") != "capability":
            continue
        capability = frontmatter.get("capability")
        if not isinstance(capability, dict):
            raise ValueError(f"Capability note has no capability mapping: {path}")
        document = {key: capability[key] for key in (
            "id", "summary", "authoring", "dependsOn", "inputModel",
        )}
        dependencies = document["dependsOn"]
        if not isinstance(dependencies, list):
            raise ValueError(f"Capability dependencies must be a list: {path}")
        document["dependsOn"] = [
            _dependency_identifier(dependency, path) for dependency in dependencies
        ]
        capabilities.append(document)

    identifiers = [capability["id"] for capability in capabilities]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Capability identifiers must be unique.")
    missing_dependencies = sorted({
        dependency
        for capability in capabilities
        for dependency in capability["dependsOn"]
        if dependency not in identifiers
    })
    if missing_dependencies:
        raise ValueError(f"Capability dependencies do not exist: {', '.join(missing_dependencies)}")

    headings = set(re.findall(
        r"^#{2,3} (.+)$", input_model.read_text(encoding="utf-8"), flags=re.MULTILINE,
    ))
    if headings != set(INPUT_MODEL_CLASSIFICATION):
        raise ValueError("Input-model capability classification does not cover its headings.")
    referenced_sections = {
        capability["inputModel"].removesuffix("]]").split("#", 1)[1]
        for capability in capabilities
    }
    expected_sections = {
        heading for heading, classification in INPUT_MODEL_CLASSIFICATION.items()
        if classification == "input"
    }
    missing_sections = sorted(expected_sections - referenced_sections)
    if missing_sections:
        raise ValueError(f"Input-model sections have no capability note: {', '.join(missing_sections)}")

    return {"schemaVersion": 1, "capabilities": capabilities}


def _dependency_identifier(dependency: object, path: Path) -> str:
    if not isinstance(dependency, str):
        raise ValueError(f"Capability dependency is not a link: {path}")
    match = re.fullmatch(r"\[\[capabilities/([a-z][a-z0-9-]*)\]\]", dependency)
    if match is None:
        raise ValueError(f"Capability dependency is not a capability-note link: {path}")
    return match.group(1)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a capability reference JSON document.")
    parser.add_argument("--notes", type=Path, required=True, metavar="FOLDER")
    parser.add_argument("--input-model", type=Path, required=True, metavar="MARKDOWN")
    parser.add_argument("--output", type=Path, required=True, metavar="JSON")
    options = parser.parse_args(argv)

    reference = build_capability_reference(options.notes, options.input_model)
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(reference, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
