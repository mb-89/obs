"""Sync records: record files, the sync results adapters return, and their persistence (input-model#Sync records).

A namespace's records live in one record file next to the manifest; only the core writes it. An
adapter returns a sync result, ``apply_result`` applies it to the record file, and ``apply_sync``
puts every record file in the Document's ``sync``.
"""
import json
import re
from functools import cache
from pathlib import Path
from typing import Any, Iterator

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from obs.comments import SCHEMA_PATH as COMMENTS_SCHEMA_PATH, document_nodes, unresolved
from obs.input import input_error, schema_error
from obs.output import write_output
from obs.overlay import overlay_files, overlay_name, overlay_owner, read_overlay


SCHEMA_PATH = Path(__file__).with_name("sync.schema.json")
OWNER = "input-model#Sync records"
VERSION = 1
_SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
_NAMESPACE = re.compile(_SCHEMA["$defs"]["namespace"]["pattern"])
_KIND = "sync"


@cache
def _validator(definition: str = "") -> Draft202012Validator:
    """The record file's validator, or with ``definition`` that ``$defs`` entry's, comments.schema.json registered."""
    registry = Registry().with_resource(
        COMMENTS_SCHEMA_PATH.name, Resource.from_contents(json.loads(COMMENTS_SCHEMA_PATH.read_text(encoding="utf-8"))))
    schema = {"$defs": _SCHEMA["$defs"], "$ref": f"#/$defs/{definition}"} if definition else _SCHEMA
    return Draft202012Validator(schema, registry=registry)


def _key(node: dict[str, Any]) -> str:
    return json.dumps(node, sort_keys=True)


def _check_file(records: dict[str, Any], path: Path, manifest: str) -> None:
    """Refuse a record file the schema refuses, or whose namespace or manifest disagree with its place."""
    error = schema_error(list(_validator().iter_errors(records)), path, OWNER)
    if error:
        raise error
    for field, expected in (("namespace", overlay_owner(path, _KIND)), ("manifest", manifest)):
        if records[field] != expected:
            raise input_error(path, field, f"is {records[field]!r}, not {expected!r}, where the file is",
                              f"Keep each namespace's records in its own file next to its manifest; see {OWNER}")


def _check_claims(entries: list[tuple[Path, str, dict[str, Any]]]) -> None:
    """Refuse two records of one node, or two records claiming one external object; each entry is a
    record with the file and field it comes from."""
    keys: dict[str, str] = {}
    claims: dict[str, str] = {}
    for path, field, record in entries:
        key = _key(record["node"])
        if key in keys:
            raise input_error(path, f"{field}.node", f"is the node of {keys[key]}", f"Keep one record per node; "
                              f"see {OWNER}")
        keys[key] = f"{path} {field}"
        for position, external in enumerate(record["external"]):
            if external in claims:
                raise input_error(path, f"{field}.external[{position}]", f"claims {external!r}, which "
                                  f"{claims[external]} claims for another node", f"Map each external object to one "
                                  f"node; see {OWNER}")
            claims[external] = f"{path} {field}.external[{position}]"


def _read(path: Path, manifest: str) -> dict[str, Any]:
    records = read_overlay(path, _KIND, _NAMESPACE, "namespace", OWNER)
    _check_file(records, path, manifest)
    _check_claims([(path, f"records[{index}]", record) for index, record in enumerate(records["records"])])
    return records


def apply_result(manifest_path: Path, result_path: Path) -> None:
    """Apply an adapter's sync result to its namespace's record file, which is written only when every
    check passes."""
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise input_error(result_path, "", f"cannot be read as JSON ({error})",
                          f"Pass the sync result an adapter returned; see {OWNER}") from error
    error = schema_error(list(_validator("result").iter_errors(result)), result_path, OWNER)
    if error:
        raise error
    manifest_path = manifest_path.resolve()
    path = manifest_path.with_name(overlay_name(manifest_path, _KIND, result["namespace"]))
    empty = {"version": VERSION, "namespace": result["namespace"], "manifest": manifest_path.name, "records": [],
             "conflicts": []}
    stored = _read(path, manifest_path.name) if path.exists() else empty
    entries = {_key(record["node"]): (path, f"records[{index}]", record)
               for index, record in enumerate(stored["records"])}
    for change, exists, remedy in (("created", False, "it has a record: report it as updated"),
                                   ("updated", True, "it has no record: report it as created")):
        for index, record in enumerate(result[change]):
            key = _key(record["node"])
            if (key in entries) != exists:
                raise input_error(result_path, f"{change}[{index}].node", f"names {key}, but {remedy}",
                                  f"Return each node in the list its record file calls for; see {OWNER}")
            entries[key] = (result_path, f"{change}[{index}]", record)
    _check_claims(list(entries.values()))
    applied = {**stored, "records": [record for _, _, record in entries.values()], "conflicts": result["conflicts"]}
    write_output(path, json.dumps(applied, indent=2, ensure_ascii=False) + "\n")


def _unmapped(path: Path, records: list[dict[str, Any]], nodes: dict[str, set[str]]) -> Iterator[str]:
    for index, record in enumerate(records):
        missing = unresolved(record["node"], nodes)
        if missing is not None:
            yield str(input_error(path, f"records[{index}].node.{missing[0]}", f"names {missing[1]}, which this "
                                  "Document does not have", f"Remove the external object and its record, or restore "
                                  f"the node; see {OWNER}"))


def apply_sync(document: dict[str, Any], manifest_path: Path) -> None:
    """Put every record file of the manifest in the Document's ``sync``, with a warning per record whose
    node the Document does not have; a Document without record files gets none."""
    manifest_path = manifest_path.resolve()
    paths = overlay_files(manifest_path, _KIND)
    if not paths:
        return
    nodes = document_nodes(document)
    document["sync"] = {}
    for path in paths:
        records = _read(path, manifest_path.name)
        document["diagnostics"].extend({"level": "warning", "message": message}
                                       for message in _unmapped(path, records["records"], nodes))
        document["sync"][records["namespace"]] = {"file": path.name, "records": records["records"],
                                                  "conflicts": records["conflicts"]}
