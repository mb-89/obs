"""Parse a Markdown vault into the neutral Document data model."""
from __future__ import annotations

import base64
import hashlib
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
from referencing import Registry, Resource
import yaml

from obs.commands import CommandError, run_command
from obs.config import (
    DEFAULT_CORE_CONFIG, DEFAULT_FIGURE_LABELS, DEFAULT_LONG_PARAGRAPHS,
    CoreConfig, CoreConfigError, load_core_config, overridden,
)
from obs.figure import FIGURE_KINDS, FIGURE_SCHEMA_PATH, FigureContentError, FigureContext
from obs.input import (
    ADAPTER_NAMESPACE,
    InputError,
    input_error,
    input_validator,
    parse_callout,
    parse_card_spec,
    parse_property_editor,
    property_editor_writes,
    schema_error,
    validate_base_definition,
    validate_command,
    declared_style,
    validate_cover_metadata,
    validate_count_query,
    validate_note_profile,
    project_config_keys,
    validate_project_config,
    validate_quantity,
)
from obs.node_ids import block_names
from obs.note import IGNORED, Note, VaultError, lines, parser, read_note
from obs import svg_links
from obs.figure_lint import figure_warnings
from obs.paragraph_lint import paragraph_warnings
from obs.quantity import document_quantity
from obs.producers import ProducerError, run_producers
from obs.sources import SourceError, css_snippets
from obs.selection import (
    Record, UnsupportedFilter, base_selects, conditions_select, member_order, note_marks,
    paragraph_marks, view_selectors,
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
    r"(?P<embed>!)?\[\[(?P<target>[^\]|#]*)(?:#(?P<heading>[^\]|]+))?"
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
    figure_labels: tuple[str, ...] = DEFAULT_FIGURE_LABELS
    """The labels before a typed figure number, which the figure lint warns about."""
    long_paragraphs: tuple[int, int] = DEFAULT_LONG_PARAGRAPHS
    """The long-paragraph lint's warningLines and lineCharacters."""
    blocks: dict[Path, set[str]] = field(default_factory=dict)
    """Each parsed note's figure block ids (input-model, Figure captions and references)."""
    block_links: list[tuple[dict[str, object], Path, Path, str]] = field(default_factory=list)
    """Each wikilink with a block heading: its attrs, its note, the note it targets and its syntax."""
    titles: dict[Path, str] = field(default_factory=dict)
    """The manifest's and each listed chapter's title, by note."""

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


PROJECT_CONFIG_OWNER = "spec/design_input/architecture.md (Project configuration)"


@dataclass(frozen=True)
class _Settings:
    """A build's core configuration and the vault's project configuration file, if it holds one."""

    given: CoreConfig | None
    """The core configuration --config names, if any."""
    effective: CoreConfig
    """The core configuration the build applies: --config or the defaults, the vault's file over it."""
    given_path: Path | None = None
    project: Path | None = None
    project_value: dict[str, object] = field(default_factory=dict)

    def declares_manifest_filename(self) -> bool:
        return self.given is not None or "manifestFilename" in self.project_value.get("input", {})

    def manifest_filename_owner(self) -> str:
        """Where the applied ``input.manifestFilename`` comes from."""
        if "manifestFilename" in self.project_value.get("input", {}):
            return str(self.project)
        return f"--config {self.given_path}" if self.given is not None else "src/obs/config.schema.json"

    def handed_over(self, vault_root: Path) -> dict[str, object]:
        """The Document's ``projectConfig``: the file's keys the core does not own, unread."""
        if self.project is None:
            return {}
        keys = project_config_keys()
        return {"projectConfig": {"path": self.project.relative_to(vault_root).as_posix(), "settings": {
            key: value for key, value in self.project_value.items() if key not in keys}}}


def _settings(vault_root: Path, configuration_path: Path | None) -> _Settings:
    """Read --config, then the vault's project configuration over it (architecture.md, Project
    configuration); the vault's file is read once per call of this."""
    try:
        given = load_core_config(configuration_path) if configuration_path is not None else None
    except CoreConfigError as error:
        raise VaultError(str(error)) from error
    base = given or DEFAULT_CORE_CONFIG
    path = vault_root / base.project_config_filename
    if not path.is_file():
        return _Settings(given, base, configuration_path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise VaultError(f"{path}: top level: cannot be read as JSON ({error}). Correct the JSON there, or "
                         f"remove the file; see {PROJECT_CONFIG_OWNER}.") from error
    try:
        validate_project_config(value, path)
    except InputError as error:
        raise VaultError(str(error)) from error
    return _Settings(given, overridden(base, value), configuration_path, path, value)


def manifest_note(source: Path, configuration_path: Path | None = None) -> Path:
    """The manifest note ``source`` names: a note as given, a vault folder its
    ``input.manifestFilename`` note (cli.md, One-call build), the vault's project configuration
    over --config."""
    if not source.is_dir():
        return source
    settings = _settings(source, configuration_path)
    filename = settings.effective.manifest_filename
    note = source / filename
    if not note.is_file():
        raise VaultError(
            f"--source {source}: the vault folder holds no manifest note {filename} (input.manifestFilename, "
            f"{settings.manifest_filename_owner()}). Add {filename} to the folder, or name the manifest note "
            f"itself with --source.")
    return note


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
    manifest_path = manifest_path.resolve()
    vault_root = manifest_path.parent
    settings = _settings(vault_root, configuration_path)
    configuration = settings.effective
    command_runner: Callable[[str], str] | None = None
    if execute_commands:
        timeout = configuration.command_timeout_seconds
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
        style = declared_style(metadata, manifest_path)
    except InputError as error:
        raise VaultError(str(error)) from error
    if settings.declares_manifest_filename() and manifest_path.name != configuration.manifest_filename:
        raise VaultError(
            f"Manifest filename does not match core configuration: {manifest_path.name}"
        )
    try:
        snippets = css_snippets(vault_root, configuration.css_snippet_folder)
    except SourceError as error:
        raise VaultError(str(error)) from error
    vault = _read_vault(manifest_path, metadata, body)
    vault.figure_labels = configuration.figure_labels
    vault.long_paragraphs = configuration.long_paragraphs
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
        if (chapter_metadata.get("obs") or {}).get("bless") == "pending":
            chapter["bless"] = {"version": bless_version(path, context.embedded, vault)}
        for child in chapter["children"]:
            parse_chapter(child)

    for chapter in chapters:
        parse_chapter(chapter)
    _metadata_links(metadata, manifest_path, vault)
    manifest_context = replace(context_of(manifest_path, metadata), first_line=body[:abstract].count("\n"))
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
    contents = {HOME: abstract_nodes, **_chapter_contents(chapters)}
    names: dict[str, set[str]] = {}
    for attrs, source_path, target, syntax in vault.block_links:
        if attrs["chapter"] is None:
            continue
        if attrs["chapter"] not in names:
            names[attrs["chapter"]] = block_names(contents[attrs["chapter"]], vault.relative(target))
        if attrs["heading"][1:] not in names[attrs["chapter"]]:
            raise VaultError(str(input_error(
                source_path, f"link {syntax}", f"names the block id {attrs['heading']}, which no block in "
                f"{vault.relative(target)} carries",
                f"Link the block id of a block there (a ^name at its end, or the ^name line after it) or add "
                "it; see capabilities/wikilinks")))
        attrs["block"] = attrs["heading"][1:]
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
        "cssSnippets": snippets,
        **({"style": style} if style is not None else {}),
        **settings.handed_over(vault_root),
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


def _shown_title(path: Path, vault: _Vault) -> str:
    """The title a note is shown by: its chapter's title, else its title as authored, else its
    file name."""
    name = vault.titles.get(path) or _note_title(path, vault)
    return name.strip() if isinstance(name, str) and name.strip() else path.stem


def _add_records(vault: _Vault, chapters: list[dict[str, object]], title: str) -> None:
    """Every record a Base view can select, of each type; see document.schema.json ($defs/record)."""
    used = set(vault.identities.values()) | {HOME}
    titles = vault.titles
    titles[vault.manifest] = title
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
        name = _shown_title(path, vault)
        for category, identifier, text in paragraph_marks(body):
            add("tag", f"{note}-{category}-{identifier}", {
                "sourcePath": source, "type": category, "label": identifier, "text": text,
                "source": name,
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


def _metadata_links(metadata: object, source_path: Path, vault: _Vault, name: str = "") -> None:
    """Follow wikilinks and embeds in frontmatter string values, named by field path as _field_nodes."""
    if isinstance(metadata, dict):
        for key, value in metadata.items():
            _metadata_links(value, source_path, vault, f"{name}.{key}" if name else str(key))
    elif isinstance(metadata, list):
        for index, value in enumerate(metadata):
            _metadata_links(value, source_path, vault, f"{name}.{index}")
    elif isinstance(metadata, str):
        for match in _SEMANTIC.finditer(metadata):
            if match["target"]:
                _link(match["target"].strip(), source_path, vault, place=f"field {name}")


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
    except UnsupportedFilter as error:
        raise VaultError(str(input_error(
            source_path, f"{place}, {error.field}", str(error),
            'Write comparisons such as status == "done", combined with and, or and not; '
            "see input-model#Bases filter grammar",
        ))) from error
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
        validate_note_profile(metadata, path, manifest=path == vault.manifest)
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
    embedded: set[Path] = field(default_factory=set)
    """The vault files the note embeds, which its bless version counts (input-model#Bless requests)."""
    first_line: int | None = 0
    """The note body's 0-based line the parsed text starts on, or None where the text is not
    the note's own (a card body), for messages that name a note line."""


def _nodes(source: str, context: _Context) -> list[dict[str, object]]:
    tokens = parser().parse(source)
    if context.first_line is None:
        return _blocks(tokens, 0, len(tokens), context)
    # The note's own text: the lints name its lines.
    note = context.vault.relative(context.source_path)
    for line, message in figure_warnings(tokens, partial(_note_line, context), context.vault.figure_labels):
        context.vault.warnings.append(f"{note}{'' if line is None else f':{line}'}: {message}")
    linked = len(context.vault.links)
    blocks = _blocks(tokens, 0, len(tokens), context)
    labels = {(attrs["target"], attrs["heading"]): (
        attrs["heading"] if not attrs["target"] else _shown_title(resolved, context.vault)
        + (f" > {attrs['heading']}" if attrs["heading"] else ""))
        for attrs, resolved in context.vault.links[linked:] if "heading" in attrs and resolved is not None}
    for line, message in paragraph_warnings(tokens, partial(_note_line, context), labels,
                                            *context.vault.long_paragraphs):
        context.vault.warnings.append(f"{note}{'' if line is None else f':{line}'}: {message}")
    return blocks


_BLOCK_ID = re.compile(r"\^([A-Za-z0-9-]+)")
"""A figure's block id line, directly after its fence; see input-model, Figure descriptor."""


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
            node = _fence_node(token, context)
            result.append(node)
            position += 1
            block = _BLOCK_ID.fullmatch(tokens[position + 1].content) if (
                node["type"] == "figures" and position + 2 < end and tokens[position].type == "paragraph_open"
            ) else None
            if block:
                blocks = context.vault.blocks.setdefault(context.source_path, set())
                if block[1] in blocks:
                    language = token.info.split()[0]
                    raise VaultError(str(input_error(
                        context.source_path, f"{language} fence {context.fences[language]}, block",
                        f"is ^{block[1]}, which an earlier figure in this note carries",
                        f"Give each figure its own block id; see {FIGURES}")))
                blocks.add(block[1])
                node["attrs"]["block"] = block[1]
                position = _closing(tokens, position) + 1
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


@cache
def _block_types() -> frozenset[str]:
    """The types that key a branch of document.schema.json ($defs/blockNode), each by its ``const`` or
    ``enum``: a node of any other type matches no branch (src/obs/discriminator.py)."""
    schema = json.loads(Path(__file__).with_name("document.schema.json").read_text(encoding="utf-8"))
    keys = [branch["properties"]["type"] for branch in schema["$defs"]["blockNode"]["anyOf"]]
    return frozenset(value for key in keys for value in key.get("enum", [key.get("const")]))


def _is_block(node: dict[str, object]) -> bool:
    """Whether ``node`` is a block node, by the schema; only a node whose type keys a branch is checked."""
    kind = node.get("type")
    return isinstance(kind, str) and kind in _block_types() and _block_node().is_valid(node)


def _paragraphs(children: list[dict[str, object]]) -> list[dict[str, object]]:
    """A paragraph's inline nodes as paragraphs with each block node between them, never inside
    one; see capabilities/markdown#Document nodes. The text around a block node keeps its
    authored characters; a paragraph left with only whitespace is dropped."""
    result: list[dict[str, object]] = []
    run: list[dict[str, object]] = []
    for child in [*children, None]:
        if child is not None and not _is_block(child):
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
        "attrs": {"kind": callout["type"], "title": _inline_text(callout["title"], context)},
        "children": _blocks(body_tokens, 0, len(body_tokens), context),
    }


def _fence_node(token: Token, context: _Context) -> dict[str, object]:
    """The node of one fenced or indented code block; see capabilities/markdown."""
    source_path, vault, capability_ids = context.source_path, context.vault, context.capability_ids
    info = token.info.strip().split() if token.type == "fence" else []
    language = info[0] if info else ""
    silent_command = info == ["cmd", "silent"]
    diagram = FIGURE_KINDS[language] if language in FIGURE_KINDS and FIGURE_KINDS[language].fence else None
    if diagram is not None and not {"figures", diagram.capability} <= capability_ids:
        diagram = None
    if language in {"base", "cards", "property-editor", "cmd", "figure"} or diagram:
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
            body_context = replace(context, capabilities=set(), fences={}, first_line=None)
            for card in specification["cards"]:
                _card_selection(card, source_path, vault)
                card_bodies.append({"type": "document", "attrs": {
                    "title": _inline_text(card["title"], body_context),
                    "labels": [_inline_text(metric["label"], body_context)
                               for metric in card.get("metrics", [])],
                }, "children": _nodes(card["body"], body_context)})
        elif language == "property-editor":
            specification = parse_property_editor(token.content, source_path, context.frontmatter, place)
        elif language == "cmd":
            try:
                validate_command(token.content)
            except InputError as error:
                raise input_error(source_path, place, "is empty", "Write the command to run or "
                                  "remove the fence; see capabilities/command-fences") from error
        elif language == "figure":
            figure = _figure(_figure_fence(token.content, context, place), context, place, token.map[0])
        elif diagram:
            figure = _figure({"version": 1, "kind": language, "content": token.content}, context, place,
                             token.map[0], plain=True)
    except (InputError, yaml.YAMLError) as error:
        raise VaultError(str(error)) from error
    fence_type = {
        "base": "bases",
        "cmd": "command-fences",
        "cards": "cards-metrics",
        "property-editor": "property-editors",
        "figure": "figures",
    }.get(language, "figures" if diagram else None)
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
    if language == "figure" or diagram:
        context.capabilities.add(fence_type)
        if FIGURE_KINDS[figure["attrs"]["kind"]].capability:
            context.capabilities.add(FIGURE_KINDS[figure["attrs"]["kind"]].capability)
        return figure
    if language == "base":
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


FIGURES = "capabilities/figures"
"""The note that owns the figure fence; see input-model, Figure input direction."""


def _figure_fence(text: str, context: _Context, place: str) -> dict[str, object]:
    """A figure fence's mapping, checked against the fence's schema."""
    try:
        fence = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise input_error(context.source_path, place, f"is not valid YAML: {error}",
                          f"Write a YAML mapping; see {FIGURES}") from error
    error = schema_error(list(input_validator("figureFence").iter_errors(fence)), context.source_path, FIGURES,
                         place=place)
    if error:
        raise error
    content = yaml.compose(text).value
    fence = _json_value(fence)
    for key, value in content:
        if key.value == "content" and isinstance(fence.get("content"), str):
            # The fence text's line, from 0, before content line 1: a block scalar's text starts below its key.
            fence["_content_line"] = value.start_mark.line + (0 if value.style in {"|", ">"} else -1)
    return fence


def _figure(fence: dict[str, object], context: _Context, place: str, opener: int,
            plain: bool = False) -> dict[str, object]:
    """The one figures node of a figure fence, or of a plain fence of a diagram kind (``plain``,
    whose whole text is the content), whatever its kind; its one child is the kind's body.
    ``opener`` is the note body line, from 0, of the fence's opening line."""
    source_path = context.source_path
    # The fence line a content line k (from 1) is on, counted from the opening line.
    content_offset = 0 if plain else 1 + fence.pop("_content_line", 0)

    def fail(field: str, problem: str, remedy: str, reference: str = FIGURES) -> InputError:
        reference = "" if "; see " in remedy else f"; see {reference}"
        return input_error(source_path, f"{place}, {field}", problem, remedy + reference)

    def located(error: FigureContentError) -> InputError:
        """A diagram's error: the note line of the content line it names, else of the fence."""
        where = place if plain else f"{place}, {error.field}"
        offset = 0
        if error.line is not None and error.field == "source":
            where += f", line {error.line}"
        elif error.line is not None:
            offset = content_offset + error.line
        note_line = _note_line(context, opener + offset)
        if note_line is not None:
            where = f"line {note_line}, {where}"
        return input_error(source_path, where, error.problem, f"{error.remedy}; see {error.reference}")

    kind = FIGURE_KINDS.get(fence["kind"])
    if kind is None:
        raise fail("kind", f"is {fence['kind']!r}, which is no figure kind",
                   f"Use one of {', '.join(sorted(FIGURE_KINDS))}")
    if ("source" in fence) == ("content" in fence):
        raise fail("source", "and content are both given" if "source" in fence else "and content are both missing",
                   "Give the figure's content inline under content or name its file in source, exactly one")
    shared = {"version", "kind", "caption", "alt", "source", "content"}
    options = {key: value for key, value in fence.items() if key not in shared}
    try:
        if "source" in fence:
            path = _figure_file(fence["source"], context, fail)
            body = kind.read(path.read_bytes(), mimetypes.guess_type(path.name)[0])
        else:
            body = kind.read(fence["content"], None)
        if kind.resolve:
            body = kind.resolve(body, FigureContext(
                "source" if "source" in fence else "content", lambda target: _figure_note(target, context),
                (lambda snippet: _file_line(snippet, path, fence["source"])) if "source" in fence
                else lambda snippet: _content_line(snippet, context, opener)))
    except FigureContentError as error:
        raise (located(error) if error.reference else fail(error.field, error.problem, error.remedy)) from error
    body |= options
    error = schema_error(list(_figure_body(fence["kind"]).iter_errors(body)), source_path, FIGURES, place=place)
    if error:
        raise error
    svg = svg_links.figure_svg(body)
    note_line = _note_line(context, opener)
    links = _figure_links(svg, context, place if note_line is None else f"line {note_line}, {place}") if svg else []
    attrs: dict[str, object] = {"kind": fence["kind"]}
    if "caption" in fence:
        captions = fence["caption"] if isinstance(fence["caption"], list) else [fence["caption"]]
        attrs["caption"] = [
            {"type": "paragraph", "attrs": {},
             "children": _inline_nodes(parser().parseInline(caption)[0], context)}
            for caption in captions
        ]
    if "alt" in fence:
        attrs["alt"] = fence["alt"]
    return {"type": "figures", "attrs": attrs,
            "children": [{"type": fence["kind"], "attrs": body, "children": links}]}


@cache
def _figure_body(kind: str) -> Draft202012Validator:
    """The validator of a figure kind's body, document.schema.json ($defs/figureBodies), compiled once."""
    schema = json.loads(Path(__file__).with_name("document.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator({**schema["$defs"]["figureBodies"][kind], "$defs": schema["$defs"]},
                                registry=_figure_registry())


@cache
def _figure_registry() -> Registry:
    return Registry().with_resource(
        FIGURE_SCHEMA_PATH.name, Resource.from_contents(json.loads(FIGURE_SCHEMA_PATH.read_text(encoding="utf-8"))))


def _figure_note(target: str, context: _Context) -> tuple[str, dict[str, object]] | None:
    """The note a figure's link names, validated and included: its vault path and frontmatter."""
    path = _link(target, context.source_path, context.vault)
    if path is None or path not in context.vault.notes:
        return None
    _validate_note(path, context.vault)
    return context.vault.relative(path), context.vault.notes[path][0]


def _content_line(snippet: str, context: _Context, opener: int) -> str:
    """Where ``snippet`` first stands in the fence that opens on body line ``opener``, such as
    "line 12" of the note; empty where it is not found or the text is not the note's own."""
    if context.first_line is None:
        return ""
    rows = read_note(context.source_path).body.splitlines()[context.first_line + opener + 1:]
    index = _first_row(snippet, rows)
    return "" if index is None else f"line {_note_line(context, opener + 1 + index)}"


def _file_line(snippet: str, path: Path, source: str) -> str:
    """Where ``snippet`` first stands in a figure's source file, such as "curve.yaml line 3"."""
    index = _first_row(snippet, path.read_text(encoding="utf-8").splitlines())
    return "" if index is None else f"{source} line {index + 1}"


def _first_row(snippet: str, rows: list[str]) -> int | None:
    start = snippet.strip().splitlines()[0][:40] if snippet.strip() else ""
    return next((index for index, row in enumerate(rows) if start and start in row), None)


def _note_line(context: _Context, body_line: int) -> int | None:
    """The note's source line of the parsed text's 0-based ``body_line``, where it is the note's own."""
    if context.first_line is None:
        return None
    lines = read_note(context.source_path).lines
    return lines[min(context.first_line + body_line, len(lines) - 1)] if lines else None


def _figure_file(source: str, context: _Context, fail: Callable[..., InputError]) -> Path:
    """The file a figure's source names: relative to its note, inside the vault."""
    path = (context.source_path.parent / source).resolve()
    if not path.is_relative_to(context.vault.root):
        raise fail("source", f"is {source!r}, outside the vault", "Keep the file inside the vault")
    if not path.is_file():
        raise fail("source", f"is {source!r}, which does not exist",
                   f"Add {source} next to the note or correct the path")
    context.embedded.add(path)
    return path


def bless_version(note: Path, embedded: set[Path], vault: _Vault) -> str:
    """A chapter's version: the SHA-256 of its note and of every vault file it embeds, each as its
    vault path, its length and its bytes, the note first, then the rest by vault path
    (input-model#Bless requests)."""
    digest = hashlib.sha256()
    for path in [note, *sorted(embedded - {note}, key=vault.relative)]:
        data = path.read_bytes()
        digest.update(b"%s\0%d\0" % (vault.relative(path).encode("utf-8"), len(data)))
        digest.update(data)
    return digest.hexdigest()


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
    """The inline nodes of one inline token; marks nest, link text carries attrs.link, a hard line
    break is a break node and a soft one a space (capabilities/markdown#Document nodes)."""
    result: list[dict[str, object]] = []
    open_nodes = [result]
    link: dict[str, str] | None = None
    children = token.children or []
    skip = 0
    for index, child in enumerate(children):
        if index < skip:
            continue
        output = open_nodes[-1]
        mark = child.type.removesuffix("_open").removesuffix("_close")
        if mark in _INLINE_MARKS and child.type.endswith("_open"):
            node = {"type": _INLINE_MARKS[mark], "attrs": {}, "children": []}
            output.append(node)
            open_nodes.append(node["children"])
        elif mark in _INLINE_MARKS:
            open_nodes.pop()
        elif child.type == "link_open" and (block := _block_href(child.attrGet("href") or "", context)):
            label, (target, heading, resolved) = _link_label(children[index + 1:]), block
            output.append(_wikilink(target, heading, label, resolved, f"[{label}]({unquote(child.attrGet('href') or '')})", context))
            skip = next((end for end in range(index + 1, len(children)) if children[end].type == "link_close"),
                        len(children)) + 1
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
        elif child.type == "hardbreak":
            output.append({"type": "break", "attrs": {}, "children": []})
        elif child.type in {"text", "softbreak"}:
            text = " " if child.type == "softbreak" else child.content
            if link:
                output.append({"type": "text", "attrs": {"link": link["id"]}, "children": [], "text": text})
            else:
                output.extend(_semantic_text_nodes(text, context))
    return result


def _inline_text(text: str, context: _Context) -> list[dict[str, object]]:
    """The inline nodes of a string the author wrote as inline Markdown: a callout title, a card
    title or a metric label (capabilities/callouts, capabilities/cards-metrics)."""
    return _inline_nodes(parser().parseInline(text)[0], context) if text else []


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
        if value.startswith(("[[", "![[")) and not target and (match["embed"] or not match["heading"]):
            nodes.append({"type": "text", "attrs": {}, "children": [], "text": value})
            position = match.end()
            continue  # A link names its own note by its heading alone ([[#Heading]], [[#^name]]).
        resolved = _link(target, source_path, vault, value,
                         f"field {context.field_path}" if context.field_path else "") if target else None
        if value.startswith("[[") and not target:
            resolved = source_path
        is_base = bool(match["embed"]) and Path(target).suffix == ".base"
        definition: object = None
        if is_base and resolved is None:
            raise VaultError(
                f"Base does not exist in {vault.relative(source_path)}: {value} matches no vault file; "
                f"create {target} in the vault or embed the vault path of an existing .base file."
            )
        if match["embed"] and resolved is not None and resolved.is_file():
            context.embedded.add(resolved)
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
            nodes.append(_wikilink(target, match["heading"] or "", match["label"] or "", resolved, value, context))
        elif "marks" in capability_ids:
            nodes.append({"type": "marks", "attrs": {"category": match["category"], "id": match["id"]}, "children": []})
            capabilities.add("marks")
        else:
            nodes.append({"type": "text", "attrs": {}, "children": [], "text": value})
        position = match.end()
    if position < len(text):
        nodes.append({"type": "text", "attrs": {}, "children": [], "text": text[position:]})
    return nodes


def _chapter_contents(chapters: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    """Each chapter's content, by chapter id, its children's included."""
    return {key: value for chapter in chapters
            for key, value in [(chapter["id"], chapter["content"]), *_chapter_contents(chapter["children"]).items()]}


def _wikilink(target: str, heading: str, label: str, resolved: Path | None, syntax: str, context: _Context,
              **written: str) -> dict[str, object]:
    """A wikilinks node to a resolved target, labelled by the link text rule
    (capabilities/wikilinks#Link text); its chapter is set once inclusion is final, and a block
    link's block once every block id is known. ``syntax`` is the link as written; ``written`` is
    the ``svg`` attribute of a link inside a figure (capabilities/wikilinks)."""
    if not label:
        note = target if resolved is None else _shown_title(resolved, context.vault)
        label = f"{note} > {heading}" if target and heading else heading or target
    attrs = {"target": target, "chapter": None, "heading": heading, "label": label, **written}
    context.vault.links.append((attrs, resolved))
    if heading.startswith("^") and resolved is not None:
        context.vault.block_links.append((attrs, context.source_path, resolved, syntax))
    _resource(context.links, context.link_ids, attrs["label"], target or f"#{heading}")
    context.capabilities.add("wikilinks")
    return {"type": "wikilinks", "attrs": attrs, "children": []}


_BLOCK_HREF = re.compile(r"(?P<target>[^#:]*)#(?P<heading>\^[^#]+)")
"""A Markdown link's href that names a block id: ``note.md#^name`` or ``#^name``; capabilities/wikilinks."""


def _block_href(href: str, context: _Context) -> tuple[str, str, Path | None] | None:
    """The target, heading and resolved note of a Markdown block link, which resolves like the
    wikilink form ``[[note#^name]]`` (capabilities/wikilinks), or None for any other link."""
    href = unquote(href.strip())
    match = _BLOCK_HREF.fullmatch(href)
    if match is None or "wikilinks" not in context.capability_ids:
        return None
    target = match["target"].strip()
    resolved = _link(target, context.source_path, context.vault, f"[]({href})") if target else context.source_path
    return target, match["heading"], resolved


def _figure_links(svg: str, context: _Context, place: str) -> list[dict[str, object]]:
    """One wikilinks node per distinct link the figure's SVG holds, resolved by the prose rule
    (_link); ``place`` names the figure in a message. See capabilities/wikilinks."""
    nodes: dict[str, dict[str, object]] = {}
    for kind, value in svg_links.links(svg):
        if kind == "href":
            target, _, heading = unquote(value.strip()).partition("#")
            found = [(value, target, heading, "")] if target else []
        else:  # As in prose, a link names its own note by its heading alone ([[#Heading]]).
            found = [(match[0], match["target"].strip(), match["heading"] or "", match["label"] or "")
                     for match in _SEMANTIC.finditer(value) if match[0].startswith("[[")
                     and (match["target"].strip() or match["heading"])]
        for written, target, heading, label in found:
            if written in nodes:
                continue
            resolved = _link(target, context.source_path, context.vault, written, place) if target else context.source_path
            if "wikilinks" in context.capability_ids:
                nodes[written] = _wikilink(target, heading, label, resolved, written, context, svg=written)
    return list(nodes.values())


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
    if path is not None:
        context.embedded.add(path)
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


def _link(target: str, source_path: Path, vault: _Vault, syntax: str = "", place: str = "") -> Path | None:
    """Resolve a link or embed target and include a reached note; warn for a missing note.

    Resolution follows input-model ("Remaining chapter content"): source-relative path,
    vault-relative path, then a bare name that matches exactly one non-hidden vault file (a
    Markdown note by its name, then by its alias). ``syntax`` is the link as written, for errors;
    ``place`` names where in the note the link is, for its messages: ``field <dotted path>`` for a
    link in a frontmatter value, the figure for a link inside a figure.
    """
    syntax = syntax or f"[[{target}]]"
    relative = Path(target)
    source = vault.relative(source_path) + (f", {place}" if place else "")
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
