from __future__ import annotations

import base64
from collections import Counter
from copy import deepcopy
import mimetypes
import os
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from functools import cache, cached_property, partial
from html import escape
from html.parser import HTMLParser
from importlib.resources import files
import json
from math import isfinite
from pathlib import Path, PurePosixPath
from textwrap import wrap
from typing import Callable, Sequence
from urllib.parse import quote, unquote, urlparse

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.dollarmath import dollarmath_plugin
from latex2mathml import exceptions as math_errors
from latex2mathml.converter import convert as mathml
from obs import selection
from obs.input import InputError, schema_error
from obs_html_interim.callouts import decorate_callouts, marker as callout_marker
from obs_html_interim.markdown import authoring_markdown, shared_authoring_markdown


NOTE_PROFILE_SCHEMA = json.loads(
    files("obs_html_interim").joinpath("note-profile.schema.json").read_text(encoding="utf-8")
)
NOTE_PROFILE_VALIDATOR = Draft202012Validator(NOTE_PROFILE_SCHEMA)
MANIFEST_ITEM = re.compile(
    r"^(?P<indent> *)(?:[-*+] )"
    r"(?:\[\[(?P<wiki_target>[^\]|#]+)(?:\|(?P<wiki_label>[^\]]+))?\]\]"
    r"|\[(?P<md_label>[^\]]+)\]\((?P<md_target>[^)#]+)(?:#[^)]*)?\))$"
)
WIKILINK = re.compile(r"\[\[(?P<target>[^\]|]+)(?:\|(?P<label>[^\]]+))?\]\]")
EMBED = re.compile(r"!\[\[(?P<target>[^\]|]+)(?:\|(?P<label>[^\]]+))?\]\]")
# A wikilink or embed whose target carries one of these suffixes is a note or register, not a file.
_NOTE_SUFFIXES = {".md", ".base"}
_FILE_SUFFIX = re.compile(r"\.[A-Za-z0-9]{1,10}$")
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"}
NOTE_LINK = re.compile(r"(?<!!)\[[^\]]+\]\([^)]+\)|\[\[[^\]]+\]\]")
MARKER = re.compile(
    r"(?<!\S)#mark/(?P<kind>[a-z_]+)/"
    r"(?P<label>[a-z0-9]+(?:_[a-z0-9]+)*)(?=\s|$)"
)
MARKER_LIKE = re.compile(r"(?<!\S)#mark/\S+")
MARKER_KINDS = frozenset({
    "open_point",
    "risk",
    "assumption",
    "issue",
    "decision",
    "warning",
    "question",
    "idea",
})


class ContentError(ValueError):
    """Raised when source content violates the supported input contract."""


@dataclass(frozen=True)
class Chapter:
    depth: int
    title: str
    slug: str
    source_path: Path
    target: str
    generated: str = ""
    # The vault that resolves the note's embedded .base files (generic-tables).
    vault_root: Path | None = field(default=None, compare=False)


@dataclass(frozen=True)
class Manifest:
    metadata: dict[str, object]
    chapters: list[Chapter]
    abstract: str
    _abstract_line_offset: int = field(default=0, repr=False, compare=False)

    @property
    def presentation(self) -> dict[str, object]:
        return document_presentation(self.metadata)


DOCUMENT_PROFILE_KEYS = ("layout", "heading", "pages", "figures", "print", "cssSnippets", "query")


def document_presentation(metadata: dict[str, object]) -> dict[str, object]:
    """Resolve the manifest's document-level obsHtml keys over the schema-owned defaults."""
    profile = metadata.get("obsHtml") or {}
    defaults = {key: deepcopy(NOTE_PROFILE_SCHEMA["properties"][key]["default"])
                for key in DOCUMENT_PROFILE_KEYS}
    resolved = {key: deepcopy(profile.get(key, defaults[key])) for key in DOCUMENT_PROFILE_KEYS}
    resolved["figures"] = defaults["figures"] | resolved["figures"]
    resolved["print"] = defaults["print"] | resolved["print"]
    return resolved


def manifest_presentation(manifest_path: Path) -> dict[str, object]:
    """Resolve the document profile from the manifest frontmatter alone."""
    metadata, _ = _split_frontmatter(manifest_path.read_text(encoding="utf-8"), manifest_path)
    return document_presentation(metadata)


CSS_CLASS = re.compile(r"-?[_A-Za-z][_A-Za-z0-9-]*")


def note_css_classes(frontmatter: dict[str, object], source_path: Path) -> list[str]:
    """Return the note's Obsidian ``cssclasses``: one class name or a list of them."""
    value = frontmatter.get("cssclasses", [])
    classes = [value] if isinstance(value, str) else value
    if not isinstance(classes, list) or not all(
            isinstance(name, str) and CSS_CLASS.fullmatch(name) for name in classes):
        raise ContentError(
            f"cssclasses must be one CSS class name or a list of them in {source_path}: {value!r}"
        )
    return list(dict.fromkeys(classes))


def css_snippets(vault_root: Path, folder: str, names: Sequence[str]) -> list[tuple[str, str]]:
    """Read the manifest's listed CSS snippets, in order, from the configured vault folder."""
    snippets = []
    for name in names:
        relative = f"{folder}/{name}.css"
        path = vault_root / relative
        if not path.is_file() or not path.resolve().is_relative_to(vault_root.resolve()):
            raise ContentError(f"Manifest obsHtml.cssSnippets lists {name!r}, but {relative} is not a file.")
        css = path.read_text(encoding="utf-8")
        if re.search(r"</style", css, re.IGNORECASE):
            raise ContentError(f"CSS snippet {relative} must not contain '</style'.")
        snippets.append((name, css))
    return snippets


@dataclass(frozen=True)
class Mark:
    kind: str
    label: str
    text: str
    anchor: str


@dataclass(frozen=True)
class BaseTable:
    key: str
    definition: dict[str, object]


@dataclass(frozen=True)
class _NoteSource:
    frontmatter: dict[str, object]
    body: str
    line_offset: int

    @cached_property
    def tokens(self) -> tuple[Token, ...]:
        return tuple(shared_authoring_markdown().parse(self.body))

    @cached_property
    def headings(self) -> frozenset[str]:
        return frozenset(heading for _, heading in _heading_ids(self.tokens))


@dataclass(frozen=True)
class ChapterContent:
    frontmatter: dict[str, object]
    body: str
    marks: tuple[Mark, ...]
    tables: tuple[BaseTable, ...]
    source_notes: tuple[str, ...] = ()
    editable_properties: dict[str, object] = field(default_factory=dict)
    _body_tokens: tuple[Token, ...] | None = field(default=None, repr=False, compare=False)
    _body_line_offset: int | None = field(default=None, repr=False, compare=False)
    _source: _NoteSource | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class FigureNumber:
    """A figure fence's display number and its optional Obsidian block identity."""
    label: str | None
    block: str | None
    anchor: str | None
    number: str | None = None


FIGURE_BLOCK_ID = re.compile(r"\^([A-Za-z0-9-]+)")


def _figure_fences(tokens: Sequence[Token]):
    """Yield each figure fence index with the Obsidian block id on the following line."""
    for index, token in enumerate(tokens):
        info = token.info.strip().split(maxsplit=1) if token.type == "fence" else []
        if not info or info[0] != "figure":
            continue
        block = None
        if (index + 3 < len(tokens) and tokens[index + 1].type == "paragraph_open"
                and tokens[index + 2].type == "inline"
                and (match := FIGURE_BLOCK_ID.fullmatch(tokens[index + 2].content.strip()))):
            block = match[1]
        yield index, block


def _figure_captioned(text: str) -> bool:
    try:
        spec = yaml.safe_load(text)
    except yaml.YAMLError:
        return False
    return isinstance(spec, dict) and bool(spec.get("caption"))


def index_figures(
    notes: Sequence[Chapter], numbered: Sequence[Chapter], sources_by_path: dict[Path, "_NoteSource"],
    settings: dict[str, str],
) -> dict[Path, tuple[tuple[FigureNumber, ...], dict[str, FigureNumber]]]:
    """Number captioned figure fences in contents order; other notes keep block anchors only."""
    ordinals: dict[Path, int] = {}
    ordinal = 0
    for chapter in numbered:
        if chapter.generated == "home":
            continue
        if chapter.depth == 0:
            ordinal += 1
        ordinals[chapter.source_path] = ordinal
    numbered_paths = {chapter.source_path for chapter in numbered}
    counters: Counter[int | None] = Counter()
    ordered = [*numbered, *(note for note in notes if note.source_path not in numbered_paths)]
    index: dict[Path, tuple[tuple[FigureNumber, ...], dict[str, FigureNumber]]] = {}
    for note in ordered:
        source = sources_by_path.get(note.source_path)
        if note.source_path in index or source is None:
            continue
        tokens = source.tokens
        entries: list[FigureNumber] = []
        blocks: dict[str, FigureNumber] = {}
        for position, block in _figure_fences(tokens):
            number = None
            if (settings["numbering"] != "none" and note.source_path in numbered_paths
                    and _figure_captioned(tokens[position].content)):
                key = ordinals.get(note.source_path) if settings["numbering"] == "chapter" else None
                counters[key] += 1
                number = f"{key}.{counters[key]}" if key is not None else str(counters[key])
            entry = FigureNumber(
                f"{settings['label']} {number}" if number else None,
                block, f"{note.slug}--block-{block}" if block else None, number,
            )
            if block is not None:
                if block in blocks:
                    raise ContentError(f"Duplicate block id ^{block} in {note.source_path}")
                blocks[block] = entry
            entries.append(entry)
        index[note.source_path] = (tuple(entries), blocks)
    return index


@dataclass(frozen=True)
class NoteReferenceIndex:
    aliases: dict[str, tuple[Chapter, ...]]
    metadata_by_path: dict[Path, dict[str, object]]
    sources_by_path: dict[Path, _NoteSource] = field(default_factory=dict)
    documents_by_path: dict[Path, ChapterContent] = field(default_factory=dict)
    asset_bytes_by_path: dict[Path, bytes] = field(default_factory=dict)
    # The --embed-attachments build decision; only files marked with ![...] embed, and only then.
    embed_attachments: bool = False
    # Build-scoped memoization; the vault and note list do not change during one render.
    markdown_by_key: dict[tuple[object, ...], tuple[list[Chapter], MarkdownIt]] = field(
        default_factory=dict,
    )
    resolved_paths: dict[Path, Path] = field(default_factory=dict)
    # Vault files by case-folded name, filled on the first wikilink that needs a name lookup.
    files_by_name: dict[str, list[Path]] = field(default_factory=dict)
    inline_html_by_key: dict[tuple[str, bool], str] = field(default_factory=dict)
    # Mark backlink discovery parses linked frontmatter strings that rendering parses again.
    inline_tokens_by_key: dict[tuple[MarkdownIt, str], tuple[list[Token], dict[str, object]]] = field(
        default_factory=dict,
    )
    chapter_lookups: dict[int, tuple[list[Chapter], int, dict[Path, Chapter], dict[str, list[Chapter]]]] = field(
        default_factory=dict,
    )
    figures: dict[Path, tuple[tuple[FigureNumber, ...], dict[str, FigureNumber]]] = field(
        default_factory=dict,
    )
    # The manifest's obsHtml.figures decision and how prose names figures (cfg.json input).
    figure_presentation: dict[str, str] = field(default_factory=dict)
    figure_references: dict[str, list[str]] = field(default_factory=dict)


@cache
def _packaged_figure_references() -> dict[str, list[str]]:
    return json.loads(
        files("obs_html_interim").joinpath("cfg.json").read_text(encoding="utf-8")
    )["input"]["figureReferences"]


