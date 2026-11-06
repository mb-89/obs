"""The build hook of the core's package: it writes the capability reference the package ships.

Reader: whoever changes how the core is built or what it ships.

Each build of the `obs` distribution, editable (`uv sync`) or not, writes
`src/obs/capability-reference.json` from the capability notes in `spec/capabilities`, with the
generator `obs.capabilities` and its coverage data, and ships it as package data; obs-document
reads it when no `--capability-reference` is given. The file is generated, so it is ignored and
never edited; `[tool.uv] cache-keys` in pyproject.toml makes `uv sync` and `uv run` build again
when a note changes. test/test_capabilities.py fails when the shipped file is stale.
"""
import json
import sys
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

NOTES = Path("spec") / "capabilities"
PACKAGED = Path("src") / "obs" / "capability-reference.json"


class CapabilityReferenceHook(BuildHookInterface):
    PLUGIN_NAME = "capability-reference"

    def initialize(self, version: str, build_data: dict) -> None:
        root = Path(self.root)
        # The generator from the source tree; it and what it imports need only pyyaml.
        sys.path.insert(0, str(root / "src"))
        try:
            from obs.capabilities import build_capability_reference
        finally:
            sys.path.remove(str(root / "src"))
        reference = build_capability_reference(root / NOTES, root / NOTES / "coverage.json")
        (root / PACKAGED).write_text(json.dumps(reference, indent=2) + "\n", encoding="utf-8")
        build_data["artifacts"].append(PACKAGED.as_posix())
