"""Generate the authoring skill, an Agent Skills folder that teaches obs's Markdown dialect.

Reader: whoever changes what the skill says or how it is laid out; cli.md, Authoring skill, owns
why it exists and where it lives.

The skill is a second view of the capability notes in `spec/capabilities`: `SKILL.md` lists each
capability of the capability reference with its summary and authoring line, and
`references/capabilities.md` gives one section per capability with its authoring line and its
tested examples, the `markdown` fences and companion files test/test_capability_examples.py reads.

`skill_files` is pure: the capability reference and each capability's examples in, the folder's
files as texts out. `note_examples` reads one note's text. `main` is the thin writer.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Mapping, Sequence

import yaml

from obs.capabilities import build_capability_reference
from obs.output import write_output

NAME = "obs-authoring"
"""The skill's name; Agent Skills requires it to equal the folder's name."""
DESCRIPTION = (
    "Write and edit Markdown in obs's dialect: the manifest, notes and their frontmatter, "
    "wikilinks and embeds, callouts and marks, queries, Bases and registers, reference notes, "
    "quantities, and the fences obs reads (base, cards, cmd, figure, mermaid, plantuml, "
    "property-editor, pugh). Use when creating or changing notes of a vault that obs builds, "
    "or when checking which syntax obs reads and how to write it."
)
REFERENCE = "references/capabilities.md"
"""The one reference file, relative to the skill folder."""
REGENERATE = ("uv run python -m obs.authoring_skill --notes spec/capabilities "
              "--coverage spec/capabilities/coverage.json --destination skills/obs-authoring")
_GENERATED = f"<!-- Generated from spec/capabilities by obs.authoring_skill; do not edit. Regenerate: {REGENERATE} -->"

FENCE = re.compile(
    r"^(?P<fence>`{3,})(?P<language>\S*)(?:[ \t]+(?P<file>[^\s`]+\.[A-Za-z0-9]+))?[^\n]*\n"
    r"(?P<body>.*?)^(?P=fence)[ \t]*$", re.M | re.S,
)
"""A fence of a capability note; a file name after the language makes it a companion file."""


def note_examples(text: str) -> list[dict[str, str]]:
    """A capability note's tested examples, in note order: each `markdown` fence's body, and each
    companion file (a fence that names a file) with its language and file name."""
    examples = []
    for match in FENCE.finditer(text):
        if match["file"]:
            examples.append({"language": match["language"], "file": match["file"], "body": match["body"]})
        elif match["language"] == "markdown":
            examples.append({"language": "markdown", "body": match["body"]})
    return examples


def skill_files(reference: Mapping[str, object],
                examples: Mapping[str, Sequence[Mapping[str, str]]]) -> dict[str, str]:
    """The skill folder's files, by path relative to the folder, from the capability reference and
    each capability's examples by its id."""
    capabilities = reference["capabilities"]
    return {"SKILL.md": _skill(capabilities), REFERENCE: _reference(capabilities, examples)}


def _skill(capabilities) -> str:
    lines = [
        "---", f"name: {NAME}", f"description: {_yaml_text(DESCRIPTION)}", "---", "", _GENERATED, "",
        "# Writing for obs", "",
        "obs builds a document from a vault of Obsidian-compatible Markdown notes: a manifest note "
        "lists the chapters, and each note uses the capabilities below. Write only these "
        "constructs; obs refuses or ignores what it does not read.", "",
        f"Each capability's section in [{REFERENCE}]({REFERENCE}) holds its authoring line and its "
        "tested examples; read the sections of the capabilities a note needs before writing it.", "",
        "| Capability | What it does | How to write it |", "|---|---|---|",
    ]
    lines += [f"| [{item['id']}]({REFERENCE}#{item['id']}) | {_cell(item['summary'])} | {_cell(item['authoring'])} |"
              for item in capabilities]
    return "\n".join(lines) + "\n"


def _reference(capabilities, examples) -> str:
    lines = ["# obs capabilities", "", _GENERATED, ""]
    for item in capabilities:
        lines += [f"## {item['id']}", "", item["summary"], "", f"**How to write it:** {item['authoring']}", ""]
        if item["dependsOn"]:
            lines += ["Builds on " + ", ".join(f"[{name}](#{name})" for name in item["dependsOn"]) + ".", ""]
        for example in examples.get(item["id"], ()):
            label = f"The file `{example['file']}`:" if "file" in example else "Example:"
            fence = "`" * max([3, *(len(run) + 1 for run in re.findall(r"^`+", example["body"], re.M))])
            info = " ".join(part for part in (example["language"], example.get("file", "")) if part)
            lines += [label, "", f"{fence}{info}", example["body"].rstrip("\n"), fence, ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _yaml_text(text: str) -> str:
    """A one-line YAML double-quoted scalar."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_skill(notes: Path, coverage: Path | None = None) -> dict[str, str]:
    """The skill folder's files from the capability notes in ``notes``."""
    reference = build_capability_reference(notes, coverage)
    examples = {}
    for path in sorted(notes.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        frontmatter = yaml.safe_load(text.split("---", 2)[1])
        if frontmatter.get("kind") == "capability":
            examples[frontmatter["capability"]["id"]] = note_examples(text)
    return skill_files(reference, examples)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the obs authoring skill folder from the capability notes.")
    parser.add_argument("--notes", type=Path, required=True)
    parser.add_argument("--coverage", type=Path)
    parser.add_argument("--destination", type=Path, required=True)
    options = parser.parse_args(argv)
    for path, text in build_skill(options.notes, options.coverage).items():
        write_output(options.destination / path, text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
