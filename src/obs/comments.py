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
from pathlib import Path
from typing import Any, Iterator

from jsonschema import Draft202012Validator

from obs.input import input_error, schema_error
from obs.node_ids import chapter_targets
from obs.output import write_output
from obs.overlay import overlay_files, overlay_name, overlay_owner, read_overlay


SCHEMA_PATH = Path(__file__).with_name("comments.schema.json")
OWNER = "input-model#Comments and reviews"
VERSION = 1
_SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
_PRINCIPAL = re.compile(_SCHEMA["$defs"]["principal"]["pattern"])
_KINDS = ("comments", "decisions")
_KIND = "comments"


@cache
def _validator() -> Draft202012Validator:
    return Draft202012Validator(_SCHEMA)


@cache
def _returned() -> Draft202012Validator:
    """A returned copy's comments: the resolved shape (``$defs/resolved``), which an adapter hands back."""
    return Draft202012Validator({"$defs": _SCHEMA["$defs"], "$ref": "#/$defs/resolved"})


def validate_overlay(overlay: object, path: Path) -> None:
    """Check one principal's overlay before an adapter writes it to ``path``, or after the core reads it."""
    error = schema_error(list(_validator().iter_errors(overlay)), path, OWNER)
    if error:
        raise error
    principal = overlay_owner(path, _KIND)
    if overlay["principal"] != principal:
        raise input_error(path, "principal", f"is {overlay['principal']!r}, not {principal!r}, the file name's",
                          f"Write each principal's comments into its own file; see {OWNER}")


def _read(path: Path) -> dict[str, Any]:
    overlay = read_overlay(path, _KIND, _PRINCIPAL, "principal", OWNER)
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


def unresolved(target: dict[str, Any], nodes: dict[str, set[str]]) -> tuple[str, str] | None:
    """The field of a target that names what the Document lacks, and what it names; None where it resolves."""
    chapter, node = target.get("chapter"), target.get("node")
    if chapter is not None and chapter not in nodes:
        return "chapter", f"the chapter {chapter!r}"
    if node is not None and node not in nodes[chapter]:
        return "node", f"the node {node!r} in the chapter {chapter!r}"
    return None


def _targets(entry: _Entry) -> Iterator[tuple[str, dict[str, Any]]]:
    if "target" in entry.payload:
        yield f"{entry.field}.target", entry.payload["target"]
    for index, item in enumerate(entry.payload.get("batch", {}).get("items", [])):
        yield f"{entry.field}.batch.items[{index}]", item


def _unmapped(entries: list[_Entry], nodes: dict[str, set[str]]) -> Iterator[str]:
    for entry in entries:
        for field, target in _targets(entry):
            missing = unresolved(target, nodes)
            if missing is not None:
                yield str(input_error(entry.path, f"{field}.{missing[0]}", f"names {missing[1]}, which this Document "
                                      f"does not have, for {entry.payload['id']!r}", f"Move it to a target the "
                                      f"Document has, or resolve it; see {OWNER}"))


def apply_comments(document: dict[str, Any], manifest_path: Path) -> None:
    """Put the union of the manifest's overlay files in the Document's ``comments``, with a warning per
    target the Document does not have; a Document without overlay files gets none."""
    paths = overlay_files(manifest_path.resolve(), _KIND)
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


def import_comments(manifest_path: Path, returned_path: Path, principal: str) -> Path:
    """Write ``principal``'s overlay file from the comments an adapter returned (input-model#Comments and
    reviews, Adapter contract): every entry no other principal's file holds with the same payload. The
    file is written only when the union of every overlay file with it passes the union's checks."""
    try:
        returned = json.loads(returned_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise input_error(returned_path, "", f"cannot be read as JSON ({error})",
                          f"Pass the comments file an adapter exported; see {OWNER}") from error
    if not isinstance(returned, dict) or returned.get("version") != VERSION:
        raise input_error(returned_path, "version", f"is {returned.get('version') if isinstance(returned, dict) else None!r}, "
                          f"not {VERSION}", f"Export the comments with an adapter of this core; see {OWNER}")
    error = schema_error(list(_returned().iter_errors(returned)), returned_path, OWNER)
    if error:
        raise error
    manifest_path = manifest_path.resolve()
    if not _PRINCIPAL.fullmatch(principal):
        raise input_error(returned_path, "principal", f"is {principal!r}, not {_PRINCIPAL.pattern}",
                          f"Name the principal whose file it is with --principal; see {OWNER}")
    path = manifest_path.with_name(overlay_name(manifest_path, _KIND, principal))
    others = [(other, _read(other)) for other in overlay_files(manifest_path, _KIND) if other != path]
    held = {entry["id"]: (other, f"{kind}[{index}]", entry) for other, overlay in others
            for kind in _KINDS for index, entry in enumerate(overlay[kind])}
    overlay: dict[str, Any] = {"version": VERSION, "principal": principal, "comments": [], "decisions": []}
    for kind in _KINDS:
        for index, entry in enumerate(returned[kind]):
            known = held.get(entry["id"])
            if known is None:
                overlay[kind].append(entry)
            elif known[2] != entry:
                raise input_error(returned_path, f"{kind}[{index}]", f"changes {entry['id']!r} of {known[0]} "
                                  f"{known[1]}; a principal writes only its own file",
                                  f"Give the changed entry a new id, or keep the other principal's; see {OWNER}")
    validate_overlay(overlay, path)
    overlays = [*others, (returned_path, overlay)]
    comments, decisions = (_union(overlays, kind) for kind in _KINDS)
    _check_decisions(decisions)
    _check_replies(comments)
    write_output(path, json.dumps(overlay, indent=2, ensure_ascii=False) + "\n")
    return path
