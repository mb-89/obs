"""se's repository size rule on obs's tree, with obs's allow list.

Reader: whoever tracks a large file or changes the allow list.

architecture.md, Repository layout, owns the rule as obs applies it. se's `tests/test_repository.py`
owns the rule itself and its bound, `MAX_BYTES`, and checks only se's own tree; obs applies it
here. Only a vendored library its part's vendor manifest pins may be on the allow list, and that
part's tests check the file against the pin.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
# se's bound, `MAX_BYTES` in se's tests/test_repository.py: the most bytes a tracked file holds
# outside LARGE_ALLOWED.
MAX_BYTES = 200_000
VENDOR_MANIFEST = "vendor.json"

# Tracked files over MAX_BYTES, each with the reason it is tracked.
LARGE_ALLOWED: dict[str, str] = {
    "adapters/html/src/obs_html/vendor/plotly-basic.min.js": "embedded library, pages work offline",
    "adapters/html/src/obs_html/vendor/pdf-lib.min.js": "embedded library, pages work offline",
}


def tracked_sizes(repo: Path) -> dict[str, int]:
    """The size of each file git tracks in `repo` that exists in its working tree."""
    out = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], check=True, capture_output=True).stdout
    return {p: (repo / p).stat().st_size for p in out.decode().split("\0") if p and (repo / p).is_file()}


def large_findings(sizes: dict[str, int], allowed: dict[str, str], limit: int = MAX_BYTES) -> list[str]:
    """Files over `limit` bytes outside `allowed`, and entries of `allowed` naming none."""
    large = {p for p, size in sizes.items() if size > limit}
    return [
        f"{p}: {sizes[p]} bytes, over {limit}; git rm --cached it and ignore it, split it, "
        "or allow it with a reason"
        for p in sorted(large - set(allowed))
    ] + [
        f"{p}: allowed as large but no tracked file over {limit} bytes; remove the entry"
        for p in sorted(set(allowed) - large)
    ]


def unpinned_findings(root: Path, allowed: dict[str, str]) -> list[str]:
    """Entries of `allowed` that no vendor manifest of their part pins.

    A part is the core and each adapter adapters.json registers (architecture.md, Repository layout).
    """
    registry = json.loads((root / "adapters.json").read_text(encoding="utf-8"))["adapters"]
    parts = [Path(manifest).parent.as_posix() for manifest in registry.values()]
    found = []
    for entry in sorted(allowed):
        part = next((p for p in parts if entry.startswith(f"{p}/")), "")
        manifest = root / part / VENDOR_MANIFEST
        pinned = json.loads(manifest.read_text(encoding="utf-8"))["libraries"] if manifest.is_file() else {}
        if entry.removeprefix(f"{part}/") not in pinned:
            found.append(f"{entry}: allowed as large but {(Path(part) / VENDOR_MANIFEST).as_posix()} "
                         "pins no such library; pin it there or remove the entry")
    return found


def test_obs_tracks_no_file_over_the_bound_outside_its_allow_list() -> None:
    assert large_findings(tracked_sizes(ROOT), LARGE_ALLOWED) == []
    assert all(reason.strip() for reason in LARGE_ALLOWED.values())


def test_a_file_over_the_bound_fails_and_a_stale_entry_too() -> None:
    sizes = {"dump.json": 201, "kept.json": 201, "small.py": 200}

    assert large_findings(sizes, {"kept.json": "needed", "small.py": "shrank"}, limit=200) == [
        "dump.json: 201 bytes, over 200; git rm --cached it and ignore it, split it, "
        "or allow it with a reason",
        "small.py: allowed as large but no tracked file over 200 bytes; remove the entry",
    ]


def test_each_allowed_file_is_a_vendored_library_its_part_pins() -> None:
    assert unpinned_findings(ROOT, LARGE_ALLOWED) == []


def test_an_allowed_file_no_vendor_manifest_pins_fails() -> None:
    allowed = {"adapters/html/src/obs_html/artifact.js": "big", "src/obs/big.json": "big"}

    assert [finding.split(":", 1)[0] for finding in unpinned_findings(ROOT, allowed)] == sorted(allowed)
