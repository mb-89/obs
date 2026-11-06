"""Parse a Markdown vault into the neutral Document data model."""
from __future__ import annotations

import base64
from copy import copy
from functools import cache, partial
from dataclasses import dataclass, field, replace
import mimetypes
import json
from pathlib import Path, PurePosixPath
import re
from typing import Callable
from urllib.parse import unquote, urlparse
import urllib.request

from jsonschema import Draft202012Validator
from markdown_it.token import Token
import yaml

from obs.commands import CommandError, run_command
from obs.config import (
    DEFAULT_COMMAND_TIMEOUT_SECONDS, CoreConfig, CoreConfigError, load_core_config,
)
from obs.figure import FigureDescriptorError, validate_figure_descriptor
from obs.input import (
    ADAPTER_NAMESPACE,
    InputError,
    input_error,
    parse_callout,
    parse_card_spec,
    parse_property_editor,
    property_editor_writes,
    validate_base_definition,
    validate_command,
    validate_cover_metadata,
    validate_count_query,
    validate_note_profile,
    validate_project_config,
    validate_quantity,
)
from obs.note import IGNORED, Note, VaultError, lines, parser, read_note
from obs.quantity import document_quantity
from obs.producers import ProducerError, run_producers
from obs.selection import (
    Record, base_selects, conditions_select, member_order, note_marks, paragraph_marks,
    view_selectors,
)


