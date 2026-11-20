"""The JSON files next to a manifest: their naming, discovery and reading (input-model#Overlay files).

A file ``<manifest stem>.<kind>.<name>.json`` belongs to one name of one kind: a principal's
comments (kind ``comments``) or a namespace's sync records (kind ``sync``). Each kind owns its
schema and the pattern of its names; this module owns what the kinds share.
"""
import json
import re
from glob import escape
from pathlib import Path

from obs.input import input_error


def overlay_name(manifest_path: Path, kind: str, name: str) -> str:
    """The file name of ``name``'s file of ``kind``: ``<manifest stem>.<kind>.<name>.json``."""
    return f"{manifest_path.stem}.{kind}.{name}.json"


def overlay_files(manifest_path: Path, kind: str) -> list[Path]:
    """Every file of ``kind`` next to the manifest, by file name."""
    return sorted(manifest_path.parent.glob(f"{escape(manifest_path.stem)}.{kind}.*.json"), key=lambda path: path.name)


def overlay_owner(path: Path, kind: str) -> str:
    """The name a file of ``kind`` belongs to, after its last ``.<kind>.``."""
    return path.name.removesuffix(".json").rsplit(f".{kind}.", 1)[-1]


def read_overlay(path: Path, kind: str, pattern: re.Pattern[str], what: str, owner: str) -> object:
    """A file of ``kind`` as JSON, once its name gives a valid ``what`` (a principal, a namespace)."""
    name = overlay_owner(path, kind)
    if not pattern.fullmatch(name):
        raise input_error(path, "", f"names the {what} {name!r}, which is not {pattern.pattern}",
                          f"Rename the file; see {owner}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise input_error(path, "", f"cannot be read as JSON ({error})", f"Write the file as JSON; see {owner}") \
            from error
