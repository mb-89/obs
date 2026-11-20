"""Comments and reviews: overlay discovery, validation, union and resolution (input-model#Comments and reviews).

Each principal's comments, review decisions and state entries live in one overlay file next to the
manifest. The core reads them all, forms their union by immutable id, resolves replies and state
entries across files and targets through the Document, and puts the resolved model in the
Document's ``comments``; every adapter renders that model and maps its native comments onto the
overlay format.
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
_KINDS = ("comments", "decisions", "states")
_KIND = "comments"
_NAME = {"comments": "author", "decisions": "reviewer", "states": "author"}
"""The field of each kind's entries that holds a name of the file's ``names``."""
_FINER = re.compile(r"(\.[0-9]{3})[0-9]+")


def _ms(time: str) -> str:
    """A time at milliseconds, its digits after the third cut, as a browser reads it."""
    return _FINER.sub(r"\1", time, count=1)


def _moment(time: str) -> datetime:
    return datetime.fromisoformat(_ms(time))


def _in_ms(model: dict[str, Any]) -> dict[str, Any]:
    """``model`` with every entry's times at milliseconds (input-model#Comments and reviews, Overlay files)."""
    return {**model, **{kind: [{**entry, **{field: _ms(entry[field]) for field in ("created", "modified")
                                            if field in entry}} for entry in model[kind]]
                        for kind in _KINDS if kind in model}}


def _unnamed(model: dict[str, Any], names: list[str]) -> Iterator[tuple[str, dict[str, Any], str]]:
    """The field path, entry and name of each entry of ``model`` under a name ``names`` lacks."""
    for kind in _KINDS:
        for index, entry in enumerate(model.get(kind, [])):
            if entry[_NAME[kind]] not in names:
                yield f"{kind}[{index}].{_NAME[kind]}", entry, entry[_NAME[kind]]


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
    for field, entry, name in _unnamed(overlay, overlay["names"]):
        raise input_error(path, field, f"is {name!r} for {entry['id']!r}, not one of this file's names "
                          f"({', '.join(map(repr, overlay['names']))})",
                          f"Write each entry under one of the principal's names; see {OWNER}")


def _read(path: Path) -> dict[str, Any]:
    overlay = read_overlay(path, _KIND, _PRINCIPAL, "principal", OWNER)
    validate_overlay(overlay, path)
    return _in_ms(overlay)


class _Entry:
    """One comment or decision of the union, with the file and field of its first occurrence."""

    def __init__(self, payload: dict[str, Any], path: Path, field: str) -> None:
        self.payload, self.path, self.field = payload, path, field


def _union(overlays: list[tuple[Path, dict[str, Any]]], kind: str) -> list[_Entry]:
    entries: dict[str, _Entry] = {}
    for path, overlay in overlays:
        for index, payload in enumerate(overlay.get(kind, [])):
            field, known = f"{kind}[{index}]", entries.get(payload["id"])
            if known is None:
                entries[payload["id"]] = _Entry(payload, path, field)
            elif known.payload != payload:
                raise input_error(path, field, f"has the id {payload['id']!r} of {known.path} {known.field}, with a "
                                  "different payload", f"Give a changed entry a new id, or keep one payload; see {OWNER}")
    return sorted(entries.values(), key=lambda entry: (_moment(entry.payload["created"]), entry.payload["id"]))


def _check_decisions(decisions: list[_Entry]) -> None:
    decided: dict[tuple[str, str], _Entry] = {}
    for entry in sorted(decisions, key=lambda entry: (entry.path.name, entry.field)):
        key = (entry.payload["reviewer"], json.dumps(entry.payload["target"], sort_keys=True))
        if key in decided:
            first = decided[key]
            raise input_error(entry.path, entry.field, f"is a second decision of {key[0]!r} on its target, after "
                              f"{first.path} {first.field}", f"Keep one decision per reviewer and target; see {OWNER}")
        decided[key] = entry


