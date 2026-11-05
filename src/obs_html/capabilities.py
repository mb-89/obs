"""Generate the language-neutral capability reference from its owning notes."""

import argparse
import json
import re
from pathlib import Path
from typing import Sequence

from obs_html.content import _split_frontmatter


def build_capability_reference(notes_root: Path, input_model: Path) -> dict[str, object]:
    """Return the validated capability document owned by the supplied Markdown notes."""
    capabilities = []
    for path in sorted(notes_root.glob("*.md")):
        frontmatter, _ = _split_frontmatter(path.read_text(encoding="utf-8"), path)
        if frontmatter.get("kind") != "capability":
            continue
        capability = frontmatter.get("capability")
        if not isinstance(capability, dict):
            raise ValueError(f"Capability note has no capability mapping: {path}")
        capabilities.append({key: capability[key] for key in (
            "id", "summary", "authoring", "dependsOn", "inputModel",
        )})

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
    referenced_sections = {
        capability["inputModel"].removesuffix("]]").split("#", 1)[1]
        for capability in capabilities
    }
    missing_sections = sorted(headings - referenced_sections)
    if missing_sections:
        raise ValueError(f"Input-model sections have no capability note: {', '.join(missing_sections)}")

    return {"schemaVersion": 1, "capabilities": capabilities}


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
