"""Comments and reviews: overlay discovery, validation, union and resolution (input-model#Comments and reviews).

Each principal's comments and review decisions live in one overlay file next to the manifest. The
core reads them all, forms their union by immutable id, resolves replies across files and targets
through the Document, and puts the resolved model in the Document's ``comments``; every adapter
renders that model and maps its native comments onto the overlay format.
"""
import json
import re
from datetime import datetime
from functools import cache
from glob import escape
from pathlib import Path
from typing import Any, Iterator

from jsonschema import Draft202012Validator

from obs.input import InputError, input_error, schema_error
from obs.node_ids import chapter_targets


SCHEMA_PATH = Path(__file__).with_name("comments.schema.json")
OWNER = "input-model#Comments and reviews"
VERSION = 1
_SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
_PRINCIPAL = re.compile(_SCHEMA["$defs"]["principal"]["pattern"])
_KINDS = ("comments", "decisions")


def overlay_name(manifest_path: Path, principal: str) -> str:
    """The overlay file name of a principal: ``<manifest stem>.comments.<principal>.json``."""
    return f"{manifest_path.stem}.comments.{principal}.json"


def overlay_files(manifest_path: Path) -> list[Path]:
    """Every overlay file next to the manifest, by file name."""
    return sorted(manifest_path.parent.glob(escape(manifest_path.stem) + ".comments.*.json"),
                  key=lambda path: path.name)


def _principal(path: Path) -> str:
    """The principal an overlay file's name gives, after its last ``.comments.``."""
    return path.name.removesuffix(".json").rsplit(".comments.", 1)[-1]


@cache
def _validator() -> Draft202012Validator:
    return Draft202012Validator(_SCHEMA)


def validate_overlay(overlay: object, path: Path) -> None:
    """Check one principal's overlay before an adapter writes it to ``path``, or after the core reads it."""
    error = schema_error(list(_validator().iter_errors(overlay)), path, OWNER)
    if error:
        raise error
    principal = _principal(path)
    if overlay["principal"] != principal:
        raise input_error(path, "principal", f"is {overlay['principal']!r}, not {principal!r}, the file name's",
                          f"Write each principal's comments into its own file; see {OWNER}")


def _read(path: Path) -> dict[str, Any]:
    principal = _principal(path)
    if not _PRINCIPAL.fullmatch(principal):
        raise input_error(path, "", f"names the principal {principal!r}, not lower-case letters, digits and hyphens",
                          f"Rename the file; see {OWNER}")
    try:
        overlay = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise input_error(path, "", f"cannot be read as JSON ({error})", f"Write the overlay as JSON; see {OWNER}") \
            from error
    validate_overlay(overlay, path)
    return overlay


class _Entry:
    """One comment or decision of the union, with the file and field of its first occurrence."""

    def __init__(self, payload: dict[str, Any], path: Path, field: str) -> None:
        self.payload, self.path, self.field = payload, path, field


def _union(overlays: list[tuple[Path, dict[str, Any]]], kind: str) -> list[_Entry]:
    entries: dict[str, _Entry] = {}
    for path, overlay in overlays:
        for index, payload in enumerate(overlay[kind]):
            field, known = f"{kind}[{index}]", entries.get(payload["id"])
            if known is None:
                entries[payload["id"]] = _Entry(payload, path, field)
            elif known.payload != payload:
                raise input_error(path, field, f"has the id {payload['id']!r} of {known.path} {known.field}, with a "
                                  "different payload", f"Give a changed entry a new id, or keep one payload; see {OWNER}")
    return sorted(entries.values(), key=lambda entry: (datetime.fromisoformat(entry.payload["created"]),
                                                       entry.payload["id"]))


def _check_decisions(decisions: list[_Entry]) -> None:
    decided: dict[tuple[str, str], _Entry] = {}
    for entry in sorted(decisions, key=lambda entry: (entry.path.name, entry.field)):
        key = (entry.payload["reviewer"], json.dumps(entry.payload["target"], sort_keys=True))
        if key in decided:
            first = decided[key]
            raise input_error(entry.path, entry.field, f"is a second decision of {key[0]!r} on its target, after "
                              f"{first.path} {first.field}", f"Keep one decision per reviewer and target; see {OWNER}")
        decided[key] = entry


def _check_replies(comments: list[_Entry]) -> None:
    by_id = {entry.payload["id"]: entry for entry in comments}
    for entry in sorted(comments, key=lambda entry: (entry.path.name, entry.field)):
        seen, current = {entry.payload["id"]}, entry.payload
        while "inReplyTo" in current:
            answered = by_id.get(current["inReplyTo"])
            if answered is None or answered.payload["id"] in seen:
                problem = (f"names {current['inReplyTo']!r}, which no overlay file has as a comment" if answered is None
                           else "is part of a chain of replies that reaches no root comment")
                raise input_error(entry.path, f"{entry.field}.inReplyTo", problem,
                                  f"Reply to a comment of an overlay file of this manifest; see {OWNER}")
            seen.add(answered.payload["id"])
            current = answered.payload


def _targets(entry: _Entry) -> Iterator[tuple[str, dict[str, Any]]]:
    if "target" in entry.payload:
        yield f"{entry.field}.target", entry.payload["target"]
    for index, item in enumerate(entry.payload.get("batch", {}).get("items", [])):
        yield f"{entry.field}.batch.items[{index}]", item


def _unmapped(entries: list[_Entry], nodes: dict[str, set[str]]) -> Iterator[str]:
    for entry in entries:
        for field, target in _targets(entry):
            chapter, node = target.get("chapter"), target.get("node")
            if chapter is not None and chapter not in nodes:
                missing, field = f"the chapter {chapter!r}", f"{field}.chapter"
            elif node is not None and node not in nodes[chapter]:
                missing, field = f"the node {node!r} in the chapter {chapter!r}", f"{field}.node"
            else:
                continue
            yield str(input_error(entry.path, field, f"names {missing}, which this Document does not have, for "
                                  f"{entry.payload['id']!r}", f"Move it to a target the Document has, or resolve it; "
                                  f"see {OWNER}"))


def apply_comments(document: dict[str, Any], manifest_path: Path) -> None:
    """Put the union of the manifest's overlay files in the Document's ``comments``, with a warning per
    target the Document does not have; a Document without overlay files gets none."""
    paths = overlay_files(manifest_path.resolve())
    if not paths:
        return
    overlays = [(path, _read(path)) for path in paths]
    comments, decisions = (_union(overlays, kind) for kind in _KINDS)
    _check_decisions(decisions)
    _check_replies(comments)
    nodes = chapter_targets(document)
    document["diagnostics"].extend({"level": "warning", "message": message}
                                   for message in _unmapped([*comments, *decisions], nodes))
    document["comments"] = {"version": VERSION, "files": [path.name for path in paths],
                            "comments": [entry.payload for entry in comments],
                            "decisions": [entry.payload for entry in decisions]}


def review_state(decisions: list[dict[str, Any]], target: dict[str, Any], reviewer: str | None = None) -> str:
    """A target's review state: ``reviewer``'s decision on it, or without a reviewer the aggregate,
    rejected over accepted over waiting (input-model#Comments and reviews, Review semantics)."""
    states = {decision["state"] for decision in decisions
              if decision["target"] == target and reviewer in (None, decision["reviewer"])}
    return next((state for state in ("rejected", "accepted") if state in states), "waiting")