def _check_states(states: list[_Entry], comments: list[_Entry]) -> None:
    known = {entry.payload["id"] for entry in comments}
    for entry in sorted(states, key=lambda entry: (entry.path.name, entry.field)):
        if entry.payload["target"] not in known:
            raise input_error(entry.path, f"{entry.field}.target", f"names {entry.payload['target']!r}, which no "
                              "overlay file has as a comment", f"Change the state of a comment of an overlay file of "
                              f"this manifest; see {OWNER}")


def _check_union(overlays: list[tuple[Path, dict[str, Any]]]) -> tuple[list[_Entry], ...]:
    """The union of ``overlays``, each kind's entries ordered, once its checks pass."""
    comments, decisions, states = (_union(overlays, kind) for kind in _KINDS)
    _check_decisions(decisions)
    _check_replies(comments)
    _check_states(states, comments)
    return comments, decisions, states


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


def document_targets(document: dict[str, Any]) -> tuple[dict[str, set[str]], set[str]]:
    """Each chapter's node targets, and the manifest abstract's: their block ids and keyed rows."""
    abstract = {"id": "abstract", "content": document["manifest"]["abstract"], "children": []}
    return (chapter_targets(document),
            chapter_targets({"records": document["records"], "chapters": [abstract]})["abstract"])


def unresolved(target: dict[str, Any], nodes: dict[str, set[str]], abstract: frozenset[str] | set[str] = frozenset(),
               ) -> tuple[str, str] | None:
    """The field of a target that names what the Document lacks, and what it names; None where it
    resolves. ``nodes`` are each chapter's node targets, ``abstract`` the manifest abstract's."""
    chapter, node = target.get("chapter"), target.get("node")
    if chapter is not None and chapter not in nodes:
        return "chapter", f"the chapter {chapter!r}"
    if node is not None and node not in (abstract if target.get("abstract") else nodes[chapter]):
        place = "the abstract" if target.get("abstract") else f"the chapter {chapter!r}"
        return "node", f"the node {node!r} in {place}"
    return None


def _targets(entry: _Entry) -> Iterator[tuple[str, dict[str, Any]]]:
    if "target" in entry.payload:
        yield f"{entry.field}.target", entry.payload["target"]
    for index, item in enumerate(entry.payload.get("batch", {}).get("items", [])):
        yield f"{entry.field}.batch.items[{index}]", item


def _unmapped(entries: list[_Entry], nodes: dict[str, set[str]], abstract: set[str]) -> Iterator[str]:
    for entry in entries:
        for field, target in _targets(entry):
            missing = unresolved(target, nodes, abstract)
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
    comments, decisions, states = _check_union([(path, _read(path)) for path in paths])
    document["diagnostics"].extend({"level": "warning", "message": message}
                                   for message in _unmapped([*comments, *decisions], *document_targets(document)))
    document["comments"] = {"version": VERSION, "files": [path.name for path in paths],
                            "comments": [entry.payload for entry in comments],
                            "decisions": [entry.payload for entry in decisions],
                            "states": [entry.payload for entry in states]}


def review_state(decisions: list[dict[str, Any]], target: dict[str, Any], reviewer: str | None = None) -> str:
    """A target's review state: ``reviewer``'s decision on it, or without a reviewer the aggregate,
    rejected over accepted over waiting (input-model#Comments and reviews, Review semantics)."""
    states = {decision["state"] for decision in decisions
              if decision["target"] == target and reviewer in (None, decision["reviewer"])}
    return next((state for state in ("rejected", "accepted") if state in states), "waiting")


def comment_state(comment: dict[str, Any], states: list[dict[str, Any]]) -> str:
    """A comment's state: its latest state entry's, at milliseconds, of one time the one whose author,
    then id, sorts first; without one the state it was created with (input-model#Comments and reviews,
    Review semantics)."""
    entries = [entry for entry in states if entry["target"] == comment["id"]]
    if not entries:
        return comment["state"]
    latest = max(_moment(entry["created"]) for entry in entries)
    return min((entry for entry in entries if _moment(entry["created"]) == latest),
               key=lambda entry: (entry["author"], entry["id"]))["state"]