_MANIFEST_ITEM = re.compile(
    r"^(?P<indent> *)[-*+] \[\[(?P<target>[^\]|#]+)(?:\|(?P<label>[^\]]+))?\]\]$"
)
_WIKILINK = re.compile(
    r"(?<!!)\[\[(?P<target>[^\]|#]+)(?:#(?P<heading>[^\]|]+))?(?:\|(?P<label>[^\]]+))?\]\]"
)
_EMBED = re.compile(r"!\[\[(?P<target>[^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
_MARK = re.compile(r"#mark/(?P<category>[a-z_]+)/(?P<id>[a-z0-9_]+)")
_SEMANTIC = re.compile(
    r"(?P<embed>!)?\[\[(?P<target>[^\]|#]+)(?:#(?P<heading>[^\]|]+))?"
    r"(?:\|(?P<label>[^\]]+))?\]\]|#mark/(?P<category>[a-z_]+)/(?P<id>[a-z0-9_]+)"
)


REMOTE_SCHEMES = frozenset({"http", "https"})
"""The URL schemes of a remote image the build fetches; see input-model "Document home and abstract"."""
FETCH_TIMEOUT_SECONDS = 20


def fetch_remote(url: str) -> tuple[bytes, str | None]:
    """The bytes at a URL and the media type its server names; the build's one network read.

    Tests replace this function, so no test reaches the network. Raises OSError or ValueError.
    Some image hosts refuse urllib's default user agent, so the request names the core.
    """
    request = urllib.request.Request(url, headers={"User-Agent": "obs-document"})
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
        media_type = response.headers.get_content_type() if response.headers.get("Content-Type") else None
        return response.read(), media_type


HOME = "home"
"""The chapter identifier a link to the manifest names; no note takes it."""


@dataclass
class _Vault:
    """The vault's notes, read once, and what parsing the included notes reaches."""

    root: Path
    manifest: Path
    notes: dict[Path, tuple[dict[str, object], str]]
    identities: dict[Path, str]
    reached: list[Path] = field(default_factory=list)
    links: list[tuple[dict[str, object], Path | None]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    validated: set[Path] = field(default_factory=set)
    files: dict[str, list[Path]] | None = None
    records: list[Record] = field(default_factory=list)
    notes_by_id: dict[str, tuple[Path, Record]] = field(default_factory=dict)

    def note_of(self, record: Record) -> tuple[Path, Record] | None:
        """The path and note record a record comes from; None for a row without a note."""
        identifier = record["id"] if record["type"] == "note" else record.get("note")
        return None if identifier is None else self.notes_by_id[identifier]

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def files_named(self, name: str) -> list[Path]:
        """The vault files outside hidden folders with this case-insensitive name, listed once."""
        if self.files is None:
            self.files = {}
            for path in sorted(self.root.rglob("*"), key=lambda item: item.as_posix().casefold()):
                if path.is_file() and not any(
                    part.startswith(".") for part in path.relative_to(self.root).parts
                ):
                    self.files.setdefault(path.name.casefold(), []).append(path)
        return self.files.get(name.casefold(), [])


def build_document(
    manifest_path: Path, capability_ids: set[str] | None = None,
    configuration_path: Path | None = None,
    execute_commands: bool = False,
) -> dict[str, object]:
    """Build semantic Document data from a manifest and its linked chapters.

    ``execute_commands`` is the build's authorization to run cmd fences from the vault root:
    producers first, then each rendering fence, whose captured output its node carries. Without
    it a rendering cmd fence fails; see capabilities/command-fences.
    """
    try:
        configuration: CoreConfig | None = (
            load_core_config(configuration_path) if configuration_path is not None else None
        )
    except CoreConfigError as error:
        raise VaultError(str(error)) from error
    manifest_path = manifest_path.resolve()
    vault_root = manifest_path.parent
    command_runner: Callable[[str], str] | None = None
    if execute_commands:
        timeout = (configuration.command_timeout_seconds if configuration is not None
                   else DEFAULT_COMMAND_TIMEOUT_SECONDS)
        try:
            run_producers(vault_root, True, timeout)
        except ProducerError as error:
            raise VaultError(str(error)) from error
        command_runner = partial(run_command, cwd=vault_root, timeout_seconds=timeout)
    manifest = read_note(manifest_path)
    metadata, body = manifest.metadata, manifest.body
    title = metadata.get("title", manifest_path.stem.replace("-", " ").title())
    if not isinstance(title, str) or not title.strip():
        raise VaultError("Manifest title must be a non-empty string.")
    try:
        validate_cover_metadata(metadata, manifest_path)
    except InputError as error:
        raise VaultError(str(error)) from error
    if configuration is not None and manifest_path.name != configuration.manifest_filename:
        raise VaultError(
            f"Manifest filename does not match core configuration: {manifest_path.name}"
        )
    if configuration is not None:
        project_configuration = vault_root / configuration.project_config_filename
        if project_configuration.is_file():
            try:
                validate_project_config(
                    json.loads(project_configuration.read_text(encoding="utf-8")),
                    project_configuration,
                )
            except (OSError, json.JSONDecodeError, InputError) as error:
                raise VaultError(str(error)) from error
    vault = _read_vault(manifest_path, metadata, body)
    _validate_note(manifest_path, vault)
    chapters, abstract = _parse_manifest(manifest, manifest_path, vault_root, vault.identities)
    _add_records(vault, chapters, title)
    links: list[dict[str, str]] = []
    assets: list[dict[str, str]] = []
    link_ids: set[str] = set()
    asset_ids: set[str] = set()
    capabilities: set[str] = set()
    included: set[Path] = {manifest_path}

    def context_of(path: Path, frontmatter: dict[str, object]) -> _Context:
        """What parsing one note's Markdown reads and adds to."""
        return _Context(
            path, vault, links, assets, link_ids, asset_ids, capability_ids or set(), capabilities,
            command_runner, frontmatter=frontmatter,
        )

    def parse_chapter(chapter: dict[str, object]) -> None:
        path = chapter.pop("_path")
        included.add(path)
        chapter_metadata, chapter_body = vault.notes.get(path) or read_note(path)[:2]
        _validate_note(path, vault)
        _metadata_links(chapter_metadata, path, vault)
        _query_selection(chapter_metadata.get("query"), path, vault)
        chapter["metadata"] = _json_value(chapter_metadata)
        context = context_of(path, chapter_metadata)
        content = _frontmatter_nodes(chapter_metadata, context)
        if "chapter-inclusion" in (capability_ids or set()):
            content.append({
                "type": "chapter-inclusion", "attrs": {"id": chapter["id"]}, "children": [],
            })
            capabilities.add("chapter-inclusion")
        parsed = _nodes(chapter_body, context)
        if parsed and "markdown" in (capability_ids or set()):
            content.append({"type": "markdown", "attrs": {}, "children": []})
            capabilities.add("markdown")
        content.extend(parsed)
        chapter["content"] = content
        for child in chapter["children"]:
            parse_chapter(child)

    for chapter in chapters:
        parse_chapter(chapter)
    _metadata_links(metadata, manifest_path, vault)
    manifest_context = context_of(manifest_path, metadata)
    abstract_nodes = _nodes(body[abstract:], manifest_context)
    manifest_nodes = _frontmatter_nodes(metadata, manifest_context)
    unlisted: list[dict[str, object]] = []
    while vault.reached:
        path = vault.reached.pop(0)
        if path in included:
            continue
        chapter = _unlisted_chapter(path, vault)
        parse_chapter(chapter)
        unlisted.append(chapter)
    chapters.extend(sorted(unlisted, key=lambda chapter: chapter["_relative"].casefold()))
    for chapter in unlisted:
        del chapter["_relative"]
    # Inclusion is final: an included note's frontmatter links were followed with its chapter,
    # and a note outside the Document includes nothing (capabilities/bases#Note records).
    for path, (fields, _) in vault.notes.items():
        record = vault.notes_by_id[vault.identities[path]][1]
        record["fieldNodes"] = _field_nodes(fields, "", context_of(path, fields))
        if path in vault.validated and fields.get("kind") == "quantity":
            record["quantity"] = document_quantity(fields)
    vault.reached.clear()
    for attrs, target in vault.links:  # Only an included note is a chapter a link can name.
        attrs["chapter"] = HOME if target == manifest_path else (
            vault.identities.get(target) if target in included else None)
    if "manifest" in (capability_ids or set()):
        manifest_nodes.append({"type": "manifest", "attrs": {}, "children": []})
        capabilities.add("manifest")
    if abstract_nodes and "markdown" in (capability_ids or set()):
        manifest_nodes.append({"type": "markdown", "attrs": {}, "children": []})
        capabilities.add("markdown")
    manifest_nodes.extend(abstract_nodes)
    return {
        "schemaVersion": 1,
        "manifest": {
            "title": title,
            "path": vault.relative(manifest_path),
            "metadata": _json_value(metadata),
            "abstract": manifest_nodes,
        },
        "chapters": chapters,
        "links": links,
        "assets": assets,
        "records": vault.records,
        "semanticResources": [],
        "diagnostics": [{"level": "warning", "message": message} for message in vault.warnings],
        "capabilities": sorted(capabilities),
    }


def _read_vault(manifest_path: Path, metadata: dict[str, object], body: str) -> _Vault:
    """Read every vault note outside hidden folders once; see the bases capability."""
    vault_root = manifest_path.parent
    notes: dict[Path, tuple[dict[str, object], str]] = {}
    identities: dict[Path, str] = {}
    used = {HOME}
    for path in sorted(vault_root.rglob("*.md"), key=lambda item: item.as_posix().casefold()):
        relative = path.relative_to(vault_root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        source_path = path.resolve()
        if not source_path.is_relative_to(vault_root):
            raise VaultError(
                f"Note path escapes the vault: {relative} (vault {vault_root}); "
                "replace the link to outside the vault with the note itself."
            )
        notes[source_path] = (metadata, body) if source_path == manifest_path else read_note(source_path)[:2]
        identities[source_path] = _unique_identifier(relative.with_suffix("").as_posix(), used)
    return _Vault(vault_root, manifest_path, notes, identities)


def _note_title(path: Path, vault: _Vault) -> object:
    """A note's title as authored: its title or term, else its first heading, else its file name."""
    metadata, body = vault.notes[path]
    heading = next((line[2:].strip() for line in body.splitlines() if line.startswith("# ")), None)
    return metadata.get("title") or metadata.get("term") or heading or path.stem.replace("-", " ").title()


def _add_records(vault: _Vault, chapters: list[dict[str, object]], title: str) -> None:
    """Every record a Base view can select, of each type; see document.schema.json ($defs/record)."""
    used = set(vault.identities.values()) | {HOME}
    titles: dict[Path, str] = {vault.manifest: title}
    toc: list[tuple[dict[str, object], int]] = []

    def walk(items: list[dict[str, object]], depth: int) -> None:
        for chapter in items:
            toc.append((chapter, depth))
            titles[chapter["_path"]] = str(chapter["title"])
            walk(chapter["children"], depth + 1)
    walk(chapters, 0)

    def add(kind: str, key: str, fields: dict[str, object], note: str | None = None) -> None:
        """Add a record; its id is the kebab-cased type and key, unique among all records."""
        prefix = re.sub(r"(?<=[a-z])(?=[A-Z])", "-", kind)
        vault.records.append({
            "id": _unique_identifier(f"{prefix}-{key}", used), "type": kind,
            **({"note": note} if note else {}), "fields": fields,
        })

    for path, (metadata, _) in vault.notes.items():
        record = {"id": vault.identities[path], "type": "note", "path": vault.relative(path),
                  "fields": _json_value(metadata), **({IGNORED: True} if metadata.get(IGNORED) else {})}
        vault.records.append(record)
        vault.notes_by_id[record["id"]] = (path, record)
    for chapter, depth in toc:
        path = chapter["_path"]
        add("chapter", vault.identities[path], {
            "chapter": chapter["title"], "title": chapter["title"], "depth": str(depth),
            "slug": chapter["id"], "sourcePath": vault.relative(path),
        }, vault.identities[path])
    for path, (metadata, body) in vault.notes.items():
        note, source = vault.identities[path], vault.relative(path)
        name = titles.get(path) or _note_title(path, vault)
        for category, identifier, text in paragraph_marks(body):
            add("tag", f"{note}-{category}-{identifier}", {
                "sourcePath": source, "type": category, "label": identifier, "text": text,
                "source": name if isinstance(name, str) else path.stem,
            }, note)
        if metadata.get("kind") == "glossary":
            add("glossary", note, {
                "sourcePath": source, "term": _json_value(metadata.get("term")),
                "definition": _json_value(metadata.get("definition")),
                "aliases": _json_value(metadata.get("aliases") or []),
            }, note)
    manifest = vault.notes[vault.manifest][0]
    for key, value in manifest.items():
        if key not in {"history", "obs"} and not ADAPTER_NAMESPACE.fullmatch(str(key)):
            add("documentMetadata", str(key), {"key": str(key), "value": _json_value(value)})
    history = manifest.get("history")
    for index, entry in enumerate(history if isinstance(history, list) else [], 1):
        if isinstance(entry, dict):
            add("documentHistory", str(index), {**_json_value(entry), "date": _json_value(entry.get("date") or "")})


def _unlisted_chapter(path: Path, vault: _Vault) -> dict[str, object]:
    """An included note the manifest does not list; see input-model "Chapter content"."""
    title = _note_title(path, vault)
    if not isinstance(title, str) or not title.strip():
        raise VaultError(
            f"Note title must be a non-empty string: {vault.relative(path)}; "
            "give the frontmatter title a text value."
        )
    return {
        "id": vault.identities[path], "title": title.strip(), "toc": False,
        "content": [], "children": [], "_path": path, "_relative": vault.relative(path),
    }


def _metadata_links(metadata: object, source_path: Path, vault: _Vault) -> None:
    """Follow wikilinks and embeds in frontmatter string values."""
    if isinstance(metadata, dict):
        for value in metadata.values():
            _metadata_links(value, source_path, vault)
    elif isinstance(metadata, list):
        for value in metadata:
            _metadata_links(value, source_path, vault)
    elif isinstance(metadata, str):
        for match in _SEMANTIC.finditer(metadata):
            if match["target"]:
                _link(match["target"].strip(), source_path, vault)


def _select(selects, vault: _Vault) -> None:
    """Include the notes that selects(fields, path, body) chooses."""
    for path, (fields, body) in vault.notes.items():
        if selects(fields, vault.relative(path), body):
            vault.reached.append(path)


def _query_owner(identity: object, key: str, source_path: Path, vault: _Vault) -> Path:
    path = (vault.root / f"{identity}.md").resolve()
    if path not in vault.notes or path == vault.manifest:
        raise VaultError(
            f"Query {key} does not resolve in {vault.relative(source_path)}: {identity}; "
            "name a vault note by its path without .md."
        )
    return path


def _query_selection(query: object, source_path: Path, vault: _Vault, owners: tuple[Path, ...] = ()) -> None:
    """Include the notes a frontmatter query or cards metric selects, and its owner notes."""
    if not isinstance(query, dict) or not isinstance(query.get("where"), list):
        return
    if "secondary" in query:
        vault.reached.append(_query_owner(query["secondary"], "secondary", source_path, vault))
    chain = [query["where"]]
    seen = set(owners)
    owner = query.get("from")
    while owner is not None:
        path = _query_owner(owner, "from", source_path, vault)
        if path in seen:
            raise VaultError(
                f"Query from is cyclic in {vault.relative(source_path)}: {owner}; "
                "remove one from reference of the cycle."
            )
        seen.add(path)
        vault.reached.append(path)
        _validate_note(path, vault)
        owned = vault.notes[path][0].get("query")
        if not isinstance(owned, dict) or not isinstance(owned.get("where"), list):
            raise VaultError(
                f"Query from names a note without a query in {vault.relative(source_path)}: "
                f"{owner}; add a query to that note or remove from."
            )
        chain.append(owned["where"])
        owner = owned.get("from")
    _select(lambda fields, path, body: all(
        conditions_select(where, fields, path, note_marks(body)) for where in chain), vault)


def _card_selection(card: dict[str, object], source_path: Path, vault: _Vault) -> None:
    """Include the notes a card references and the records its metrics count and divide by."""
    series = card.get("obs", {}).get("metricsFrom")
    if series:
        references = [("obs.metricsFrom.sourceNote", series["sourceNote"])]
        if "link" in series:
            references.append(("obs.metricsFrom.link.note", series["link"]["note"]))
        for field_name, identity in references:
            path = (vault.root / f"{identity}.md").resolve()
            if path not in vault.notes:
                raise VaultError(
                    f"Card {field_name} does not resolve in {vault.relative(source_path)}: "
                    f"{identity}; name a vault note by its path without .md."
                )
            vault.reached.append(path)
        _query_selection({"where": series["where"]}, source_path, vault)
    for metric in card.get("metrics", []):
        _query_selection(metric, source_path, vault)
        if "denominator" in metric:
            population = {key: metric[key] for key in ("from",) if key in metric}
            _query_selection({**population, "where": metric["denominator"]}, source_path, vault)


def _validate_members(definition: dict[str, object], source_path: Path, vault: _Vault, place: str = "") -> None:
    """Each view's obs.members names distinct Markdown notes of the vault by vault-relative path
    (generic-tables); the schema has checked their shape."""
    for index, view in enumerate(definition["views"]):
        members = (view.get("obs") or {}).get("members", [])
        seen: set[Path] = set()
        for number, member in enumerate(members):
            entry = member["path"]
            relative = PurePosixPath(entry)
            resolved = (vault.root / entry).resolve()
            name = f"view {view.get('name')!r}" if view.get("name") is not None else f"view {index + 1}"
            problem = (
                f"{entry!r} of {name} is absolute or leaves the vault"
                if relative.is_absolute() or re.match(r"[A-Za-z]:", entry) or ".." in relative.parts
                or not resolved.is_relative_to(vault.root)
                else f"{entry!r} of {name} is not a Markdown note path" if relative.suffix.lower() != ".md"
                else f"{entry!r} of {name} names no note of the vault" if resolved not in vault.notes
                else f"{entry!r} of {name} repeats an earlier member" if resolved in seen
                else ""
            )
            if problem:
                field = ", ".join(item for item in (place, f"views[{index}].obs.members[{number}].path") if item)
                raise input_error(source_path, field, problem,
                                  "Write the vault-relative path of a note, with .md, once per view, such as "
                                  "items/a.md; see capabilities/bases")
            seen.add(resolved)


def _base_selection(definition: object, source_path: Path, vault: _Vault, place: str) -> None:
    """Include the notes a Base definition selects and the notes of the rows it selects."""
    if not isinstance(definition, dict):
        return
    try:
        selects = base_selects(definition)
    except InputError as error:
        raise VaultError(
            f"{error} ({place} in {vault.relative(source_path)}); "
            "use the Bases filter grammar of generic-tables."
        ) from error
    for record in vault.records:
        owner = vault.note_of(record)
        if owner is not None and selects(record, owner[1]):
            vault.reached.append(owner[0])


def _validate_note(path: Path, vault: _Vault) -> None:
    """Check an included note's frontmatter contracts once; see input-model "Chapter content"."""
    if path in vault.validated:
        return
    vault.validated.add(path)
    metadata = vault.notes[path][0] if path in vault.notes else read_note(path).metadata
    try:
        validate_note_profile(metadata, path)
        if metadata.get("kind") == "quantity":
            validate_quantity(metadata, path)
        if "query" in metadata:
            validate_count_query(metadata["query"], path)
    except InputError as error:
        raise VaultError(str(error)) from error


def _parse_manifest(
    manifest: Note, manifest_path: Path, vault_root: Path, identities: dict[Path, str],
) -> tuple[list[dict[str, object]], int]:
    body = manifest.body
    body_lines = lines(body)
    chapters: list[dict[str, object]] = []
    parents: list[dict[str, object]] = []
    seen: set[Path] = set()
    abstract_start = 0
    found = False

    def entry_error(index: int, problem: str, remedy: str) -> str:
        """A manifest entry's error, naming its source line; see capabilities/manifest."""
        line = manifest.source_line(index)
        return f"{manifest_path}: line {line}: manifest entry {problem}; {remedy}."

    for index, line in enumerate(body_lines):
        if not line.strip():
            if found:
                abstract_start = sum(len(item) for item in body_lines[:index + 1])
                break
            continue
        match = _MANIFEST_ITEM.fullmatch(line.rstrip("\r\n"))
        if match is None:
            if not found:
                return [], 0
            abstract_start = sum(len(item) for item in body_lines[:index])
            break
        found = True
        depth = len(match["indent"]) // 2
        if len(match["indent"]) % 2:
            raise VaultError(entry_error(
                index, "must use two-space indentation",
                "indent each nesting level by two spaces",
            ))
        if depth > len(parents):
            raise VaultError(entry_error(
                index, "skips a nesting level",
                "nest the entry one level below the entry above it",
            ))
        target = match["target"].strip()
        relative = Path(target)
        if relative.is_absolute() or ".." in relative.parts:
            raise VaultError(entry_error(
                index, "escapes the vault",
                "link to a note inside the vault",
            ))
        if not relative.suffix:
            relative = relative.with_suffix(".md")
        if relative.suffix.lower() != ".md":
            raise VaultError(entry_error(
                index, "must link to a Markdown note",
                "link to a .md note",
            ))
        path = (vault_root / relative).resolve()
        if not path.is_relative_to(vault_root) or path == manifest_path or not path.is_file():
            raise VaultError(entry_error(
                index, f"links to {target}, which does not resolve",
                "link to an existing note of the vault other than the manifest",
            ))
        if path in seen:
            raise VaultError(entry_error(
                index, f"links to {target} a second time",
                "list each note once",
            ))
        seen.add(path)
        if path not in identities:
            identities[path] = _unique_identifier(
                relative.with_suffix("").as_posix(), set(identities.values()) | {HOME},
            )
        chapter = {
            "id": identities[path],
            "title": (match["label"] or relative.stem.replace("-", " ").title()).strip(),
            "content": [],
            "children": [],
            "_path": path,
        }
        if not chapter["title"]:
            raise VaultError(entry_error(
                index, "has an empty chapter title",
                "write a label after the | or remove the |",
            ))
        if depth == 0:
            chapters.append(chapter)
        else:
            parents[depth - 1]["children"].append(chapter)
        parents[depth:] = [chapter]
    else:
        abstract_start = len(body)
    return chapters, abstract_start


def _frontmatter_nodes(metadata: dict[str, object], context: _Context) -> list[dict[str, object]]:
    nodes: list[dict[str, object]] = []

    def add(
        identifier: str, attrs: dict[str, object], children: list[dict[str, object]] | None = None,
    ) -> None:
        if identifier in context.capability_ids:
            nodes.append({"type": identifier, "attrs": attrs, "children": children or []})
            context.capabilities.add(identifier)

    if metadata and "markdown-frontmatter" in context.capability_ids:
        add("markdown-frontmatter", {"metadata": _json_value(metadata)}, _field_nodes(metadata, "", context))
    if "obs" in metadata:
        add("profiles", {"profile": _json_value(metadata["obs"])})
    if metadata.get("kind") == "quantity":
        add("quantities", {"metadata": _json_value(metadata), "quantity": document_quantity(metadata)})
    if "query" in metadata:
        query = _json_value(metadata["query"])
        add("queries", {"query": query})
        add("count-query", {"query": query})
    if metadata.get("kind") in {"glossary", "reference"} or "reference" in metadata:
        add("references", {"metadata": _json_value(metadata)})
    return nodes


@dataclass
class _Context:
    """What parsing one note's Markdown reads and adds to; see input-model "Chapter content"."""

    source_path: Path
    vault: _Vault
    links: list[dict[str, str]]
    assets: list[dict[str, str]]
    link_ids: set[str]
    asset_ids: set[str]
    capability_ids: set[str]
    capabilities: set[str]
    command_runner: Callable[[str], str] | None = None
    fences: dict[str, int] = field(default_factory=dict)
    field_path: str = ""
    frontmatter: dict[str, object] = field(default_factory=dict)


def _nodes(source: str, context: _Context) -> list[dict[str, object]]:
    tokens = parser().parse(source)
    return _blocks(tokens, 0, len(tokens), context)


def _closing(tokens: list[Token], position: int) -> int:
    """The index of the token that closes the block tokens[position] opens."""
    opening = tokens[position]
    closing = opening.type.removesuffix("_open") + "_close"
    return next(
        index for index in range(position + 1, len(tokens))
        if tokens[index].type == closing and tokens[index].level == opening.level
    )


def _blocks(
    tokens: list[Token], position: int, end: int, context: _Context,
) -> list[dict[str, object]]:
    """The block nodes of tokens[position:end], each block with its nested blocks."""
    result: list[dict[str, object]] = []
    while position < end:
        token = tokens[position]
        if token.type == "heading_open":
            result.append({
                "type": "section", "attrs": {"level": int(token.tag[1:])},
                "children": _inline_nodes(tokens[position + 1], context),
            })
            position = _closing(tokens, position) + 1
        elif token.type == "paragraph_open":
            result.extend(_paragraphs(_inline_nodes(tokens[position + 1], context)))
            position = _closing(tokens, position) + 1
        elif token.type in {"bullet_list_open", "ordered_list_open"}:
            closing = _closing(tokens, position)
            items = []
            item = position + 1
            while item < closing:
                item_end = _closing(tokens, item)
                items.append({
                    "type": "list-item", "attrs": {},
                    "children": _blocks(tokens, item + 1, item_end, context),
                })
                item = item_end + 1
            result.append({
                "type": "list", "attrs": {
                    "ordered": token.type == "ordered_list_open", "tight": _tight(tokens, position, closing),
                },
                "children": items,
            })
            position = closing + 1
        elif token.type in {"fence", "code_block"}:
            result.append(_fence_node(token, context))
            position += 1
        elif token.type == "blockquote_open":
            closing = _closing(tokens, position)
            result.append(_callout(tokens, position, closing, context) or {
                "type": "quote", "attrs": {},
                "children": _blocks(tokens, position + 1, closing, context),
            })
            position = closing + 1
        elif token.type == "table_open":
            closing = _closing(tokens, position)
            result.append({"type": "table", "attrs": {}, "children": _table_rows(
                tokens[position:closing], context,
            )})
            position = closing + 1
        elif token.type == "hr":
            result.append({"type": "rule", "attrs": {}, "children": []})
            position += 1
        elif token.type == "math_block":
            result.append({
                "type": "math", "attrs": {"display": True}, "children": [],
                "text": token.content.strip("\n"),
            })
            position += 1
        else:
            position += 1
    return result


@cache
def _block_node() -> Draft202012Validator:
    """Whether a node is a block node; document.schema.json ($defs/blockNode) owns the list."""
    schema = json.loads(Path(__file__).with_name("document.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator({**schema["$defs"]["blockNode"], "$defs": schema["$defs"]})


def _paragraphs(children: list[dict[str, object]]) -> list[dict[str, object]]:
    """A paragraph's inline nodes as paragraphs with each block node between them, never inside
    one; see capabilities/markdown#Document nodes. The text around a block node keeps its
    authored characters; a paragraph left with only whitespace is dropped."""
    result: list[dict[str, object]] = []
    run: list[dict[str, object]] = []
    for child in [*children, None]:
        if child is not None and not _block_node().is_valid(child):
            run.append(child)
            continue
        if any(node["type"] != "text" or node["text"].strip() for node in run):
            result.append({"type": "paragraph", "attrs": {}, "children": run})
        run = []
        if child is not None:
            result.append(child)
    return result


def _tight(tokens: list[Token], position: int, closing: int) -> bool:
    """Whether the list tokens[position:closing] was authored tight; see capabilities/markdown.

    markdown-it records a tight list only by hiding its items' own paragraphs.
    """
    level = tokens[position].level + 2
    return not any(
        token.type == "paragraph_open" and token.level == level and not token.hidden
        for token in tokens[position + 1:closing]
    )


def _table_rows(tokens: list[Token], context: _Context) -> list[dict[str, object]]:
    """A pipe table's rows; each cell names whether it is a header and its authored alignment."""
    rows: list[dict[str, object]] = []
    for index, token in enumerate(tokens):
        if token.type == "tr_open":
            rows.append({"type": "table-row", "attrs": {}, "children": []})
        elif token.type in {"th_open", "td_open"}:
            attrs: dict[str, object] = {"header": token.type == "th_open"}
            style = str(token.attrGet("style") or "")
            if style.startswith("text-align:"):
                attrs["align"] = style.removeprefix("text-align:")
            rows[-1]["children"].append({
                "type": "table-cell", "attrs": attrs,
                "children": _inline_nodes(tokens[index + 1], context),
            })
    return rows


def _callout(
    tokens: list[Token], position: int, closing: int, context: _Context,
) -> dict[str, object] | None:
    """A callout node for the blockquote tokens[position:closing], or None; see capabilities/callouts.

    The marker is the first line of the blockquote's first paragraph; the rest of the
    blockquote, nested blocks included, is the body.
    """
    if "callouts" not in context.capability_ids or tokens[position + 1].type != "paragraph_open":
        return None
    inline = tokens[position + 2]
    callout = parse_callout(inline.content.splitlines()[0].strip()) if inline.content else None
    if callout is None:
        return None
    children = inline.children or []
    first_break = next(
        (index for index, child in enumerate(children) if child.type in {"softbreak", "hardbreak"}),
        None,
    )
    body_tokens = list(tokens[position + 1:closing])
    paragraph_end = _closing(tokens, position + 1) - position - 1
    if first_break is None:
        body_tokens = body_tokens[paragraph_end + 1:]
    else:
        rest = copy(inline)
        rest.children = children[first_break + 1:]
        rest.content = inline.content.split("\n", 1)[1]
        body_tokens[1] = rest
    context.capabilities.add("callouts")
    return {
        "type": "callouts",
        "attrs": {"kind": callout["type"], "title": callout["title"]},
        "children": _blocks(body_tokens, 0, len(body_tokens), context),
    }


def _fence_node(token: Token, context: _Context) -> dict[str, object]:
    """The node of one fenced or indented code block; see capabilities/markdown."""
    source_path, vault, capability_ids = context.source_path, context.vault, context.capability_ids
    info = token.info.strip().split() if token.type == "fence" else []
    language = info[0] if info else ""
    silent_command = info == ["cmd", "silent"]
    figure_descriptor: dict[str, object] | None = None
    if language in {"base", "cards", "property-editor", "cmd", "figure"}:
        context.fences[language] = context.fences.get(language, 0) + 1
    place = f"{language} fence {context.fences.get(language, 0)}"
    try:
        if language == "base":
            try:
                specification = yaml.safe_load(token.content)
            except yaml.YAMLError as error:
                raise input_error(source_path, place, f"is not valid YAML: {error}",
                                  "Write YAML; see capabilities/bases") from error
            validate_base_definition(specification, source_path, place)
            _validate_members(specification, source_path, vault, place)
            _base_selection(specification, source_path, vault, place)
        elif language == "cards":
            specification = parse_card_spec(token.content, source_path, place)
            card_bodies = []
            body_context = replace(context, capabilities=set(), fences={})
            for card in specification["cards"]:
                _card_selection(card, source_path, vault)
                card_bodies.append({
                    "type": "document", "attrs": {}, "children": _nodes(card["body"], body_context),
                })
        elif language == "property-editor":
            specification = parse_property_editor(token.content, source_path, context.frontmatter, place)
        elif language == "cmd":
            try:
                validate_command(token.content)
            except InputError as error:
                raise input_error(source_path, place, "is empty", "Write the command to run or "
                                  "remove the fence; see capabilities/command-fences") from error
        elif language == "figure":
            try:
                figure_descriptor = json.loads(token.content)
            except json.JSONDecodeError:
                figure_descriptor = None
            if figure_descriptor is not None:
                if not isinstance(figure_descriptor, dict):
                    raise input_error(source_path, place, "must hold a JSON object",
                                      "Write the descriptor as one JSON object; "
                                      "see capabilities/figure-descriptor")
                validate_figure_descriptor(figure_descriptor, source_path, place)
    except (InputError, FigureDescriptorError, yaml.YAMLError) as error:
        raise VaultError(str(error)) from error
    fence_type = {
        "base": "bases",
        "cmd": "command-fences",
        "cards": "cards-metrics",
        "property-editor": "property-editors",
    }.get(language)
    if language == "figure":
        fence_type = "figure-descriptor" if figure_descriptor is not None else "figures"
    if fence_type is None or fence_type not in capability_ids:
        return {
            "type": "code", "attrs": {"language": language},
            "children": [], "text": token.content,
        }
    attrs: dict[str, object] = {"source": token.content}
    if silent_command:
        attrs["silent"] = True
    elif language == "cmd":
        attrs["output"] = _command_output(token.content, source_path, place, context.command_runner)
    if language == "figure" and figure_descriptor is not None:
        attrs = {"descriptor": figure_descriptor}
    elif language in {"base", "figure"}:
        try:
            spec = yaml.safe_load(token.content)
        except yaml.YAMLError as error:
            raise VaultError(f"Invalid {language} fence in {source_path}: {error}") from error
        if spec is not None:
            attrs["spec"] = _json_value(spec)
    elif language == "property-editor":
        attrs["spec"] = _json_value(specification)
        attrs["writes"] = property_editor_writes(specification)
    elif language == "cards":
        attrs["spec"] = _json_value(specification)
        context.capabilities.update(body_context.capabilities)
    context.capabilities.add(fence_type)
    return {
        "type": fence_type, "attrs": attrs,
        "children": card_bodies if language == "cards" else [],
    }


def _command_output(command: str, source_path: Path, place: str,
                    runner: Callable[[str], str] | None) -> str:
    """The captured output of a rendering cmd fence; see capabilities/command-fences."""
    if runner is None:
        raise VaultError(str(input_error(
            source_path, place, "runs a command, and this build is not authorized to run commands",
            "Review the command, then build with --execute-commands; see capabilities/command-fences",
        )))
    try:
        return runner(command.strip())
    except CommandError as error:
        raise VaultError(str(input_error(
            source_path, place, str(error).rstrip("."),
            "Fix the command or what it reads; see capabilities/command-fences",
        ))) from error


_INLINE_MARKS = {"em": "emphasis", "strong": "strong", "s": "strikethrough"}
"""Inline marks, by markdown-it token name, and the structural node each becomes."""


def _inline_nodes(token: Token, context: _Context) -> list[dict[str, object]]:
    """The inline nodes of one inline token; marks nest, link text carries attrs.link."""
    result: list[dict[str, object]] = []
    open_nodes = [result]
    link: dict[str, str] | None = None
    children = token.children or []
    for index, child in enumerate(children):
        output = open_nodes[-1]
        mark = child.type.removesuffix("_open").removesuffix("_close")
        if mark in _INLINE_MARKS and child.type.endswith("_open"):
            node = {"type": _INLINE_MARKS[mark], "attrs": {}, "children": []}
            output.append(node)
            open_nodes.append(node["children"])
        elif mark in _INLINE_MARKS:
            open_nodes.pop()
        elif child.type == "link_open":
            href = child.attrGet("href") or ""
            link = _resource(context.links, context.link_ids, _link_label(children[index + 1:]), href)
        elif child.type == "link_close":
            link = None
        elif child.type == "image":
            src = child.attrGet("src") or ""
            asset = _asset(context, child.content or src, src, _image_file(src, child.content, context))
            if "attachments" in context.capability_ids:
                output.append({
                    "type": "attachments", "attrs": {"asset": asset["id"], "label": child.content},
                    "children": [],
                })
                context.capabilities.add("attachments")
            else:
                output.append({"type": "text", "attrs": {"asset": asset["id"]}, "children": [], "text": child.content})
        elif child.type == "code_inline":
            output.append({"type": "code", "attrs": {}, "children": [], "text": child.content})
        elif child.type in {"math_inline", "math_inline_double"}:
            output.append({
                "type": "math", "attrs": {"display": child.type == "math_inline_double"},
                "children": [], "text": child.content,
            })
        elif child.type in {"text", "softbreak", "hardbreak"}:
            text = "\n" if child.type != "text" else child.content
            if link:
                output.append({"type": "text", "attrs": {"link": link["id"]}, "children": [], "text": text})
            else:
                output.extend(_semantic_text_nodes(text, context))
    return result


def _field_nodes(value: object, name: str, context: _Context) -> list[dict[str, object]]:
    """One field node per nonempty string in a metadata value, by dotted path; see markdown-frontmatter."""
    if isinstance(value, dict):
        return [
            node for key, item in value.items()
            for node in _field_nodes(item, f"{name}.{key}" if name else str(key), context)
        ]
    if isinstance(value, list):
        return [
            node for index, item in enumerate(value)
            for node in _field_nodes(item, f"{name}.{index}", context)
        ]
    if not isinstance(value, str) or not value.strip():
        return []
    tokens = parser().parseInline(value)
    children = _bare_urls(_inline_nodes(tokens[0], replace(context, field_path=name)), context)
    return [{"type": "field", "attrs": {"name": name}, "children": children}]


_BARE_URL = re.compile(r"https?://[^\s<>]*[^\s<>.,;:!?'\")\]]", re.IGNORECASE)


def _bare_urls(nodes: list[dict[str, object]], context: _Context) -> list[dict[str, object]]:
    """A field's plain text with each bare http(s) URL as link text, as Obsidian shows it."""
    result: list[dict[str, object]] = []
    for node in nodes:
        if node["type"] in {"emphasis", "strong", "strikethrough"}:
            result.append({**node, "children": _bare_urls(node["children"], context)})
            continue
        if node["type"] != "text" or node["attrs"]:
            result.append(node)
            continue
        text, position = node["text"], 0
        for match in _BARE_URL.finditer(text):
            if match.start() > position:
                result.append({**node, "text": text[position:match.start()]})
            link = _resource(context.links, context.link_ids, match[0], match[0])
            result.append({"type": "text", "attrs": {"link": link["id"]}, "children": [], "text": match[0]})
            position = match.end()
        if position < len(text):
            result.append({**node, "text": text[position:]})
    return result


def _semantic_text_nodes(text: str, context: _Context) -> list[dict[str, object]]:
    source_path, vault, links, link_ids = context.source_path, context.vault, context.links, context.link_ids
    capability_ids, capabilities = context.capability_ids, context.capabilities
    nodes: list[dict[str, object]] = []
    position = 0
    for match in _SEMANTIC.finditer(text):
        if match.start() > position:
            nodes.append({"type": "text", "attrs": {}, "children": [], "text": text[position:match.start()]})
        value = match.group(0)
        target = (match["target"] or "").strip()
        resolved = _link(target, source_path, vault, value) if target else None
        is_base = bool(match["embed"]) and Path(target).suffix == ".base"
        definition: object = None
        if is_base and resolved is None:
            raise VaultError(
                f"Base does not exist in {vault.relative(source_path)}: {value} matches no vault file; "
                f"create {target} in the vault or embed the vault path of an existing .base file."
            )
        if is_base and resolved is not None:
            try:
                definition = yaml.safe_load(resolved.read_text(encoding="utf-8-sig"))
            except (OSError, yaml.YAMLError) as error:
                raise VaultError(
                    f"Cannot read the Base {target} embedded in {vault.relative(source_path)}: "
                    f"{error}; make the .base file valid YAML."
                ) from error
            try:
                validate_base_definition(definition, resolved)
                _validate_members(definition, resolved, vault)
            except InputError as error:
                raise VaultError(
                    f"{error} {vault.relative(source_path)} embeds it as {target}."
                ) from error
            _base_selection(definition, source_path, vault, f"embedded {target}")
        if is_base and "registers" in capability_ids:
            nodes.append({
                "type": "registers",
                "attrs": _register_attrs(value, target, match["heading"] or "", definition, source_path, vault),
                "children": [],
            })
            capabilities.add("registers")
        elif match["embed"] and "embeds" in capability_ids:
            attrs: dict[str, object] = {"target": target, "chapter": None}
            if Path(target).suffix not in {"", ".md", ".base"}:
                if resolved is None:
                    raise VaultError(
                        f"Asset does not exist in {vault.relative(source_path)}: {value}; "
                        f"add {target} to the vault or correct the embed."
                    )
                attrs["asset"] = _asset(context, target, target, resolved)["id"]
            vault.links.append((attrs, resolved))
            nodes.append({"type": "embeds", "attrs": attrs, "children": []})
            capabilities.add("embeds")
        elif value.startswith("[[") and "wikilinks" in capability_ids:
            attrs = {"target": target, "chapter": None, "heading": match["heading"] or "", "label": match["label"] or target}
            vault.links.append((attrs, resolved))
            nodes.append({"type": "wikilinks", "attrs": attrs, "children": []})
            _resource(links, link_ids, attrs["label"], target)
            capabilities.add("wikilinks")
        elif "marks" in capability_ids:
            nodes.append({"type": "marks", "attrs": {"category": match["category"], "id": match["id"]}, "children": []})
            capabilities.add("marks")
        else:
            nodes.append({"type": "text", "attrs": {}, "children": [], "text": value})
        position = match.end()
    if position < len(text):
        nodes.append({"type": "text", "attrs": {}, "children": [], "text": text[position:]})
    return nodes


def _register_attrs(
    embed: str, target: str, heading: str, definition: object, source_path: Path, vault: _Vault,
) -> dict[str, object]:
    """The registers node's attrs: the Base, the embedded view and each view's rows; see capabilities/registers."""
    source = vault.relative(source_path)
    names = [view.get("name") for view in definition["views"]]
    view = None
    if heading:
        if heading not in names:
            raise VaultError(
                f"Register view does not exist in {source}: {embed} names no view of {target}; "
                f"name one of: {', '.join(str(name) for name in names if name is not None)}."
            )
        view = names.index(heading)
    rows = []
    for selects, members in zip(view_selectors(definition), map(member_order, definition["views"])):
        selected = [(record, None if (owner := vault.note_of(record)) is None else owner[1])
                    for record in vault.records]
        selected = [(record, note) for record, note in selected if selects(record, note)]
        if members is not None:  # The members' order is the view's row order (generic-tables).
            def position(pair: tuple[Record, Record | None]) -> int:
                owner = pair[0] if pair[0]["type"] == "note" else pair[1]
                return members.get(owner["path"], len(members)) if owner is not None else len(members)
            selected.sort(key=position)
        rows.append([record["id"] for record, _ in selected])
    return {
        "target": target, "heading": heading, "base": _json_value(definition), "view": view, "rows": rows,
    }


def _link_label(children: list[Token]) -> str:
    text: list[str] = []
    for child in children:
        if child.type == "link_close":
            break
        if child.type in {"text", "code_inline", "image"}:
            text.append(child.content)
    return "".join(text)


def _resource(
    resources: list[dict[str, str]], identifiers: set[str], label: str, href: str,
) -> dict[str, str]:
    existing = next((item for item in resources if item["href"] == href and item["label"] == label), None)
    if existing is not None:
        return existing
    resource = {"id": _unique_identifier(label or href, identifiers), "href": href, "label": label or href}
    resources.append(resource)
    return resource


def _asset(context: _Context, label: str, href: str, path: Path | None) -> dict[str, str]:
    """The one asset of a referenced file, with its bytes; see architecture "Asset bytes".

    A vault file is one asset however often it is referenced, and so is a URL; ``path`` is
    None for a URL. A remote image is fetched once; one it cannot fetch is a warning.
    """
    relative = context.vault.relative(path) if path is not None else None
    existing = next((
        item for item in context.assets
        if (item.get("path") == relative if relative is not None else item["href"] == href)
    ), None)
    if existing is not None:
        return existing
    asset = {
        "id": _unique_identifier(label or href, context.asset_ids),
        "href": href,
        "mediaType": mimetypes.guess_type(relative or urlparse(href).path)[0] or "application/octet-stream",
    }
    if path is not None:
        asset["path"] = relative
        asset["data"] = base64.b64encode(path.read_bytes()).decode("ascii")
    elif urlparse(href).scheme.lower() in REMOTE_SCHEMES:
        try:
            data, media_type = fetch_remote(href)
        except (OSError, ValueError) as error:
            place = context.vault.relative(context.source_path)
            if context.field_path:
                place = f"{place}: {context.field_path}"
            context.vault.warnings.append(
                f"{place}: remote image {href} cannot be fetched ({error}). "
                f"Save the image into the vault and embed it locally: ![{label}](<vault path>)."
            )
        else:
            asset["mediaType"] = media_type or asset["mediaType"]
            asset["data"] = base64.b64encode(data).decode("ascii")
    context.assets.append(asset)
    return asset


def _image_file(src: str, label: str, context: _Context) -> Path | None:
    """The vault file a Markdown image or marked attachment names, next to its note; None for a URL."""
    parsed = urlparse(src)
    if parsed.scheme or parsed.netloc:
        return None
    source = context.vault.relative(context.source_path)
    syntax = f"![{label}]({src})"
    path = (context.source_path.parent / unquote(parsed.path)).resolve()
    if not path.is_relative_to(context.vault.root):
        raise VaultError(f"Asset escapes the vault in {source}: {syntax}; keep the file inside the vault.")
    if not path.is_file():
        raise VaultError(
            f"Asset does not exist in {source}: {syntax}; "
            f"add {context.vault.relative(path)} to the vault or correct the path."
        )
    return path


def _link(target: str, source_path: Path, vault: _Vault, syntax: str = "") -> Path | None:
    """Resolve a link or embed target and include a reached note; warn for a missing note.

    Resolution follows input-model ("Remaining chapter content"): source-relative path,
    vault-relative path, then a bare name that matches exactly one non-hidden vault file (a
    Markdown note by its name, then by its alias). ``syntax`` is the link as written, for errors.
    """
    syntax = syntax or f"[[{target}]]"
    relative = Path(target)
    source = vault.relative(source_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise VaultError(f"Link escapes the vault in {source_path}: {target}")
    if not relative.suffix:
        relative = relative.with_suffix(".md")
    for root in (source_path.parent, vault.root):
        path = (root / relative).resolve()
        if not path.is_relative_to(vault.root):
            raise VaultError(f"Link escapes the vault in {source_path}: {target}")
        if path.is_file():
            break
    else:
        path = None
        if len(relative.parts) == 1:
            if relative.suffix == ".md":
                name = relative.stem.casefold()
                matches = [note for note in vault.notes if note != vault.manifest and note.stem.casefold() == name]
                if not matches:
                    matches = [
                        note for note, (metadata, _) in vault.notes.items()
                        if note != vault.manifest and name in _aliases(metadata)
                    ]
            else:
                matches = vault.files_named(relative.name)
            if len(matches) > 1:
                raise VaultError(
                    f"Ambiguous {'note' if relative.suffix == '.md' else 'file'} name in {source}: "
                    f"{syntax} matches {', '.join(vault.relative(match) for match in matches)}; "
                    f"{'embed' if syntax.startswith('!') else 'link'} the vault path instead."
                )
            path = matches[0] if matches else None
    if path is None:
        if relative.suffix == ".md":
            warning = (
                f"Link target does not exist in {source}: [[{target}]]; "
                f"create {relative.as_posix()} in the vault or correct the link."
            )
            if warning not in vault.warnings:
                vault.warnings.append(warning)
        return None
    if path in vault.notes:
        vault.reached.append(path)
    return path


def _aliases(metadata: dict[str, object]) -> set[str]:
    aliases = metadata.get("aliases")
    values = aliases if isinstance(aliases, list) else [aliases]
    return {value.casefold() for value in values if isinstance(value, str) and value.strip()}


def _identifier(value: str) -> str:
    identifier = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return identifier if identifier[:1].isalpha() else f"item-{identifier or 'value'}"


def _unique_identifier(value: str, identifiers: set[str]) -> str:
    base = _identifier(value)
    identifier = base
    suffix = 2
    while identifier in identifiers:
        identifier = f"{base}-{suffix}"
        suffix += 1
    identifiers.add(identifier)
    return identifier


def _json_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise VaultError(f"Frontmatter value is not JSON-compatible: {value!r}")
