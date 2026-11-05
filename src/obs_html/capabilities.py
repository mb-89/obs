"""Generate a capability reference from independently authored capability notes."""
import argparse
import json
import re
from pathlib import Path
from typing import Sequence
import yaml


def _frontmatter(path: Path) -> dict[str, object]:
    source = path.read_text(encoding="utf-8")
    if not source.startswith("---\n"):
        raise ValueError(f"Capability note has no frontmatter: {path}")
    loaded = yaml.safe_load(source.split("---", 2)[1])
    if not isinstance(loaded, dict):
        raise ValueError(f"Capability frontmatter is not a mapping: {path}")
    return loaded


def build_capability_reference(notes_root: Path, coverage: Path | None = None,
                               references: Sequence[Path] = ()) -> dict[str, object]:
    capabilities = []
    for path in sorted(notes_root.glob("*.md")):
        frontmatter = _frontmatter(path)
        if frontmatter.get("kind") != "capability":
            continue
        value = frontmatter["capability"]
        document = {key: value[key] for key in ("id", "summary", "authoring", "dependsOn", "source")}
        document["dependsOn"] = [_dependency_id(item, path) for item in document["dependsOn"]]
        capabilities.append(document)
    identifiers = {item["id"] for item in capabilities}
    if len(identifiers) != len(capabilities):
        raise ValueError("Capability identifiers must be unique.")
    external = {
        item["id"] for reference in references
        for item in json.loads(reference.read_text(encoding="utf-8"))["capabilities"]
    }
    missing = sorted({dependency for item in capabilities for dependency in item["dependsOn"]
                      if dependency not in identifiers | external})
    if missing:
        raise ValueError(f"Capability dependencies do not exist: {', '.join(missing)}")
    if coverage is not None:
        sections = json.loads(coverage.read_text(encoding="utf-8"))["sections"]
        expected = {name for name, kind in sections.items() if kind == "input"}
        actual = {item["source"].removesuffix("]]" ).split("#", 1)[1] for item in capabilities}
        if expected != actual:
            raise ValueError("Capability coverage does not match the supplied coverage data.")
    return {"schemaVersion": 1, "capabilities": capabilities}


def _dependency_id(value: object, path: Path) -> str:
    match = re.fullmatch(r"\[\[[^\]]*/([a-z][a-z0-9-]*)\]\]", str(value))
    if match is None:
        raise ValueError(f"Capability dependency is not a note link: {path}")
    return match.group(1)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a capability reference JSON document.")
    parser.add_argument("--notes", type=Path, required=True)
    parser.add_argument("--coverage", type=Path)
    parser.add_argument("--reference", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args(argv)
    reference = build_capability_reference(options.notes, options.coverage, options.reference)
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(reference, indent=2) + "\n", encoding="utf-8")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