def import_comments(manifest_path: Path, imports: list[tuple[Path, str]]) -> list[Path]:
    """Write each principal's overlay file from the comments an adapter returned for it (input-model#Comments
    and reviews, Adapter contract): every entry no other file holds with the same payload, the files on disk
    of the principals not imported and the other returned files. An edit of another principal's comment body
    is refused; the reader's resolves and reopens are its own state entries. Every written entry is under one
    of its returned file's ``names``, which become the principal's. The files are written only when the union
    of every overlay file with all of them passes the union's checks, all of them or none."""
    manifest_path = manifest_path.resolve()
    returned = [(path, principal, _returned_file(path, principal)) for path, principal in imports]
    paths = [manifest_path.with_name(overlay_name(manifest_path, _KIND, principal)) for _, principal, _ in returned]
    others = [(other, _read(other)) for other in overlay_files(manifest_path, _KIND) if other not in paths]
    overlays = []
    for index, ((returned_path, principal, copy), path) in enumerate(zip(returned, paths)):
        held = {entry["id"]: (other, f"{kind}[{position}]", entry)
                for other, overlay in [*others, *((source, data) for number, (source, _, data) in enumerate(returned)
                                                  if number != index)]
                for kind in _KINDS for position, entry in enumerate(overlay.get(kind, []))}
        overlays.append((path, _principal_overlay(copy, returned_path, principal, path, held)))
    _check_union([*others, *((source, overlay) for (source, _, _), (_, overlay) in zip(returned, overlays))])
    for path, overlay in overlays:
        write_output(path, json.dumps(overlay, indent=2, ensure_ascii=False) + "\n")
    return paths


def _returned_file(returned_path: Path, principal: str) -> dict[str, Any]:
    """A returned file, once the core's schema accepts it, with its times at milliseconds."""
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
    if not _PRINCIPAL.fullmatch(principal):
        raise input_error(returned_path, "principal", f"is {principal!r}, not {_PRINCIPAL.pattern}",
                          f"Name the principal whose file it is with --principal; see {OWNER}")
    if "names" not in returned:
        raise input_error(returned_path, "names", "is missing: the reader's names, which the import holds the "
                          "principal's entries to", f"Export the comments with an adapter that writes the reader's "
                          f"names; see {OWNER}")
    return _in_ms(returned)


def _principal_overlay(returned: dict[str, Any], returned_path: Path, principal: str, path: Path,
                       held: dict[str, tuple[Path, str, dict[str, Any]]]) -> dict[str, Any]:
    """The principal's overlay file from its returned file: every entry ``held`` lacks, under its names."""
    names = returned["names"]
    overlay: dict[str, Any] = {"version": VERSION, "principal": principal, "names": names, "comments": [],
                               "decisions": [], "states": []}
    for kind in _KINDS:
        for index, entry in enumerate(returned.get(kind, [])):
            known = held.get(entry["id"])
            if known is None and entry[_NAME[kind]] not in names:
                raise input_error(returned_path, f"{kind}[{index}].{_NAME[kind]}", f"is {entry[_NAME[kind]]!r} for "
                                  f"{entry['id']!r}, not one of the names ({', '.join(map(repr, names))}) of "
                                  f"{path}, the file of {principal!r}", f"Import each reader's copy as that reader's "
                                  f"principal, or export it under the name its entries carry; see {OWNER}")
            if known is None:
                overlay[kind].append(entry)
            elif kind == "comments" and known[2]["body"] != entry["body"]:
                raise input_error(returned_path, f"{kind}[{index}].body", f"edits the body of {entry['id']!r} by "
                                  f"{known[2]['author']!r} in {known[0]} {known[1]}, as {principal!r}; only a "
                                  "comment's author edits its body", f"Reply to the comment instead; see {OWNER}")
            elif known[2] != entry:
                raise input_error(returned_path, f"{kind}[{index}]", f"changes {entry['id']!r} of {known[0]} "
                                  f"{known[1]}; a principal writes only its own file",
                                  f"Record a resolve or reopen as a state entry, any other change as a new entry; "
                                  f"see {OWNER}")
    if not overlay["states"]:
        del overlay["states"]
    validate_overlay(overlay, path)
    return overlay
