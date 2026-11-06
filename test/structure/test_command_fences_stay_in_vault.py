"""No command fence of obs's specification names a path outside the specification's vault.

Reader: whoever adds or changes a command fence in obs's specification.

architecture.md, Source archive, owns the rule: a source archive holds the vault alone, so a
fence reads nothing outside it and calls only installed programs. The check reads every note
through the core's note reader, so a fence inside an Obsidian comment, which never runs, is not
checked, and names each argument of a `cmd` fence that is an absolute path, starts at the home
folder or climbs above the vault root; a URL is no path.
"""
from __future__ import annotations

import posixpath
import shlex
from pathlib import Path, PurePosixPath, PureWindowsPath

from obs.note import parser, read_note

SPEC = Path(__file__).parents[2] / "spec"
OWNER = "spec/design_input/architecture.md (Source archive)"


def _outside(argument: str) -> bool:
    path = argument.split("=", 1)[1] if argument.startswith("-") and "=" in argument else argument
    if "://" in path or not path:
        return False
    if path.startswith("~") or PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute():
        return True
    normal = posixpath.normpath(path.replace("\\", "/"))
    return normal == ".." or normal.startswith("../")


def paths_outside(vault: Path) -> list[tuple[str, str]]:
    """Each argument of a cmd fence below ``vault`` that names a path outside it, after its place
    (``<note>:<line>``, the fence's line in the source file)."""
    found = []
    for path in sorted(vault.rglob("*.md")):
        relative = path.relative_to(vault)
        if "design_output" in relative.parts or any(part.startswith(".") for part in relative.parts):
            continue
        note = read_note(path)
        for token in parser().parse(note.body):
            if token.type != "fence" or token.info.strip().split()[:1] != ["cmd"]:
                continue
            for argument in shlex.split(token.content, comments=False, posix=True):
                if _outside(argument):
                    found.append((f"{relative.as_posix()}:{note.source_line(token.map[0])}", argument))
    return found


def test_no_command_fence_of_the_spec_names_a_path_outside_its_vault() -> None:
    found = paths_outside(SPEC)
    assert found == [], "\n".join(
        f"spec/{place}: cmd fence names {argument}, outside the vault. Remedy: read it through an installed "
        f"program, or move it into the vault; see {OWNER}." for place, argument in found)


def test_a_fence_naming_a_path_above_the_vault_or_an_absolute_one_is_named(tmp_path) -> None:
    (tmp_path / "manifest.md").write_text("- [[note]]\n", encoding="utf-8")
    (tmp_path / "note.md").write_text(
        "# Note\n\n```cmd silent\nuv run tool --source ../other/manifest.md --config=/etc/tool.json "
        "--output design_output/out.html https://example.invalid/a/b\n```\n\n"
        "%%\n```cmd\ntool ../commented-out\n```\n%%\n", encoding="utf-8")

    found = paths_outside(tmp_path)

    assert found == [("note.md:3", "../other/manifest.md"), ("note.md:3", "--config=/etc/tool.json")]