def collect_notes(
    manifest_path: Path, chapters: list[Chapter], home: Chapter, home_document: ChapterContent,
    manifest_metadata: dict[str, object],
    embed_pdfs: bool = True,
    embed_attachments: bool = False,
    *,
    figure_references: dict[str, list[str]] | None = None,
) -> tuple[list[Chapter], dict[Path, ChapterContent], NoteReferenceIndex]:
    vault_root = manifest_path.resolve().parent
    candidates = [home, *chapters]
    seen = {chapter.source_path for chapter in chapters}
    slugs = {"home", *(chapter.slug for chapter in chapters)}
    metadata_by_path: dict[Path, dict[str, object]] = {home.source_path: home_document.frontmatter}
    sources_by_path = {
        home.source_path: home_document._source or _NoteSource(
            home_document.frontmatter, home_document.body, home_document._body_line_offset or 0,
        ),
    }
    documents = {home.source_path: home_document}
    resolved_manifest = manifest_path.resolve()
    for chapter in chapters:
        document = read_chapter_content(chapter)
        metadata_by_path[chapter.source_path] = document.frontmatter
        sources_by_path[chapter.source_path] = document._source
        documents[chapter.source_path] = document
    for path in sorted(vault_root.rglob("*.md"), key=lambda path: path.as_posix().casefold()):
        relative = path.relative_to(vault_root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        source_path = path.resolve()
        if not source_path.is_relative_to(vault_root):
            raise ContentError(f"Note path escapes the vault: {relative}")
        if source_path == resolved_manifest or source_path in seen:
            continue
        seen.add(source_path)
        source = _note_source(source_path.read_text(encoding="utf-8-sig"), source_path)
        metadata, body = source.frontmatter, source.body
        metadata_by_path[source_path] = metadata
        sources_by_path[source_path] = source
        heading = next((line[2:].strip() for line in body.splitlines() if line.startswith("# ")), None)
        title = metadata.get("title", metadata.get("term", heading or path.stem.replace("-", " ").title()))
        if title == "":
            title = path.stem.replace("-", " ").title()
        if not isinstance(title, str) or not title.strip():
            raise ContentError(f"Note title must be a non-empty string: {relative}")
        candidates.append(Chapter(
            0, title.strip(), _unique_slug(relative.with_suffix("").as_posix(), slugs),
            source_path, relative.as_posix(), vault_root=vault_root,
        ))
    alias_targets: dict[str, list[Chapter]] = {}
    for candidate in candidates:
        if candidate.generated:
            continue
        metadata = metadata_by_path[candidate.source_path]
        seen_aliases: set[str] = set()
        for alias in _note_aliases(metadata, candidate.source_path):
            alias_key = alias.casefold()
            if alias_key not in seen_aliases:
                alias_targets.setdefault(alias_key, []).append(candidate)
                seen_aliases.add(alias_key)
    figure_presentation = document_presentation(manifest_metadata)["figures"]
    reference_index = NoteReferenceIndex(
        {alias: tuple(matches) for alias, matches in alias_targets.items()},
        metadata_by_path,
        sources_by_path,
        documents,
        embed_attachments=embed_attachments,
        figure_presentation=figure_presentation,
        figure_references=figure_references or _packaged_figure_references(),
    )
    reference_index.figures.update(index_figures(
        candidates, [home, *chapters], sources_by_path, figure_presentation,
    ))
    included = {home.source_path, *(chapter.source_path for chapter in chapters)}
    by_slug = {note.slug: note for note in candidates}
    candidate_paths = {candidate.source_path for candidate in candidates}
    candidate_by_path = {candidate.source_path: candidate for candidate in candidates}
    canonical_notes = manifest_metadata.get("canonicalNotes", [])
    if not isinstance(canonical_notes, list) or any(
        not isinstance(identity, str) for identity in canonical_notes
    ):
        raise ContentError("Manifest canonicalNotes must be a list of exact note identities")
    if len(canonical_notes) != len(set(canonical_notes)):
        raise ContentError("Manifest canonicalNotes must not contain duplicates")

    def resolve_canonical_note(identity: str, label: str) -> Chapter:
        parts = identity.split("/")
        if (not identity or identity.endswith(".md") or "\\" in identity or
                ":" in identity or any(part in {"", ".", ".."} for part in parts)):
            raise ContentError(f"Invalid {label}: {identity}")
        source_path = vault_root.joinpath(*PurePosixPath(f"{identity}.md").parts).resolve()
        source = candidate_by_path.get(source_path)
        if not source_path.is_relative_to(vault_root) or source is None:
            raise ContentError(f"{label} does not resolve: {identity}")
        return source
    pending = [home, *chapters]
    toc_paths = {chapter.source_path for chapter in chapters}
    Projection = tuple[str, dict[str, object], dict[str, object] | None, str]
    projections_by_path: dict[Path, list[Projection]] = {}

    def query_projections(candidate: Chapter) -> list[Projection]:
        """Projected rows as (record type, own fields, owner frontmatter or None, path); see generic-tables."""
        if candidate.source_path in projections_by_path:
            return projections_by_path[candidate.source_path]
        metadata = metadata_by_path[candidate.source_path]
        path = candidate.source_path.relative_to(vault_root).as_posix()
        note_fields = {
            "chapter": candidate.title, "title": candidate.title, "depth": str(candidate.depth),
            "slug": candidate.slug, "sourcePath": path,
        }
        projections: list[Projection] = [("note", note_fields, metadata, path)]
        if candidate.source_path in toc_paths:
            projections.append(("chapter", note_fields, metadata, path))
        if metadata.get("kind") == "glossary":
            projections.append(("glossary", {
                "sourcePath": path, "term": metadata.get("term"),
                "definition": metadata.get("definition"), "aliases": metadata.get("aliases") or [],
            }, metadata, path))
        for token in sources_by_path[candidate.source_path].tokens:
            if token.type != "inline":
                continue
            for child in token.children or []:
                if child.type != "text":
                    continue
                markers = list(MARKER.finditer(child.content))
                for marker in markers:
                    projections.append(("tag", {
                        "sourcePath": path, "type": marker["kind"],
                        "label": marker["label"],
                        "text": _remove_markers(token.content, [item.group(0) for item in markers]),
                        "source": candidate.title,
                    }, None, path))
        projections_by_path[candidate.source_path] = projections
        return projections

    def projected_value(projection: Projection, field: str):
        _, own, metadata, path = projection
        if field in own:
            return own[field]
        return None if metadata is None else base_note_value(metadata, path, field)

    while pending:
        note = pending.pop(0)
        document = documents.get(note.source_path)
        if document is None:
            document = _chapter_content(note, sources_by_path[note.source_path])
            documents[note.source_path] = document
        if note.source_path in toc_paths and document.frontmatter.get("obsHtml", {}).get("document") is False:
            raise ContentError(f"A record-only note cannot be an authored manifest chapter: {note.source_path}")
        for table in document.tables:
            for field, expansion in table.definition.get("obsHtml", {}).get("expandProperties", {}).items():
                source = resolve_canonical_note(expansion["sourceNote"], "Column source note")
                value = metadata_by_path[source.source_path]
                for part in expansion["property"].split("."):
                    value = value.get(part) if isinstance(value, dict) else None
                if not isinstance(value, list):
                    raise ContentError(f"Column source must be a list: {expansion['property']}")
                orders = [view["order"] for view in table.definition["views"]]
                if not any(field in order for order in orders):
                    raise ContentError(f"Expanded property is not ordered: {field}")
                keys = set()
                for item in value:
                    key = item
                    for part in expansion["keyProperty"].split("."):
                        key = key.get(part) if isinstance(key, dict) else None
                    if not isinstance(key, str) or not key.strip() or "." in key or key in keys:
                        raise ContentError(f"Invalid or duplicate column key: {expansion['property']}")
                    keys.add(key)
                    column = f"{field}.{key}"
                    if any(column in order for order in orders) or column in table.definition.get("properties", {}):
                        raise ContentError(f"Expanded column collides with authored property: {column}")
                if not value and [field] in orders:
                    raise ContentError(f"Column expansion is empty: {field}")
            members = table.definition.get("obsHtml", {}).get("members", [])
            member_sources: set[Path] = set()
            for member in members:
                parts = member["path"].split("/")
                if any(part in {"", ".", ".."} for part in parts):
                    raise ContentError(
                        f"Invalid obsHtml.members path: {member['path']} in {note.source_path}"
                    )
                relative = PurePosixPath(member["path"])
                resolved = vault_root.joinpath(*relative.parts).resolve()
                if not resolved.is_relative_to(vault_root) or not resolved.is_file() \
                        or resolved not in candidate_paths:
                    raise ContentError(
                        f"obsHtml.members path does not resolve to a Markdown note inside the vault: "
                        f"{member['path']} in {note.source_path}"
                    )
                if resolved in member_sources:
                    raise ContentError(
                        f"Duplicate obsHtml.members path: {member['path']} in {note.source_path}"
                    )
                member_sources.add(resolved)
        references: set[str] = set()
        owned_query = document.frontmatter.get("query")
        if isinstance(owned_query, dict) and isinstance(owned_query.get("where"), list) and "from" in owned_query:
            references.add(resolve_canonical_note(owned_query["from"], "Count query owner").slug)
        if note.generated == "home":
            references.update(
                resolve_canonical_note(identity, "Canonical note dependency").slug
                for identity in canonical_notes
            )
        references.update(
            resolve_canonical_note(identity, "Dynamic Sankey source note").slug
            for identity in document.source_notes
        )
        markdown = _shared_markdown(
            note, candidates, vault_root, embed_pdfs=embed_pdfs, reference_index=reference_index,
        )
        texts = [document.body, *_metadata_strings(
            manifest_metadata if note.generated == "home" else document.frontmatter
        )]
        for index, text in enumerate(texts):
            # Only links, fences and column delimiters matter here; see _may_link.
            if index and not (any(character in text for character in "`~") or "|||" in text
                              or _may_link(text)):
                continue
            tokens = markdown.parse(text)
            if index == 0:
                documents[note.source_path] = replace(document, _body_tokens=tuple(tokens))
            for token in tokens:
                if token.type == "fence" and token.info.strip() == "cards":
                    from obs_html_interim.cards import parse_card_spec
                    for card in parse_card_spec(token.content, note.source_path)["cards"]:
                        texts.append(card["body"])
                        for metric in card.get("metrics", []):
                            if "secondary" in metric:
                                texts.append(f'[[{metric["secondary"]}]]')
                            if "from" in metric:
                                source = resolve_canonical_note(metric["from"], "Count query owner")
                                metadata = metadata_by_path[source.source_path]
                                if "query" not in metadata:
                                    raise ContentError(f"Count query reference requires a query owner: {metric['from']}")
                                _validate_query_references(metadata["query"], source, candidates,
                                                           vault_root, reference_index, set())
                                references.add(source.slug)
                for child in token.children or []:
                    if child.type == "link_open":
                        href = child.attrGet("href") or ""
                        if href.startswith("#"):
                            slug = href[1:].split("/", 1)[0]
                            if slug in by_slug:
                                references.add(slug)
        # A view selects canonical notes, or one projection kind with its own or the base's
        # obsHtml.records (generic-tables). A note is included when any one view selects it.
        for definition in (table.definition for table in document.tables):
            base_records = definition.get("obsHtml", {}).get("records")
            base = [compile_base_filter(definition["filters"])] if definition.get("filters") is not None else []
            selections = [(
                view.get("obsHtml", {}).get("records", base_records),
                base + ([compile_base_filter(view["filters"])] if view.get("filters") is not None else []),
            ) for view in definition["views"]]
            for candidate in candidates:
                if candidate.generated:
                    continue
                metadata = metadata_by_path[candidate.source_path]
                note_path = candidate.source_path.relative_to(vault_root).as_posix()
                if any(
                    all(predicate(lambda field: base_note_value(metadata, note_path, field))
                        for predicate in predicates)
                    if record_type is None else any(
                        projection[0] == record_type
                        and all(predicate(partial(projected_value, projection)) for predicate in predicates)
                        for projection in query_projections(candidate))
                    for record_type, predicates in selections
                ):
                    references.add(candidate.slug)
        for slug in sorted(references):
            linked = by_slug[slug]
            if linked.source_path not in included:
                included.add(linked.source_path)
                pending.append(linked)
    return [note for note in candidates if note.source_path in included], documents, reference_index


def _metadata_strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _metadata_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _metadata_strings(item)


def _base_property(field: str) -> None:
    if re.match(r'^note(?:\.file\.|\["file\.)', field) or field.startswith(("formula.", "this.")) or (
        field.startswith("file.") and
        field not in {"file.name", "file.path", "file.folder", "file.ext"}
    ):
        raise ContentError(f"Unsupported Bases property: {field}")


def _base_record_value(record: dict[str, object], field: str):
    """Resolve a frontmatter property by the core's rules (capabilities/bases#Comparisons)."""
    return selection.note_value(record, "", field)


def base_note_value(frontmatter: dict[str, object], path: str, field: str):
    """Resolve a Bases property of a note; the core's evaluator owns it (obs.selection)."""
    return selection.note_value(frontmatter, path, field)


@cache
def _base_schema() -> dict[str, object]:
    return json.loads(files("obs_html_interim").joinpath("base.schema.json").read_text(encoding="utf-8"))


def compile_base_filter(filters: object) -> selection.BaseFilter:
    """Compile a Bases filter with the core's evaluator (obs.selection), raising ContentError.

    Only the recordType remedy is the adapter's own: it names this adapter's projections.
    """
    try:
        return selection.compile_base_filter(filters)
    except InputError as error:
        kinds = " | ".join(_base_schema()["properties"]["obsHtml"]["properties"]["records"]["enum"])
        raise ContentError(str(error).replace(
            "select rows with obs.records", f"select projected rows with obsHtml: {{records: {kinds}}}",
        )) from error


def _compile_base_filter_at(filters: object, location: str) -> selection.BaseFilter:
    try:
        return compile_base_filter(filters)
    except ContentError as error:
        raise ContentError(f"{error} ({location})") from error


class _LocalReferenceFinder(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name not in {"href", "src"} or not value or value.startswith("#"):
                continue
            parsed = urlparse(value)
            if not parsed.scheme and not parsed.netloc:
                self.references.append(value)


def parse_manifest(manifest_path: Path) -> list[Chapter]:
    return read_manifest(manifest_path).chapters


def read_manifest(manifest_path: Path) -> Manifest:
    manifest_path = manifest_path.resolve()
    vault_root = manifest_path.parent
    source = manifest_path.read_text(encoding="utf-8-sig")
    metadata, body = _split_frontmatter(source, manifest_path)
    title = metadata.get("title")
    if "title" in metadata and (
        not isinstance(title, str) or (title != "" and not title.strip())
    ):
        raise ContentError("Manifest title must be a string, either empty or non-whitespace.")
    if "subtitle" in metadata and (
        not isinstance(metadata["subtitle"], str) or not metadata["subtitle"].strip()
    ):
        raise ContentError("Manifest subtitle must be a non-empty Markdown string.")
    _validate_document_metadata(metadata)
    if "summaries" in metadata:
        raise ContentError(
            "Manifest summaries were removed. Count records with a cards metric "
            "(where/distinct/denominator, optional link with ?tableFilter=) or a quantity note "
            "with query: {where, from?, distinct?} referenced from the abstract."
        )
    tokens = shared_authoring_markdown().parse(body)
    if not tokens:
        raise ContentError(f"Manifest is empty: {manifest_path}")
    if tokens[0].type == "ordered_list_open":
        raise ContentError("Manifest TOC must be a bulleted list; numeric markers are not permitted.")
    body_lines = body.splitlines(keepends=True)
    if tokens[0].type == "bullet_list_open":
        start, end = tokens[0].map
    else:
        # Without a leading TOC the document has no chapters and its Markdown is all abstract.
        start = end = 0
    lines = "".join(body_lines[start:end]).splitlines()
    abstract = "".join(body_lines[end:])
    abstract_offset = source.count("\n", 0, source.find(abstract)) if abstract in source else 0
    presentation = document_presentation(metadata)
    pages = [entry["page"] for entry in presentation["pages"]]
    if len(pages) != len(set(pages)):
        raise ContentError("Manifest obsHtml.pages must declare each page kind at most once.")
    if presentation["heading"] == "compact" and ("cover" in pages or not pages):
        raise ContentError(
            "Manifest obsHtml.heading compact opens the first front page: obsHtml.pages must declare "
            "at least one page and no cover."
        )
    if abstract.strip() and "abstract" not in pages:
        raise ContentError(
            "Manifest obsHtml.pages must place the abstract page because the manifest has abstract Markdown."
        )
    chapters: list[Chapter] = []
    seen_paths: set[Path] = set()
    seen_slugs: set[str] = {"home"}
    previous_depth = 0

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        match = MANIFEST_ITEM.fullmatch(line)
        if not match:
            raise ContentError(
                f"Manifest line {line_number} must be one bulleted item containing exactly "
                "one local Markdown link."
            )

        indent = len(match["indent"])
        if indent % 2:
            raise ContentError(f"Manifest line {line_number} must use two-space indentation.")
        depth = indent // 2
        if not chapters and depth != 0:
            raise ContentError("The first manifest item must be a top-level chapter.")
        if depth > previous_depth + 1:
            raise ContentError(f"Manifest line {line_number} skips a nesting level.")
        previous_depth = depth

        target = (match["wiki_target"] or match["md_target"]).strip()
        label = match["wiki_label"] or match["md_label"]
        relative_path = Path(target)
        if relative_path.is_absolute():
            raise ContentError(f"Manifest line {line_number} uses an absolute path.")
        if not relative_path.suffix:
            relative_path = relative_path.with_suffix(".md")
        if relative_path.suffix.lower() != ".md":
            raise ContentError(f"Manifest line {line_number} must link to a Markdown note.")

        source_path = (vault_root / relative_path).resolve()
        if not source_path.is_relative_to(vault_root):
            raise ContentError(f"Manifest line {line_number} escapes the vault.")
        if source_path == manifest_path:
            raise ContentError("The manifest cannot include itself as an authored chapter.")
        if not source_path.is_file():
            raise ContentError(f"Manifest target does not exist: {target}")
        if source_path in seen_paths:
            raise ContentError(f"Manifest target is duplicated: {target}")
        seen_paths.add(source_path)

        title = label.strip() if label else relative_path.stem.replace("-", " ").title()
        slug = _unique_slug(relative_path.with_suffix("").as_posix(), seen_slugs)
        chapters.append(Chapter(depth, title, slug, source_path, target, vault_root=vault_root))

    return Manifest(metadata, chapters, abstract, abstract_offset)


COVER_TEXT_FIELDS = ("document type", "organization", "template", "document number",
                     "copyright", "confidentiality", "legal entity")
COVER_PEOPLE_FIELDS = ("authors", "reviewers", "approvers")


def _validate_document_metadata(metadata: dict[str, object]) -> None:
    def text(value: object) -> bool:
        return isinstance(value, str) and bool(value.strip())

    for field in (*COVER_TEXT_FIELDS, *COVER_PEOPLE_FIELDS, "history", "product"):
        if field in metadata and (metadata[field] is None or metadata[field] == ""
                                  or metadata[field] == [] or metadata[field] == {}
                                  or isinstance(metadata[field], str) and not metadata[field].strip()):
            del metadata[field]
    for field in COVER_TEXT_FIELDS:
        if field in metadata and not text(metadata[field]):
            raise ContentError(f"Manifest {field} must be a non-empty string.")
    for field in COVER_PEOPLE_FIELDS:
        if field in metadata:
            value = metadata[field]
            if not (text(value) or isinstance(value, list) and value and all(text(v) for v in value)):
                raise ContentError(f"Manifest {field} must be a non-empty string or list of strings.")
    if "product" in metadata:
        product = metadata["product"]
        if isinstance(product, dict):
            product = {key: value for key, value in product.items()
                       if value is not None and value != "" and not (
                           isinstance(value, str) and not value.strip())}
            if not product:
                del metadata["product"]
            else:
                metadata["product"] = product
        if "product" in metadata and (not isinstance(product, dict) or "name" not in product
                or set(product) - {"name", "version"} or not all(text(v) for v in product.values())):
            raise ContentError("Manifest product requires a name and optional version, both non-empty strings.")
    history = metadata.get("history", [])
    if not isinstance(history, list):
        raise ContentError("Manifest history must be a list.")
    versions: set[str] = set()
    for index, entry in enumerate(history):
        if (not isinstance(entry, dict) or not {"version", "author", "change"} <= set(entry)
                or set(entry) - {"version", "author", "change", "date"}
                or not all(text(entry[key]) for key in ("version", "author", "change"))):
            raise ContentError("Each history entry requires string version, author and change fields; date is optional.")
        version = entry["version"]
        if version in versions:
            raise ContentError(f"Duplicate history version: {version}")
        versions.add(version)
        if version.endswith("*") and index != len(history) - 1:
            raise ContentError("A working history version ending in * must be last.")
        if "date" in entry:
            value = entry["date"]
            if value is None or value == "":
                del entry["date"]
            elif isinstance(value, date) and not isinstance(value, datetime):
                entry["date"] = value.isoformat()
            elif isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                try:
                    date.fromisoformat(value)
                except ValueError as error:
                    raise ContentError(f"Invalid history date: {value}") from error
            else:
                raise ContentError("History dates must use YYYY-MM-DD or be omitted.")


def query_profile(
    profile: dict[str, object] | str, home: Chapter, notes: list[Chapter], vault_root: Path,
    documents: dict[Path, ChapterContent], reference_index: NoteReferenceIndex | None = None,
) -> dict[str, object]:
    """The manifest's global query profile, inline or declared by one linked note (input-model)."""
    if isinstance(profile, dict):
        return profile
    match = MANIFEST_ITEM.fullmatch(f"- {profile}")
    if not match:
        raise ContentError("Manifest obsHtml.query must be a query profile or one internal note link.")
    destination = _note_reference(
        match["wiki_target"] or match["md_target"], home, notes, vault_root, reference_index,
    )
    note = next(note for note in notes if f"#{note.slug}" == destination)
    declared = (documents[note.source_path].frontmatter.get("obsHtml") or {}).get("query")
    if not isinstance(declared, dict):
        raise ContentError(f"Query profile note must declare obsHtml.query as a mapping: {profile}")
    return declared


def render_chapter(
    chapter: Chapter,
    chapters: list[Chapter],
    vault_root: Path,
    command_runner: Callable[[str], str] | None = None,
    document: ChapterContent | None = None,
    bordered_tags: Sequence[str] = (),
    embed_pdfs: bool = True,
    include_plot_fallback: bool = True,
    reference_index: NoteReferenceIndex | None = None,
) -> str:
    """Render one note."""
    document = document or read_chapter_content(chapter)
    markdown = _markdown(
        chapter, chapters, vault_root, embed_pdfs=embed_pdfs, reference_index=reference_index,
    )
    default_fence = markdown.renderer.rules["fence"]
    default_paragraph_open = markdown.renderer.renderToken
    default_paragraph_close = markdown.renderer.renderToken
    table_index = 0
    figure_index = 0
    figure_entries = (
        reference_index.figures.get(chapter.source_path, ((), {}))[0]
        if reference_index is not None else ()
    )

    def render_base_table_placeholder() -> str:
        nonlocal table_index
        if table_index >= len(document.tables):
            raise ContentError(f"Base table has no canonical definition in {chapter.source_path}")
        table = document.tables[table_index]
        table_index += 1
        return (
            f'<div class="data-table-placeholder" data-base-table="{escape(table.key)}">'
            '</div>\n'
        )

    def render_card_body(body: str) -> str:
        card_markdown = _markdown(
            chapter, chapters, vault_root, embed_pdfs=embed_pdfs, reference_index=reference_index,
        )
        default_card_fence = card_markdown.renderer.rules["fence"]

        def render_card_fence(tokens, index, options, env) -> str:
            info = tokens[index].info.strip().split(maxsplit=1)
            if info and info[0] == "base":
                return render_base_table_placeholder()
            return default_card_fence(tokens, index, options, env)

        card_markdown.renderer.rules["fence"] = render_card_fence
        card_markdown.renderer.rules["base_embed"] = lambda *_: render_base_table_placeholder()
        return card_markdown.render(body)

    def render_fence(tokens, index, options, env) -> str:
        token = tokens[index]
        info = token.info.strip().split(maxsplit=1)
        if info and info[0] == "property-editor":
            from obs_html_interim.properties import render_property_editor
            return render_property_editor(token.content, chapter, document.editable_properties)
        if info and info[0] == "cards":
            from obs_html_interim.cards import render_cards
            def source_metadata(identity):
                path = vault_root.joinpath(*PurePosixPath(identity + ".md").parts).resolve()
                if not path.is_relative_to(vault_root) or reference_index is None \
                        or path not in reference_index.metadata_by_path:
                    raise ContentError(f"Cards source note does not resolve: {identity}")
                return reference_index.metadata_by_path[path]
            return render_cards(token.content, render_card_body, chapter.source_path, source_metadata)
        if info and info[0] == "figure":
            from obs_html_interim.figures import FigureError, render_figure
            nonlocal figure_index
            entry = figure_entries[figure_index] if figure_index < len(figure_entries) else None
            figure_index += 1
            try:
                return render_figure(
                    token.content, chapter.source_path, vault_root,
                    render_caption=lambda text: markdown.renderInline(text),
                    include_plot_fallback=include_plot_fallback,
                    number=entry.label if entry else None,
                    anchor=entry.anchor if entry else None,
                )
            except FigureError as error:
                line = token.map[0] + 1 if token.map else "?"
                raise ContentError(f"Figure in {chapter.source_path}:{line}: {error}") from error
        if info and info[0] == "base":
            return render_base_table_placeholder()
        if not info or info[0] != "cmd":
            return default_fence(tokens, index, options, env)
        if info == ["cmd", "silent"]:
            return ""
        if command_runner is None:
            raise ContentError("A cmd fence requires explicit command execution authorization.")
        output = command_runner(token.content.strip())
        return f'<pre class="command-output"><code>{escape(output)}</code></pre>\n'

    markdown.renderer.rules["fence"] = render_fence
    markdown.renderer.rules["base_embed"] = lambda *_: render_base_table_placeholder()
    def render_paragraph_open(tokens, index, options, env) -> str:
        if tokens[index].meta.get("artifact_figure"):
            return '<figure class="artifact-figure" data-artifact-figure>\n'
        return default_paragraph_open(tokens, index, options, env)

    def render_paragraph_close(tokens, index, options, env) -> str:
        if tokens[index].meta.get("artifact_figure"):
            return "</figure>\n"
        return default_paragraph_close(tokens, index, options, env)

    markdown.renderer.rules["paragraph_open"] = render_paragraph_open
    markdown.renderer.rules["paragraph_close"] = render_paragraph_close
    # Decorations and renderer rules may mutate nested tokens; keep the collected body pristine.
    tokens = (
        deepcopy(list(document._body_tokens)) if document._body_tokens is not None
        else markdown.parse(document.body)
    )
    decorate_callouts(tokens)
    _assign_heading_ids(tokens, chapter.slug)
    for position, block in _figure_fences(tokens):
        if block is not None:
            # The Obsidian block id line identifies the figure; it is not visible prose.
            tokens[position + 1].hidden = tokens[position + 3].hidden = True
            tokens[position + 2].children = []
            tokens[position + 2].content = ""
    for index, token in enumerate(tokens):
        if token.type != "inline" or index == 0 or tokens[index - 1].type != "paragraph_open":
            continue
        children = token.children or []
        if len(children) == 1 and children[0].type == "image":
            tokens[index - 1].meta["artifact_figure"] = True
            if index + 1 < len(tokens) and tokens[index + 1].type == "paragraph_close":
                tokens[index + 1].meta["artifact_figure"] = True
            continue
        if sum(child.type == "image" for child in children) >= 2 and all(
            child.type == "image" or (
                child.type == "text" and not any(character.isalnum() for character in child.content)
            )
            for child in children
        ):
            tokens[index - 1].attrSet("class", "media-strip")
    _decorate_markers(tokens, chapter.slug, bordered_tags)
    for index, token, line, cell in _body_locations(tokens, document):
        if index and any(
            child.type == "link_open" and child.attrGet("data-tag-kind") == "open_point"
            for child in token.children or []
        ):
            opening = tokens[index - 1]
            if opening.hidden:
                opening = next(item for item in reversed(tokens[:index - 1])
                               if item.nesting == 1 and not item.hidden)
            opening.attrSet("data-source-line", str(line))
            if cell:
                opening.attrSet("data-source-cell", str(cell))
    rendered = markdown.renderer.render(tokens, markdown.options, {})
    _assert_portable_references(rendered, chapter.source_path)
    return rendered


def _body_line_offset(chapter: Chapter, document: ChapterContent) -> int:
    """Lines before the body in its source file, for source-located diagnostics."""
    offset = document._body_line_offset
    if offset is None:
        source = chapter.source_path.read_text(encoding="utf-8-sig")
        offset = source.count("\n", 0, source.find(document.body)) if document.body in source else 0
    return offset


def _body_tokens_and_offset(chapter: Chapter, document: ChapterContent) -> tuple[Sequence[Token], int]:
    tokens = document._body_tokens if document._body_tokens is not None else _markdown(
        chapter, [], chapter.source_path.parent, resolve_references=False,
    ).parse(document.body)
    return tokens, _body_line_offset(chapter, document)


def paragraph_warnings(
    chapter: Chapter, document: ChapterContent, max_lines: int, line_characters: int,
) -> list[str]:
    tokens, offset = _body_tokens_and_offset(chapter, document)
    diagnostics = []
    for index, token in enumerate(tokens):
        if token.type != "inline" or index == 0 or tokens[index - 1].type != "paragraph_open":
            continue
        text = " ".join(
            child.content for child in token.children or []
            if child.type in {"text", "code_inline"} and not child.content.startswith("#mark/")
        )
        if (callout := callout_marker(text)) and tokens[index - 2].type == "blockquote_open":
            text = text[callout.end():]
        text = text.strip()
        lines = len(wrap(text, width=line_characters))
        if lines > max_lines:
            line = (token.map[0] if token.map else 0) + offset + 1
            diagnostics.append(
                f"{chapter.source_path}:{line}: long paragraph "
                f"({lines} estimated lines at {line_characters} characters; maximum {max_lines}). "
                "Split it into shorter paragraphs."
            )
    return diagnostics


def _prose_text(children: Sequence[Token]) -> str:
    """Plain prose of inline children; code and other inline markup break a phrase."""
    return "".join(
        child.content if child.type == "text"
        else " " if child.type in {"softbreak", "hardbreak"} else "\x00"
        for child in children
    )


def _italic_only(children: Sequence[Token]) -> bool:
    visible = [child for child in children
               if child.type not in {"softbreak", "hardbreak"}
               and not (child.type == "text" and not child.content.strip())]
    if len(visible) < 3 or visible[0].type != "em_open" or visible[-1].type != "em_close":
        return False
    depth = 0
    for child in visible[:-1]:
        depth += {"em_open": 1, "em_close": -1}.get(child.type, 0)
        if depth == 0:
            return False
    return True


def figure_warnings(
    chapter: Chapter, document: ChapterContent, reference_index: NoteReferenceIndex | None,
) -> list[str]:
    """Figure lint: captions inside every figure, block ids, and block links, not typed numbers."""
    # Authored tokens, as figure numbering sees them: links unresolved, image sources as written.
    source = (reference_index.sources_by_path.get(chapter.source_path)
              if reference_index else None) or document._source
    tokens = source.tokens if source is not None else shared_authoring_markdown().parse(document.body)
    offset = _body_line_offset(chapter, document)
    presentation = (reference_index.figure_presentation if reference_index
                    and reference_index.figure_presentation else document_presentation({})["figures"])
    references = (reference_index.figure_references if reference_index
                  and reference_index.figure_references else _packaged_figure_references())
    labels = sorted({*references["labels"], presentation["label"], presentation["labelPlural"]},
                    key=len, reverse=True)
    label_pattern = "|".join(re.escape(label) for label in labels)
    typed = re.compile(rf"(?<!\w)(?:{label_pattern})\s+(?P<number>\d+(?:\.\d+)*)", re.IGNORECASE)
    caption_start = re.compile(rf"\s*(?:{label_pattern})\s+\d", re.IGNORECASE)
    findings: list[tuple[int, str]] = []

    def line(token: Token) -> int:
        return (token.map[0] if token.map else 0) + offset + 1

    def warn(token: Token, message: str) -> None:
        findings.append((line(token), f"{chapter.source_path}:{line(token)}: {message}"))

    fences = list(_figure_fences(tokens))
    neighbours: list[tuple[int, int]] = []
    for position, block in fences:
        if not _figure_captioned(tokens[position].content):
            warn(tokens[position], "figure without caption. Add a caption to the figure fence.")
        if block is None:
            warn(tokens[position], "figure without block id. Add a line ^name after the fence "
                                   "so references can link it.")
        neighbours.append((position - 1, position + (4 if block is not None else 1)))
    for index, token in enumerate(tokens):
        children = token.children or []
        if (token.type == "inline" and index and tokens[index - 1].type == "paragraph_open"
                and len(children) == 1 and children[0].type == "image"):
            warn(token, "image without caption. Use a figure fence with kind: image, "
                        f"source: {children[0].attrGet('src')} and a caption.")
            neighbours.append((index - 2, index + 2))
    outside: set[int] = set()
    for before, after in neighbours:
        candidates = []
        if before > 0 and tokens[before].type == "paragraph_close":
            candidates.append(before - 1)
        if after + 1 < len(tokens) and tokens[after].type == "paragraph_open":
            candidates.append(after + 1)
        for candidate in candidates:
            children = tokens[candidate].children or []
            if candidate not in outside and (
                _italic_only(children) or caption_start.match(_prose_text(children))
            ):
                outside.add(candidate)
                warn(tokens[candidate], "caption outside the figure. Move the text into the "
                                        "figure's caption and delete the paragraph.")

    own = reference_index.figures.get(chapter.source_path, ((), {}))[0] if reference_index else ()
    fence_lines = [line(tokens[position]) for position, _ in fences]

    def suggestion(number: str) -> str:
        found = next(((None, entry, place) for place, entry in enumerate(own)
                      if entry.number == number), None)
        if found is None and reference_index is not None:
            found = next(((path, entry, None)
                          for path, (entries, _) in reference_index.figures.items()
                          if path != chapter.source_path for entry in entries
                          if entry.number == number), None)
        ordinal = int(number.rsplit(".", 1)[-1])
        if found is None and 1 <= ordinal <= len(own):
            found = (None, own[ordinal - 1], ordinal - 1)
        if found is None:
            return ("Link the figure instead with an Obsidian block link such as [[#^name]] "
                    "or [[note#^name]].")
        path, entry, place = found
        note = "" if path is None else path.stem
        if entry.block is not None:
            return f"Link the figure instead: [[{note}#^{entry.block}]]."
        where = f"at line {fence_lines[place]}" if path is None else f"in {path.name}"
        return (f"Link the figure instead: add a block id after the figure {where} "
                f"and link it with [[{note}#^name]].")

    def check_prose(token: Token, children: Sequence[Token]) -> None:
        for match in typed.finditer(_prose_text(children)):
            warn(token, f"typed figure number '{match[0]}'. {suggestion(match['number'])}")

    for index, token in enumerate(tokens):
        if token.type == "inline" and index not in outside:
            check_prose(token, token.children or [])
    for position, _ in fences:
        try:
            caption = yaml.safe_load(tokens[position].content).get("caption") or []
        except (yaml.YAMLError, AttributeError):
            continue
        for paragraph in caption if isinstance(caption, list) else [caption]:
            if isinstance(paragraph, str):
                for inline in shared_authoring_markdown().parseInline(paragraph):
                    check_prose(tokens[position], inline.children or [])
    return [message for _, message in sorted(findings, key=lambda finding: finding[0])]


# CommonMark links, images and reference definitions need "](", "][" or "]:" with no gap, and
# wikilinks need "[["; authoring comments are stripped before parsing and could close a gap.
_LINK_SYNTAX = ("](", "[[", "][", "]:", "<!--")
EXTERNAL_URL = re.compile(r"(?:https?:)?//", re.IGNORECASE)
_BARE_URL = re.compile(r"(?<![\w/])https?://[^\s<>()\[\]]+", re.IGNORECASE)
_MARKDOWN_EXTERNAL_LINK = re.compile(r"\]\(\s*<?(?:https?:)?//", re.IGNORECASE)


def _link_properties(value: object, location: str = ""):
    """Yield (location, path) for every ``linkProperty`` declared in a base definition."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "linkProperty" and isinstance(item, str):
                yield location, item
            else:
                yield from _link_properties(item, f"{location}.{key}" if location else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _link_properties(item, f"{location}.{index}")


def _external_values(value: object) -> bool:
    return any(EXTERNAL_URL.match(text.strip()) or _MARKDOWN_EXTERNAL_LINK.search(text)
               for text in _metadata_strings(value))


def external_link_warnings(
    chapter: Chapter, document: ChapterContent, metadata_by_path: dict[Path, dict[str, object]],
) -> list[str]:
    """Lint direct external links: they belong in a note's ``url`` (input-model "Reference notes")."""
    tokens, offset = _body_tokens_and_offset(chapter, document)
    diagnostics = []
    advice = "link a note that holds it in its url field instead"
    for token in tokens:
        if token.type != "inline":
            continue
        line = (token.map[0] if token.map else 0) + offset + 1
        inside_link = 0
        for child in token.children or []:
            urls = []
            if child.type == "link_open":
                inside_link += 1
                if EXTERNAL_URL.match(child.attrGet("href") or ""):
                    urls = [child.attrGet("href")]
            elif child.type == "link_close":
                inside_link -= 1
            elif child.type == "text" and not inside_link:
                urls = _BARE_URL.findall(child.content)
            diagnostics.extend(
                f"{chapter.source_path}:{line}: external link {url} in prose; {advice}." for url in urls
            )
    for table in document.tables:
        for location, path in _link_properties(table.definition):
            node = path.rsplit(".", 1)[-1]
            if any(_external_values(_base_record_value(metadata, path))
                   or _external_values(_base_record_value(metadata, node))
                   for metadata in metadata_by_path.values()):
                diagnostics.append(
                    f"{chapter.source_path}: base table {table.key} {location}.linkProperty "
                    f"{path} resolves to an external URL; {advice}."
                )
    return diagnostics


def _may_link(text: str) -> bool:
    return "[" in text and any(syntax in text for syntax in _LINK_SYNTAX)


def render_inline(
    text: str,
    chapter: Chapter,
    chapters: list[Chapter],
    vault_root: Path,
    embed_pdfs: bool = True,
    reference_index: NoteReferenceIndex | None = None,
) -> str:
    # Without link syntax no link, image or wikilink exists, so the HTML is note-independent.
    if reference_index is not None and not _may_link(text):
        key = (text, embed_pdfs)
        html = reference_index.inline_html_by_key.get(key)
        if html is None:
            html = _shared_markdown(
                chapter, chapters, vault_root, embed_pdfs=embed_pdfs, reference_index=reference_index,
            ).renderInline(text)
            reference_index.inline_html_by_key[key] = html
        return html
    markdown = _shared_markdown(
        chapter, chapters, vault_root, embed_pdfs=embed_pdfs, reference_index=reference_index,
    )
    parsed = reference_index.inline_tokens_by_key.pop((markdown, text), None) if reference_index else None
    if parsed is None:
        return markdown.renderInline(text)
    tokens, env = parsed
    return markdown.renderer.render(tokens, markdown.options, env)


def _shared_markdown(
    chapter: Chapter, notes: list[Chapter], vault_root: Path, *, resolve_references: bool = True,
    embed_pdfs: bool = True,
    reference_index: NoteReferenceIndex | None = None,
) -> MarkdownIt:
    """Reuse a configured parser for callers that never customize its renderer."""
    if reference_index is None:
        return _markdown(
            chapter, notes, vault_root, resolve_references=resolve_references,
            embed_pdfs=embed_pdfs,
        )
    key = (chapter, id(notes), vault_root, resolve_references, embed_pdfs)
    cached = reference_index.markdown_by_key.get(key)
    if cached is None or cached[0] is not notes:
        cached = (notes, _markdown(
            chapter, notes, vault_root, resolve_references=resolve_references,
            embed_pdfs=embed_pdfs, reference_index=reference_index,
        ))
        reference_index.markdown_by_key[key] = cached
    return cached[1]


def _resolved(path: Path, reference_index: NoteReferenceIndex | None) -> Path:
    if reference_index is None:
        return path.resolve()
    resolved = reference_index.resolved_paths.get(path)
    if resolved is None:
        resolved = reference_index.resolved_paths[path] = path.resolve()
    return resolved


def _asset_bytes(path: Path, reference_index: NoteReferenceIndex | None) -> bytes:
    if reference_index is None:
        return path.read_bytes()
    if path not in reference_index.asset_bytes_by_path:
        reference_index.asset_bytes_by_path[path] = path.read_bytes()
    return reference_index.asset_bytes_by_path[path]


def _markdown(
    chapter: Chapter, notes: list[Chapter], vault_root: Path, *, resolve_references: bool = True,
    embed_pdfs: bool = True,
    reference_index: NoteReferenceIndex | None = None,
) -> MarkdownIt:
    markdown = authoring_markdown()
    markdown.enable("table")

    def render_math(text: str, options: dict[str, bool]) -> str:
        try:
            return mathml(text, display="block" if options["display_mode"] else "inline")
        except (
            math_errors.NumeratorNotFoundError, math_errors.DenominatorNotFoundError,
            math_errors.ExtraLeftOrMissingRightError, math_errors.MissingSuperScriptOrSubscriptError,
            math_errors.DoubleSubscriptsError, math_errors.DoubleSuperscriptsError,
            math_errors.NoAvailableTokensError, math_errors.InvalidStyleForGenfracError,
            math_errors.MissingEndError, math_errors.InvalidAlignmentError,
            math_errors.InvalidWidthError, math_errors.LimitsMustFollowMathOperatorError,
        ) as error:
            raise ContentError(
                f"Invalid math formula in {chapter.source_path}: {text!r} ({type(error).__name__})"
            ) from error

    markdown.use(dollarmath_plugin, allow_labels=False, allow_space=False, allow_digits=False,
                 renderer=render_math)
    validate_link = markdown.validateLink
    markdown.validateLink = lambda href: bool(re.fullmatch(
        r"data:(?:application/(?:pdf|octet-stream|json)|text/plain);base64,[A-Za-z0-9+/=\s]+",
        href,
    )) or validate_link(href)

    def push_file_link(state, target: str, label: str | None, marked: bool) -> None:
        href = quote(_relative_href(_resolve_attachment_target(
            target, chapter, vault_root, reference_index,
        ), chapter)) if resolve_references else target
        token = state.push("link_open", "a", 1)
        token.attrSet("href", href)
        if marked:
            token.meta["attachment_mark"] = True
        text = state.push("text", "", 0)
        text.content = (label or target.rsplit("/", 1)[-1]).strip()
        state.push("link_close", "a", -1)

    def embed(state, silent: bool) -> bool:
        match = EMBED.match(state.src, state.pos)
        if not match or state.linkLevel or not _is_file_target(match["target"].strip()):
            return False
        if not silent:
            target = match["target"].strip()
            if _is_image_name(target.partition("#")[0]):
                src = quote(_relative_href(_resolve_attachment_target(
                    target, chapter, vault_root, reference_index,
                ), chapter)) if resolve_references else target
                token = state.push("image", "img", 0)
                token.attrs = {"src": src, "alt": ""}
                alt = Token("text", "", 0)
                alt.content = (match["label"] or "").strip()
                token.children = [alt]
                token.content = alt.content
            else:
                push_file_link(state, target, match["label"], marked=True)
        state.pos = match.end()
        return True

    markdown.inline.ruler.before("image", "embed", embed)

    def wikilink(state, silent: bool) -> bool:
        match = WIKILINK.match(state.src, state.pos)
        if not match or state.linkLevel or state.src[match.end():].startswith("("):
            return False
        if not silent and _is_file_target(match["target"].strip()):
            push_file_link(state, match["target"].strip(), match["label"], marked=False)
        elif not silent:
            target = match["target"].strip()
            href = _note_reference(
                target, chapter, notes, vault_root, reference_index,
            ) if resolve_references else target
            token = state.push("link_open", "a", 1)
            token.attrSet("href", href)
            token.meta["note_link"] = True
            text = state.push("text", "", 0)
            label = match["label"]
            linked_name, _, heading = target.partition("#")
            if resolve_references and not label and heading.startswith("^"):
                entry = _figure_reference(
                    linked_name, heading, target, chapter, notes, vault_root, reference_index,
                )
                token.meta["figure_reference"] = entry
                label = entry.label
            if resolve_references and not label and heading and not heading.startswith("^"):
                # As the core labels it (obs capabilities/wikilinks#Link text).
                linked = linked_name and _resolve_chapter_target(
                    linked_name, notes, vault_root, chapter, reference_index,
                )
                label = f"{linked.title if linked else linked_name} > {heading}" if linked_name else heading
            if resolve_references and not label and not heading:
                linked = chapter if not linked_name else _resolve_chapter_target(
                    linked_name, notes, vault_root, chapter, reference_index,
                )
                if linked is not None:
                    metadata = (reference_index.metadata_by_path.get(linked.source_path)
                                if reference_index else None)
                    if metadata is None:
                        metadata, _ = _split_frontmatter(
                            linked.source_path.read_text(encoding="utf-8-sig"), linked.source_path,
                        )
                    if metadata.get("kind") == "quantity":
                        _validate_quantity_metadata(metadata, linked.source_path)
                        label = quantity_label(metadata)
                        if "query" in metadata:
                            _validate_query_references(metadata["query"], linked, notes,
                                                       vault_root, reference_index, set())
                            token.attrSet("data-quantity-reference",
                                          linked.source_path.relative_to(vault_root).as_posix())
                            token.attrSet("aria-busy", "true")
                            token.attrSet("role", "status")
                            label = "Calculating…"
                    else:
                        label = linked.title
            text.content = (label or target.rsplit("/", 1)[-1].removesuffix(".md")).strip()
            state.push("link_close", "a", -1)
        state.pos = match.end()
        return True

    markdown.inline.ruler.before("link", "wikilink", wikilink)

    def resolve_links(state) -> None:
        for token in state.tokens:
            if token.type == "fence" and token.info.strip() == "figure":
                from obs_html_interim.figures import FigureError, figure_spec
                try:
                    caption = figure_spec(token.content).get("caption", "")
                except (FigureError, yaml.YAMLError) as error:
                    raise ContentError(f"Figure in {chapter.source_path}: {error}") from error
                paragraphs = caption if isinstance(caption, list) else [caption]
                token.children = [
                    child for paragraph in paragraphs
                    for inline in markdown.parseInline(paragraph)
                    for child in inline.children or []
                ]
                continue
            children = token.children or []
            for index, child in enumerate(children):
                if child.type == "image" and _marks_attachment(child.attrGet("src") or ""):
                    link = Token("link_open", "a", 1)
                    link.attrs = {"href": child.attrGet("src")}
                    if child.attrGet("title"):
                        link.attrSet("title", child.attrGet("title"))
                    link.meta["attachment_mark"] = True
                    label = child.children or []
                    if not label:
                        label = [Token("text", "", 0)]
                        label[0].content = child.content
                    children[index:index + 1] = [link, *label, Token("link_close", "a", -1)]
                    child = link
                if child.type == "image":
                    src = child.attrGet("src") or ""
                    parsed_image = urlparse(src)
                    if not parsed_image.scheme and not parsed_image.netloc:
                        image = (chapter.source_path.parent / unquote(parsed_image.path)).resolve()
                        if not image.is_relative_to(vault_root.resolve()):
                            raise ContentError(f"Image path escapes the vault: {src}")
                        mime = mimetypes.guess_type(image.name)[0]
                        if mime not in IMAGE_TYPES:
                            raise ContentError(f"Unsupported image type: {src}")
                        if not image.is_file():
                            raise ContentError(f"Image does not exist: {src}")
                        child.attrSet("src", f"data:{mime};base64," +
                                      base64.b64encode(_asset_bytes(image, reference_index)).decode("ascii"))
                if child.type != "link_open":
                    continue
                href = child.attrGet("href") or ""
                if href == "obs-source:archive":
                    child.attrSet("data-source-download", "")
                if urlparse(href).scheme or urlparse(href).netloc:
                    continue
                if not child.meta.get("note_link"):
                    parsed = urlparse(href)
                    if href.startswith("#") or Path(parsed.path).suffix.casefold() == ".md" or not Path(parsed.path).suffix:
                        name, _, fragment = unquote(href).partition("#")
                        href = _note_reference(
                            unquote(href), chapter, notes, vault_root, reference_index,
                        )
                        child.attrSet("href", href)
                        if (fragment.startswith("^") and index + 1 < len(children)
                                and children[index + 1].type == "link_close"):
                            label = Token("text", "", 0)
                            entry = _figure_reference(
                                name, fragment, unquote(href), chapter, notes, vault_root,
                                reference_index,
                            )
                            child.meta["figure_reference"] = entry
                            label.content = entry.label
                            children.insert(index + 1, label)
                    else:
                        attachment = (chapter.source_path.parent / unquote(parsed.path)).resolve()
                        if not attachment.is_relative_to(vault_root.resolve()):
                            raise ContentError(f"Attachment path escapes the vault: {href}")
                        if not attachment.is_file():
                            raise ContentError(f"Attachment does not exist: {href}")
                        if (not child.meta.get("attachment_mark") or reference_index is None
                                or not reference_index.embed_attachments):
                            _cite_attachment(children, index, attachment.relative_to(
                                vault_root.resolve()).as_posix())
                            continue
                        if attachment.suffix.casefold() == ".pdf" and not embed_pdfs:
                            child.attrSet("href", attachment.as_uri() + (
                                "#" + parsed.fragment if parsed.fragment else ""
                            ))
                            continue
                        mime = "application/pdf" if attachment.suffix.casefold() == ".pdf" else "application/octet-stream"
                        child.attrSet("href", f"data:{mime};base64," +
                                      base64.b64encode(_asset_bytes(attachment, reference_index)).decode("ascii"))
                        child.attrSet("download", attachment.name)
                        continue
                slug, _, anchor = href.removeprefix("#").partition("/")
                linked = next((note for note in notes if note.slug == slug), None)
                if linked is None or not anchor.startswith("mark-"):
                    continue
                mark = next((mark for mark in _reference_document(linked, reference_index).marks
                             if mark.anchor == anchor and mark.kind == "open_point"), None)
                if mark is None:
                    continue
                child.attrSet("data-tag-kind", mark.kind)
                child.attrSet("data-tag-label", mark.label)
                end = next((position for position in range(index + 1, len(children))
                            if children[position].type == "link_close"), index + 1)
                label = Token("text", "", 0)
                label.content = f"#mark/{mark.kind}/{mark.label}"
                label.meta["mark_reference"] = True
                children[index + 1:end] = [label]
            if reference_index is not None and reference_index.figure_presentation:
                merged = _merge_figure_references(
                    children, reference_index.figure_presentation["labelPlural"],
                    reference_index.figure_references["conjunctions"],
                )
                if merged is not children:
                    token.children = merged
    if resolve_references:
        markdown.core.ruler.after("inline", "resolve-note-links", resolve_links)
    return markdown


def _is_file_target(target: str) -> bool:
    name = target.partition("#")[0].strip()
    return bool(_FILE_SUFFIX.search(name)) and Path(name).suffix.casefold() not in _NOTE_SUFFIXES


def _marks_attachment(src: str) -> bool:
    """Whether ![label](src) marks a local non-image file for embedding rather than an image."""
    parsed = urlparse(src)
    if parsed.scheme or parsed.netloc:
        return False
    path = unquote(parsed.path)
    return _is_file_target(path) and not _is_image_name(path)


def _is_image_name(name: str) -> bool:
    """Image files are document content; unsupported image types still fail as images."""
    return (mimetypes.guess_type(name)[0] or "").startswith("image/")


def _relative_href(path: Path, chapter: Chapter) -> str:
    return Path(os.path.relpath(path, chapter.source_path.parent)).as_posix()


def _resolve_attachment_target(
    target: str, chapter: Chapter, vault_root: Path, reference_index: NoteReferenceIndex | None,
) -> Path:
    """Resolve a wikilink file target like a note name: note folder, vault root, unique name."""
    name = unquote(target.partition("#")[0].strip())
    vault = _resolved(vault_root, reference_index)
    for root in (chapter.source_path.parent, vault_root):
        candidate = _resolved(root / name, reference_index)
        if not candidate.is_relative_to(vault):
            raise ContentError(f"Attachment path escapes the vault: {name}")
        if candidate.is_file():
            return candidate
    files_by_name = reference_index.files_by_name if reference_index else {}
    if not files_by_name:
        for path in vault.rglob("*"):
            relative = path.relative_to(vault)
            if path.is_file() and not any(part.startswith(".") for part in relative.parts):
                files_by_name.setdefault(path.name.casefold(), []).append(path)
    matches = files_by_name.get(Path(name).name.casefold(), []) if "/" not in name else []
    if len(matches) > 1:
        raise ContentError(f"Ambiguous attachment name: {name}")
    if not matches:
        raise ContentError(f"Attachment does not exist: {name}")
    return matches[0]


def _cite_attachment(children: list[Token], index: int, path: str) -> None:
    """Replace a linked source file by provenance text: its label and vault-relative path."""
    end = next((position for position in range(index + 1, len(children))
                if children[position].type == "link_close"), None)
    if end is None:
        raise ContentError(f"Unclosed attachment link: {path}")
    opening, closing = children[index], children[end]
    opening.type, opening.tag, opening.attrs = "source_reference_open", "span", {
        "class": "source-reference", "data-source-path": path,
    }
    closing.type, closing.tag = "source_reference_close", "span"
    before, code, after = Token("text", "", 0), Token("code_inline", "code", 0), Token("text", "", 0)
    before.content, code.content, after.content = " (", path, ")"
    children[end + 1:end + 1] = [before, code, after]


def _body_locations(tokens: Sequence[Token], document: ChapterContent):
    counts = Counter(token.map[0] for token in tokens if token.type == "inline" and token.map)
    cells: Counter[int] = Counter()
    for index, token in enumerate(tokens):
        if token.type != "inline" or not token.map:
            continue
        start = token.map[0]
        cells[start] += 1
        yield index, token, start + 1 + (document._body_line_offset or 0), (
            cells[start] if counts[start] > 1 else None
        )


def collect_mark_backlinks(
    notes: list[Chapter], documents: list[ChapterContent], vault_root: Path,
    reference_index: NoteReferenceIndex | None = None,
) -> dict[tuple[str, str], list[dict[str, str]]]:
    """Derive source locations once, before table and preview projections exist."""
    backlinks = {
        (mark.kind, mark.label): [{
            "href": f"#{note.slug}/@{mark.anchor}", "label": note.title,
        }]
        for note, document in zip(notes, documents, strict=True)
        for mark in document.marks
    }
    anchors = {
        f"#{note.slug}/{mark.anchor}": (mark.kind, mark.label)
        for note, document in zip(notes, documents, strict=True)
        for mark in document.marks if mark.kind == "open_point"
    }

    def add(tokens: Sequence[Token], href: str, label: str) -> None:
        for token in tokens:
            for child in token.children or []:
                identity = anchors.get(child.attrGet("href")) if child.type == "link_open" else None
                if identity is not None:
                    location = {"href": href, "label": label}
                    if location not in backlinks[identity]:
                        backlinks[identity].append(location)

    for note, document in zip(notes, documents, strict=True):
        markdown = _shared_markdown(note, notes, vault_root, reference_index=reference_index)
        tokens = document._body_tokens if document._body_tokens is not None else markdown.parse(document.body)
        for _, token, line, cell in _body_locations(tokens, document):
            identities = {(kind, label) for kind, label, _ in _paragraph_markers(token)}
            own_mark = next((mark for mark in document.marks
                             if (mark.kind, mark.label) in identities), None)
            add([token], f"#{note.slug}/@{own_mark.anchor}" if own_mark
                else f"#{note.slug}?sourceLine={line}" + (f"&sourceCell={cell}" if cell else ""),
                note.title if own_mark else f"{note.title} · line {line}"
                + (f" · cell {cell}" if cell else ""))

        def properties(value: object, field: str = "") -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    properties(item, f"{field}.{key}" if field else key)
            elif isinstance(value, list):
                nested = any(isinstance(item, (dict, list)) for item in value)
                for index, item in enumerate(value):
                    properties(item, f"{field}.{index}" if nested else field)
            elif isinstance(value, str) and _may_link(value):
                env: dict[str, object] = {}
                tokens = markdown.parseInline(value, env)
                if reference_index is not None:
                    reference_index.inline_tokens_by_key[(markdown, value)] = (tokens, env)
                add(tokens,
                    f"#{note.slug}?sourceField={quote(field, safe='')}", f"{note.title} · {field}")

        properties(document.frontmatter)
    return backlinks


def _reference_document(
    chapter: Chapter, reference_index: NoteReferenceIndex | None,
) -> ChapterContent:
    if reference_index is not None:
        document = reference_index.documents_by_path.get(chapter.source_path)
        if document is not None:
            return document
        source = reference_index.sources_by_path.get(chapter.source_path)
        if source is not None:
            document = _chapter_content(chapter, source)
            reference_index.documents_by_path[chapter.source_path] = document
            return document
    return read_chapter_content(chapter)


def _figure_reference(
    linked_name: str, heading: str, target: str, chapter: Chapter, notes: list[Chapter],
    vault_root: Path, reference_index: NoteReferenceIndex | None,
) -> FigureNumber:
    """An unlabelled block reference displays the referenced figure's current number."""
    linked = chapter if not linked_name else _resolve_chapter_target(
        unquote(linked_name), notes, vault_root, chapter, reference_index,
    )
    entry = _figure_block(linked, unquote(heading)[1:], reference_index) if linked else None
    if entry is None or entry.label is None:
        raise ContentError(
            f"Unlabelled reference '{target}' in {chapter.source_path} must name a numbered "
            "(captioned) figure in the contents; otherwise give the link a label."
        )
    return entry


def _merge_figure_references(
    children: list[Token], plural: str, conjunctions: Sequence[str],
) -> list[Token]:
    """Adjacent unlabelled figure references read as one plural: Figures 2.4 and 2.5, 2.4–2.6."""
    units = [index for index, child in enumerate(children)
             if child.type == "link_open" and "figure_reference" in child.meta]
    if len(units) < 2:
        return children
    words = "|".join(re.escape(word) for word in sorted(conjunctions, key=len, reverse=True))
    separator = re.compile(rf"\s*(?:,\s*)?(?:(?:{words})\s+)?", re.IGNORECASE)
    groups = [[units[0]]]
    for previous, following in zip(units, units[1:]):
        between = children[previous + 3:following]
        text = "".join(" " if child.type == "softbreak" else child.content for child in between)
        if (all(child.type in {"text", "softbreak"} for child in between)
                and separator.fullmatch(text)):
            groups[-1].append(following)
        else:
            groups.append([following])

    def consecutive(first: Token, second: Token) -> bool:
        head, _, last = first.meta["figure_reference"].number.rpartition(".")
        next_head, _, next_last = second.meta["figure_reference"].number.rpartition(".")
        return head == next_head and int(next_last) == int(last) + 1

    merged, position = [], 0
    for group in (group for group in groups if len(group) > 1):
        merged.extend(children[position:group[0]])
        label = Token("text", "", 0)
        label.content = f"{plural} "
        merged.append(label)
        start = 0
        while start < len(group):
            end = start
            while end + 1 < len(group) and consecutive(children[group[end]], children[group[end + 1]]):
                end += 1
            shown = [group[start], group[end]] if end - start >= 2 else [group[start]]
            for index in shown:
                children[index + 1].content = children[index].meta["figure_reference"].number
            merged.extend(children[shown[0]:shown[0] + 3])
            if len(shown) == 2:
                dash = Token("text", "", 0)
                dash.content = "–"
                merged.extend([dash, *children[shown[1]:shown[1] + 3]])
            else:
                end = start
            if end + 1 < len(group):
                merged.extend(children[group[end] + 3:group[end + 1]])
            start = end + 1
        position = group[-1] + 3
    return [*merged, *children[position:]]


def _figure_block(
    linked: Chapter, block: str, reference_index: NoteReferenceIndex | None,
) -> FigureNumber | None:
    if reference_index is not None and linked.source_path in reference_index.figures:
        return reference_index.figures[linked.source_path][1].get(block)
    if linked.generated == "home":
        body = read_manifest(linked.source_path).abstract
    else:
        _, body = _split_frontmatter(
            linked.source_path.read_text(encoding="utf-8-sig"), linked.source_path,
        )
    tokens = shared_authoring_markdown().parse(body)
    if any(found == block for _, found in _figure_fences(tokens)):
        return FigureNumber(None, block, f"{linked.slug}--block-{block}")
    return None


def _note_reference(
    target: str, current: Chapter, notes: list[Chapter], vault_root: Path,
    reference_index: NoteReferenceIndex | None = None,
) -> str:
    name, _, heading = target.partition("#")
    name = unquote(name)
    linked = current if not name else _resolve_chapter_target(
        name, notes, vault_root, current, reference_index,
    )
    if linked is None:
        raise ContentError(f"Unresolved note reference '{target}' in {current.source_path}")
    if heading.startswith("^"):
        entry = _figure_block(linked, unquote(heading)[1:], reference_index)
        if entry is None:
            raise ContentError(f"Unresolved figure block reference '{target}' in {current.source_path}")
        return f"#{linked.slug}/block-{entry.block}"
    if heading:
        heading = unquote(heading)
        source = reference_index.sources_by_path.get(linked.source_path) if reference_index else None
        if source is not None:
            if heading.startswith("mark-"):
                document = _reference_document(linked, reference_index)
                if any(mark.anchor == heading for mark in document.marks):
                    return f"#{linked.slug}/{heading}"
            heading_id = _unique_slug(unquote(heading), set())
            if heading_id not in source.headings:
                raise ContentError(f"Unresolved note heading '{target}' in {current.source_path}")
            return f"#{linked.slug}/{heading_id}"
        if heading.startswith("mark-") and any(
            mark.anchor == heading for mark in read_chapter_content(linked).marks
        ):
            return f"#{linked.slug}/{heading}"
        heading_id = _unique_slug(unquote(heading), set())
        if linked.generated == "home":
            body = read_manifest(linked.source_path).abstract
        else:
            _, body = _split_frontmatter(
                linked.source_path.read_text(encoding="utf-8-sig"), linked.source_path,
            )
        tokens = shared_authoring_markdown().parse(body)
        _assign_heading_ids(tokens, linked.slug)
        if not any(token.attrGet("id") == f"{linked.slug}--{heading_id}" for token in tokens):
            raise ContentError(f"Unresolved note heading '{target}' in {current.source_path}")
        return f"#{linked.slug}/{heading_id}"
    return f"#{linked.slug}"


def _heading_ids(tokens: Sequence[Token]):
    seen: set[str] = set()
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            inline = tokens[index + 1]
            label = "".join(child.content for child in inline.children or [] if child.type in {"text", "code_inline"})
            yield token, _unique_slug(label, seen)


def _assign_heading_ids(tokens: list[Token], slug: str) -> None:
    for token, heading in _heading_ids(tokens):
        token.attrSet("id", f"{slug}--{heading}")


def read_chapter_content(chapter: Chapter, source: str | None = None) -> ChapterContent:
    if source is None:
        source = chapter.source_path.read_text(encoding="utf-8-sig")
    return _chapter_content(chapter, _note_source(source, chapter.source_path))


def _note_source(source: str, source_path: Path) -> _NoteSource:
    frontmatter, body = _split_frontmatter(source, source_path)
    offset = source.count("\n", 0, source.find(body))
    return _NoteSource(frontmatter, body, offset)


def _chapter_content(chapter: Chapter, source: _NoteSource) -> ChapterContent:
    frontmatter, body = source.frontmatter, source.body
    _note_aliases(frontmatter, chapter.source_path)
    if frontmatter.get("kind") == "quantity":
        _validate_quantity_metadata(frontmatter, chapter.source_path)
    if frontmatter.get("kind") == "glossary":
        for key in ("term", "definition"):
            if not isinstance(frontmatter.get(key), str) or not frontmatter[key].strip():
                raise ContentError(f"Glossary {key} must be a non-empty string: {chapter.source_path}")
    marks: list[Mark] = []
    seen: set[tuple[str, str]] = set()
    tokens = source.tokens
    from obs_html_interim.properties import property_editors
    editors = property_editors(tokens, chapter, frontmatter)
    tables = _parse_base_tables(tokens, chapter, chapter.vault_root)
    source_notes = []
    for table in tables:
        source_notes.extend(
            expansion["sourceNote"]
            for expansion in table.definition.get("obsHtml", {}).get("expandProperties", {}).values()
        )
    for token in tokens:
        if token.type == "fence" and token.info.strip() == "cards":
            from obs_html_interim.cards import parse_card_spec
            for card in parse_card_spec(token.content, chapter.source_path)["cards"]:
                series = card.get("obsHtml", {}).get("metricsFrom")
                if series:
                    source_notes.append(series["sourceNote"])
                    if series.get("link"):
                        source_notes.append(series["link"]["note"])
        if token.type != "fence" or token.info.strip().casefold() != "figure":
            continue
        from obs_html_interim.figures import FigureError, figure_spec
        try:
            source_note = figure_spec(token.content).get("sourceNote")
        except (FigureError, yaml.YAMLError) as error:
            raise ContentError(f"Figure in {chapter.source_path}: {error}") from error
        if source_note:
            source_notes.append(source_note)
    for index, token in enumerate(tokens):
        if token.type != "inline" or index == 0 or tokens[index - 1].type != "paragraph_open":
            continue
        paragraph_markers = _paragraph_markers(token, chapter.source_path)
        if not paragraph_markers:
            continue
        visible = _remove_markers(token.content, [item[2] for item in paragraph_markers])
        first_kind, first_label, _ = paragraph_markers[0]
        anchor = _marker_anchor(chapter.slug, first_kind, first_label)
        for kind, label, _ in paragraph_markers:
            if kind not in MARKER_KINDS:
                raise ContentError(f"Unknown paragraph marker kind '{kind}' in {chapter.source_path}")
            identity = (kind, label)
            if identity in seen:
                raise ContentError(
                    f"Duplicate paragraph marker #mark/{kind}/{label} in {chapter.source_path}"
                )
            seen.add(identity)
            marks.append(Mark(kind=kind, label=label, text=visible, anchor=anchor))
    return ChapterContent(
        frontmatter, body, tuple(marks), tables,
        source_notes=tuple(dict.fromkeys(source_notes)),
        editable_properties=editors,
        _body_line_offset=source.line_offset,
        _source=source,
    )


def _parse_base_tables(
    tokens: Sequence[Token], chapter: Chapter, vault_root: Path | None,
) -> tuple[BaseTable, ...]:
    tables: list[BaseTable] = []

    def add_tables(block_tokens: Sequence[Token]) -> None:
        for token in block_tokens:
            info = token.info.strip().split(maxsplit=1)
            if token.type == "base_embed":
                path = _base_file(token.meta["target"], chapter, vault_root)
                stat = path.stat()
                try:
                    definition = deepcopy(_base_file_definition(path, stat.st_mtime_ns, stat.st_size))
                except ContentError as error:
                    raise ContentError(f"{error} {chapter.source_path} embeds it.") from error
                if token.meta["view"]:
                    definition = _single_view(definition, token.meta["view"], path, chapter)
                tables.append(BaseTable(f"{chapter.slug}-base-{len(tables) + 1}", definition))
            elif token.type == "fence" and info and info[0] == "base":
                definition = _base_definition(
                    token.content, chapter.source_path, f"base fence {len(tables) + 1}",
                )
                tables.append(BaseTable(f"{chapter.slug}-base-{len(tables) + 1}", definition))
            elif token.type == "fence" and info and info[0] == "cards":
                from obs_html_interim.cards import parse_card_spec

                for card in parse_card_spec(token.content, chapter.source_path)["cards"]:
                    add_tables(shared_authoring_markdown().parse(card["body"]))

    add_tables(tokens)
    return tuple(tables)


def _base_definition(content: str, source_path: Path, place: str) -> dict[str, object]:
    try:
        loaded = _safe_load_yaml(content)
    except yaml.YAMLError as error:
        raise ContentError(f"Invalid {place} in {source_path}: {error}") from error
    if not isinstance(loaded, dict):
        raise ContentError(f"Base fence must contain a YAML mapping: {source_path}, {place}")
    definition = _normalize_mapping(loaded, source_path)
    validate_base_definition(definition, source_path, place)
    return definition


@cache
def _base_file_definition(path: Path, _mtime_ns: int, _size: int) -> dict[str, object]:
    """Parse and validate one version of a ``.base`` file once; every embed copies it."""
    return _base_definition(path.read_text(encoding="utf-8-sig"), path, "base file")


def _single_view(
    definition: dict[str, object], name: str, path: Path, chapter: Chapter,
) -> dict[str, object]:
    """``![[file.base#View]]`` embeds only that view (input-model, Registers)."""
    views = [view for view in definition["views"] if view.get("name") == name]
    if not views:
        raise ContentError(f"Embedded base {path.name} has no view {name!r}: {chapter.source_path}")
    definition["views"] = views
    expansions = definition.get("obsHtml", {}).get("expandProperties")
    if expansions:
        kept = {field: item for field, item in expansions.items() if field in views[0]["order"]}
        if kept:
            definition["obsHtml"]["expandProperties"] = kept
        else:
            del definition["obsHtml"]["expandProperties"]
    return definition


def _base_file(target: str, chapter: Chapter, vault_root: Path | None) -> Path:
    """Resolve an embedded ``.base`` file as Obsidian does: a vault-relative path, or a unique name."""
    if vault_root is None:
        raise ContentError(f"Embedded base {target} needs its vault: {chapter.source_path}")
    vault_root = vault_root.resolve()
    if "/" in target:
        matches = [vault_root.joinpath(*PurePosixPath(target).parts).resolve()]
        matches = [path for path in matches if path.is_file()]
    else:
        matches = [path.resolve() for path in vault_root.rglob(target) if path.is_file() and not any(
            part.startswith(".") for part in path.relative_to(vault_root).parts)]
    if len(matches) != 1 or not matches[0].is_relative_to(vault_root):
        problem = "is ambiguous" if len(matches) > 1 else "does not resolve to a file inside the vault"
        raise ContentError(f"Embedded base {target} {problem}: {chapter.source_path}")
    return matches[0]


@cache
def _base_validator() -> Draft202012Validator:
    assets = json.loads(files("obs_html_interim").joinpath("assets.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resource("assets.schema.json", Resource.from_contents(assets))
    return Draft202012Validator(_base_schema(), registry=registry)


def validate_base_definition(definition: dict[str, object], source_path: Path, fence: str | None = None) -> None:
    place = f"{source_path}, {fence}" if fence else str(source_path)
    if "filters" in definition:
        _compile_base_filter_at(definition["filters"], f"at filters in {place}")
    views = definition.get("views")
    for index, view in enumerate(views if isinstance(views, list) else []):
        if isinstance(view, dict) and "filters" in view:
            _compile_base_filter_at(view["filters"], f"at views.{index}.filters in {place}")
    error = schema_error(list(_base_validator().iter_errors(definition)), source_path,
                         "capabilities/bases", place="" if fence in {None, "base file"} else fence)
    if error:
        raise ContentError(str(error))
    for property_name in definition.get("properties", {}):
        _base_property(property_name)
    for property_name, declaration in definition.get("properties", {}).items():
        options = declaration.get("obsHtml", {})
        if "leadingLines" in options:
            for field in options["leadingLines"]:
                _base_property(field)
            conflict = next((key for key in ("icon", "icons", "reference", "editable") if key in options), None)
            if conflict:
                raise ContentError(
                    f"Invalid base definition at properties.{property_name}.obsHtml in {source_path}: "
                    f"leadingLines cannot be combined with {conflict}"
                )
    for view in definition["views"]:
        for property_name in view["order"]:
            _base_property(property_name)
        for key in ("groupBy", "sort"):
            directives = view.get(key, [])
            for directive in directives if isinstance(directives, list) else [directives]:
                _base_property(directive["property"])
        if "groupOrder" in view.get("obsHtml", {}) and "groupBy" not in view:
            raise ContentError(f"Invalid base definition in {place}: obsHtml.groupOrder requires groupBy")
        for property_name in view.get("columnSize", {}):
            _base_property(property_name)
        if "columnSize" in view and view.get("obsHtml", {}).get("columnSizing") == "equal":
            raise ContentError(
                f"Invalid base definition in {place}: columnSize cannot be combined with columnSizing: equal"
            )
    members = definition.get("obsHtml", {}).get("members", [])
    paths = [member["path"] for member in members]
    if len(paths) != len(set(paths)):
        raise ContentError(f"Duplicate obsHtml.members path in {source_path}")
    names = [str(view.get("name", "")).strip() for view in definition["views"]]
    if len(names) > 1 and (not all(names) or len(set(names)) != len(names)):
        raise ContentError(f"Several views of one base need unique nonempty names in {place}")


def _note_aliases(metadata: dict[str, object], source_path: Path) -> list[str]:
    aliases = metadata.get("aliases", [])
    if isinstance(aliases, str):
        aliases = [aliases]
    if not isinstance(aliases, list) or not all(
        isinstance(alias, str) and alias.strip() for alias in aliases
    ):
        raise ContentError(f"Frontmatter aliases must be a string or list of non-empty strings: {source_path}")
    return [alias.strip() for alias in aliases]


def _validate_quantity_metadata(metadata: dict[str, object], source_path: Path) -> None:
    if ("value" in metadata) == ("query" in metadata):
        raise ContentError(f"Quantity requires exactly one of value or query: {source_path}")
    if "query" in metadata:
        from obs_html_interim.cards import validate_count_query
        validate_count_query(metadata["query"], source_path)
    value = metadata.get("value")
    if "value" in metadata and (
        isinstance(value, bool) or not isinstance(value, (int, float))
        or isinstance(value, float) and not isfinite(value)
    ):
        raise ContentError(f"Quantity value must be a finite number: {source_path}")
    unit = metadata.get("unit")
    if "unit" in metadata and (not isinstance(unit, str) or not unit.strip()):
        raise ContentError(f"Quantity unit must be a non-empty string when supplied: {source_path}")
    aliases = _note_aliases(metadata, source_path)
    if len(aliases) != 1 or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", aliases[0]):
        raise ContentError(
            f"Quantity requires one short variable-style alias: {source_path}"
        )
    source = metadata.get("source")
    sources = [source] if isinstance(source, str) else source
    if not isinstance(sources, list) or not sources or not all(
        isinstance(item, str) and item.strip() for item in sources
    ):
        raise ContentError(
            f"Quantity source must be a non-empty string or list of non-empty strings: {source_path}"
        )
    if not any(NOTE_LINK.search(item) for item in sources):
        raise ContentError(f"Quantity source must contain a note link: {source_path}")


def quantity_label(metadata: dict[str, object]) -> str:
    value = metadata.get("value", 0)
    number = str(value)
    if isinstance(value, float) and value.is_integer() and value != 0:
        number = str(int(value))
    unit = metadata.get("unit")
    return f"{number} {unit.strip()}" if isinstance(unit, str) else number


def _validate_query_references(query, owner, notes, vault_root, reference_index, seen):
    from obs_html_interim.cards import validate_count_query

    validate_count_query(query, owner.source_path)
    if owner.source_path in seen:
        raise ContentError(f"Quantity query reference cycle: {owner.source_path}")
    if "from" not in query:
        return
    identity = query["from"]
    parts = identity.split("/")
    if identity.endswith(".md") or any(part in {"", ".", ".."} for part in parts):
        raise ContentError(f"Invalid Quantity query owner: {identity}")
    path = vault_root.joinpath(*PurePosixPath(f"{identity}.md").parts).resolve()
    if not path.is_relative_to(vault_root.resolve()) or not path.is_file():
        raise ContentError(f"Quantity query owner not found: {identity}")
    upstream = replace(owner, source_path=path)
    metadata = reference_index.metadata_by_path.get(path) if reference_index else None
    if metadata is None:
        metadata, _ = _split_frontmatter(upstream.source_path.read_text(encoding="utf-8-sig"),
                                         upstream.source_path)
    if "query" not in metadata:
        raise ContentError(f"Quantity query reference requires a query owner: {query['from']}")
    _validate_query_references(metadata["query"], upstream, notes, vault_root,
                               reference_index, seen | {owner.source_path})


def _resolve_chapter_target(
    target: str, chapters: list[Chapter], vault_root: Path, current: Chapter | None = None,
    reference_index: NoteReferenceIndex | None = None,
) -> Chapter | None:
    relative_path = Path(target)
    if not relative_path.suffix:
        relative_path = relative_path.with_suffix(".md")
    lookup = reference_index.chapter_lookups.get(id(chapters)) if reference_index else None
    if lookup is None or lookup[0] is not chapters or lookup[1] != len(chapters):
        stems: dict[str, list[Chapter]] = {}
        for chapter in chapters:
            if not chapter.generated:
                stems.setdefault(chapter.source_path.stem.casefold(), []).append(chapter)
        lookup = (chapters, len(chapters), {chapter.source_path: chapter for chapter in chapters}, stems)
        if reference_index:
            reference_index.chapter_lookups[id(chapters)] = lookup
    _, _, by_path, stems = lookup
    roots = [current.source_path.parent, vault_root] if current else [vault_root]
    resolved_vault = _resolved(vault_root, reference_index)
    for root in roots:
        candidate = _resolved(root / relative_path, reference_index)
        if not candidate.is_relative_to(resolved_vault):
            raise ContentError(f"Note reference escapes the vault: {target}")
        if candidate in by_path:
            return by_path[candidate]
    matches = list(stems.get(relative_path.stem.casefold(), ()))
    if not matches and reference_index:
        matches = list(reference_index.aliases.get(target.casefold(), ()))
    elif not matches:
        for chapter in chapters:
            if chapter.generated:
                continue
            metadata, _ = _split_frontmatter(
                chapter.source_path.read_text(encoding="utf-8-sig"), chapter.source_path
            )
            if target.casefold() in {alias.casefold() for alias in _note_aliases(metadata, chapter.source_path)}:
                matches.append(chapter)
    if len(matches) > 1:
        raise ContentError(f"Ambiguous note name or alias: {target}")
    return matches[0] if matches else None


def _decorate_markers(
    tokens: list[Token], chapter_slug: str, bordered_tags: Sequence[str] = ()
) -> None:
    cards: list[tuple[int, str]] = []
    for index, token in enumerate(tokens):
        if token.type != "inline" or index == 0 or tokens[index - 1].type != "paragraph_open":
            continue
        paragraph_markers = _paragraph_markers(token)
        if not paragraph_markers:
            continue
        literals = [item[2] for item in paragraph_markers]
        visible = _remove_markers(token.content, literals)
        token.content = visible
        for child in token.children or []:
            if child.type == "text" and not child.meta.get("mark_reference"):
                child.content = _remove_markers(child.content, literals, normalize=False)
        paragraph = tokens[index - 1]
        kinds = [item[0] for item in paragraph_markers]
        labels = [item[1] for item in paragraph_markers]
        classes = " ".join(f"semantic-mark--{kind.replace('_', '-')}" for kind in kinds)
        paragraph.attrSet("class", f"semantic-mark {classes}")
        paragraph.attrSet("data-mark-kind", " ".join(kinds))
        paragraph.attrSet("data-mark-label", " ".join(labels))
        paragraph.attrSet("id", _marker_anchor(chapter_slug, kinds[0], labels[0]))
        opening = Token("html_inline", "", 0)
        opening.content = '<span class="semantic-mark-content">'
        closing = Token("html_inline", "", 0)
        closing.content = "</span>"
        rail = Token("html_inline", "", 0)
        rail.content = _render_mark_rail(paragraph_markers)
        token.children = [opening, *(token.children or []), closing, rail]
        bordered_kinds = list(dict.fromkeys(kind for kind in kinds if kind in bordered_tags))
        if bordered_kinds:
            title = " / ".join(kind.replace("_", " ").title() for kind in bordered_kinds)
            cards.append((index, title))

    for index, title in reversed(cards):
        card_open = Token("html_block", "", 0)
        card_open.content = (
            '<section class="content-card">'
            f'<header class="content-card-title">{escape(title)}</header>\n'
        )
        card_close = Token("html_block", "", 0)
        card_close.content = "</section>\n"
        tokens.insert(index + 2, card_close)
        tokens.insert(index - 1, card_open)


def _render_mark_rail(markers: list[tuple[str, str, str]]) -> str:
    from obs_html_interim.semantic_assets import markup

    icons = []
    for kind, label, _ in markers:
        description = f"{kind.replace('_', ' ').title()}: {label.replace('_', ' ')}"
        icons.append(
            f'<a class="semantic-mark-icon semantic-mark-icon--{kind.replace("_", "-")}" '
            f'href="#tags" data-tag-kind="{escape(kind)}" data-tag-label="{escape(label)}" '
            f'aria-label="{escape(description)}">'
            f'{markup(f"mark.{kind}")}</a>'
        )
    return (
        '<span class="semantic-mark-rail" aria-label="Paragraph marks">'
        f'{"".join(icons)}</span>'
    )


def _paragraph_markers(
    token: object, source_path: Path | None = None
) -> list[tuple[str, str, str]]:
    markers: list[tuple[str, str, str]] = []
    for child in token.children or []:
        if child.type != "text" or child.meta.get("mark_reference"):
            continue
        for marker_like in MARKER_LIKE.finditer(child.content):
            literal = marker_like.group(0)
            match = MARKER.fullmatch(literal)
            if not match:
                location = f" in {source_path}" if source_path else ""
                raise ContentError(f"Malformed paragraph marker{location}: {literal}")
            markers.append((match["kind"], match["label"], literal))
    return markers


def _marker_anchor(chapter_slug: str, kind: str, label: str) -> str:
    return f"mark-{chapter_slug}-{kind.replace('_', '-')}-{label.replace('_', '-')}"


def _remove_markers(text: str, literals: list[str], normalize: bool = True) -> str:
    visible = text
    for literal in literals:
        visible = visible.replace(literal, "", 1)
    return " ".join(visible.split()) if normalize else re.sub(r"[ \t]{2,}", " ", visible)


def _assert_portable_references(rendered: str, source_path: Path) -> None:
    finder = _LocalReferenceFinder()
    finder.feed(rendered)
    if finder.references:
        references = ", ".join(sorted(set(finder.references)))
        raise ContentError(f"Local file references are not portable in {source_path}: {references}")


def _safe_load_yaml(source: str) -> object:
    """Parse with libyaml when available; the pure parser keeps its diagnostics on errors."""
    loader = getattr(yaml, "CSafeLoader", None)
    if loader is not None:
        try:
            return yaml.load(source, Loader=loader)
        except yaml.YAMLError:
            pass
    return yaml.safe_load(source)


def _split_frontmatter(source: str, source_path: Path) -> tuple[dict[str, object], str]:
    lines = source.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, source
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() in {"---", "..."}:
            yaml_source = "".join(lines[1:index])
            try:
                loaded = _safe_load_yaml(yaml_source)
            except yaml.YAMLError as error:
                raise ContentError(f"Invalid frontmatter in {source_path}: {error}") from error
            if loaded is None:
                return {}, "".join(lines[index + 1 :])
            if not isinstance(loaded, dict):
                raise ContentError(f"Frontmatter must be a mapping: {source_path}")
            frontmatter = _normalize_mapping(loaded, source_path)
            if "obsHtml" in frontmatter:
                _validate_note_profile(frontmatter["obsHtml"], source_path)
            return frontmatter, "".join(lines[index + 1 :])
    raise ContentError(f"Frontmatter is not closed: {source_path}")


_VALID_NOTE_PROFILES: set[str] = set()


def _validate_note_profile(profile: object, source_path: Path) -> None:
    # Generated vaults repeat the same profile on every note; validity is a pure function of the
    # normalized JSON value, so each distinct profile is validated once.
    key = json.dumps(profile, sort_keys=True)
    if key in _VALID_NOTE_PROFILES:
        return
    if isinstance(profile, dict) and "macros" in profile:
        raise ContentError(
            f"obsHtml.macros was removed in {source_path}: embed register views from a .base file, "
            "for example ![[registers.base#Glossary]] (input-model, Registers)."
        )
    errors = list(NOTE_PROFILE_VALIDATOR.iter_errors(profile))
    if errors:
        removed = errors[0].schema.get("removed") if isinstance(errors[0].schema, dict) else None
        if removed:
            raise ContentError(
                f"obsHtml.{errors[0].path[-1]} was removed in {source_path}: {removed}"
            )
        raise ContentError(str(schema_error(errors, source_path, "capabilities/profiles", field="obsHtml")))
    _VALID_NOTE_PROFILES.add(key)


def _normalize_mapping(value: dict[object, object], source_path: Path) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ContentError(f"Frontmatter field names must be strings: {source_path}")
        normalized[key] = _normalize_frontmatter_value(item, source_path)
    return normalized


def _normalize_frontmatter_value(value: object, source_path: Path) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ContentError(f"Frontmatter numbers must be finite: {source_path}")
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, list):
        return [_normalize_frontmatter_value(item, source_path) for item in value]
    if isinstance(value, dict):
        return _normalize_mapping(value, source_path)
    raise ContentError(f"Frontmatter contains an unsupported YAML value: {source_path}")


def _unique_slug(value: str, seen: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "chapter"
    slug = base
    suffix = 2
    while slug in seen:
        slug = f"{base}-{suffix}"
        suffix += 1
    seen.add(slug)
    return slug
