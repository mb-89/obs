"""Parse a Markdown vault into the neutral Document data model."""
from __future__ import annotations

from dataclasses import dataclass, field
import mimetypes
import json
from pathlib import Path
import re

from markdown_it import MarkdownIt
from markdown_it.token import Token
import yaml

from obs.config import CoreConfig, CoreConfigError, load_core_config
from obs.figure import FigureDescriptorError, validate_figure_descriptor
from obs.input import (
    InputError,
    parse_callout,
    parse_card_spec,
    parse_property_editor,
    validate_base_definition,
    validate_command,
    validate_count_query,
    validate_note_profile,
    validate_project_config,
)
from obs.selection import IGNORED, base_selects, conditions_select, note_marks


_MANIFEST_ITEM = re.compile(
    r"^(?P<indent> *)[-*+] \[\[(?P<target>[^\]|#]+)(?:\|(?P<label>[^\]]+))?\]\]$"
)
_WIKILINK = re.compile(
    r"(?<!!)\[\[(?P<target>[^\]|#]+)(?:#(?P<heading>[^\]|]+))?(?:\|(?P<label>[^\]]+))?\]\]"
)
_EMBED = re.compile(r"!\[\[(?P<target>[^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
_QUOTE_PREFIX = re.compile(r"^ {0,3}> ?")
"""One level of blockquote prefix; a callout body is its blockquote's lines without it."""
_MARK = re.compile(r"#mark/(?P<category>[a-z_]+)/(?P<id>[a-z0-9_]+)")
_SEMANTIC = re.compile(
    r"(?P<embed>!)?\[\[(?P<target>[^\]|#]+)(?:#(?P<heading>[^\]|]+))?"
    r"(?:\|(?P<label>[^\]]+))?\]\]|#mark/(?P<category>[a-z_]+)/(?P<id>[a-z0-9_]+)"
)


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

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


class VaultError(ValueError):
    """Raised when vault input violates the neutral parsing contract."""


def build_document(
    manifest_path: Path, capability_ids: set[str] | None = None,
    configuration_path: Path | None = None,
) -> dict[str, object]:
    """Build semantic Document data from a manifest and its linked chapters."""
    try:
        configuration: CoreConfig | None = (
            load_core_config(configuration_path) if configuration_path is not None else None
        )
    except CoreConfigError as error:
        raise VaultError(str(error)) from error
    manifest_path = manifest_path.resolve()
    vault_root = manifest_path.parent
    metadata, body = _read_note(manifest_path)
    title = metadata.get("title", manifest_path.stem.replace("-", " ").title())
    if not isinstance(title, str) or not title.strip():
        raise VaultError("Manifest title must be a non-empty string.")
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
    chapters, abstract = _parse_manifest(body, manifest_path, vault_root, vault.identities)
    links: list[dict[str, str]] = []
    assets: list[dict[str, str]] = []
    link_ids: set[str] = set()
    asset_ids: set[str] = set()
    capabilities: set[str] = set()
    included: set[Path] = {manifest_path}

    def parse_chapter(chapter: dict[str, object]) -> None:
        path = chapter.pop("_path")
        included.add(path)
        chapter_metadata, chapter_body = vault.notes.get(path) or _read_note(path)
        _metadata_links(chapter_metadata, path, vault)
        _query_selection(chapter_metadata.get("query"), path, vault)
        chapter["metadata"] = _json_value(chapter_metadata)
        content = _frontmatter_nodes(
            chapter_metadata, capability_ids or set(), capabilities,
        )
        if "chapter-inclusion" in (capability_ids or set()):
            content.append({
                "type": "chapter-inclusion", "attrs": {"id": chapter["id"]}, "children": [],
            })
            capabilities.add("chapter-inclusion")
        parsed = _nodes(
            chapter_body, path, vault, links, assets, link_ids, asset_ids,
            capability_ids or set(), capabilities,
        )
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
    abstract_nodes = _nodes(
        body[abstract:], manifest_path, vault, links, assets, link_ids, asset_ids,
        capability_ids or set(), capabilities,
    )
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
    for attrs, target in vault.links:
        attrs["chapter"] = HOME if target == manifest_path else vault.identities.get(target)
    manifest_nodes = _frontmatter_nodes(metadata, capability_ids or set(), capabilities)
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
            "metadata": _json_value(metadata),
            "abstract": manifest_nodes,
        },
        "chapters": chapters,
        "links": links,
        "assets": assets,
        "records": [
            {"id": vault.identities[path], "type": "note", "path": vault.relative(path),
             "fields": _json_value(note_metadata), **({IGNORED: True} if note_metadata.get(IGNORED) else {})}
            for path, (note_metadata, _) in vault.notes.items()
        ],
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
        notes[source_path] = (metadata, body) if source_path == manifest_path else _read_note(source_path)
        identities[source_path] = _unique_identifier(relative.with_suffix("").as_posix(), used)
    return _Vault(vault_root, manifest_path, notes, identities)


def _unlisted_chapter(path: Path, vault: _Vault) -> dict[str, object]:
    """An included note the manifest does not list; see input-model "Chapter content"."""
    metadata, body = vault.notes[path]
    heading = next((line[2:].strip() for line in body.splitlines() if line.startswith("# ")), None)
    title = metadata.get("title") or metadata.get("term") or heading or path.stem.replace("-", " ").title()
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


def _base_selection(definition: object, source_path: Path, vault: _Vault, place: str) -> None:
    """Include the notes a Base definition selects."""
    if not isinstance(definition, dict):
        return
    try:
        selects = base_selects(definition)
    except InputError as error:
        raise VaultError(
            f"{error} ({place} in {vault.relative(source_path)}); "
            "use the Bases filter grammar of generic-tables."
        ) from error
    _select(lambda fields, path, _body: selects(fields, path), vault)


def _read_note(path: Path) -> tuple[dict[str, object], str]:
    try:
        source = path.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise VaultError(f"Cannot read note {path}: {error}") from error
    return _split_frontmatter(source, path)


def _split_frontmatter(source: str, path: Path) -> tuple[dict[str, object], str]:
    if not source.startswith("---\n"):
        return {}, source
    closing = source.find("\n---", 4)
    if closing < 0:
        raise VaultError(f"Frontmatter is not closed: {path}")
    try:
        metadata = yaml.safe_load(source[4:closing])
    except yaml.YAMLError as error:
        raise VaultError(f"Invalid frontmatter in {path}: {error}") from error
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise VaultError(f"Frontmatter must be a mapping: {path}")
    if not isinstance(metadata.get(IGNORED, False), bool):
        raise VaultError(
            f"Frontmatter field {IGNORED} must be true or false in {path}: "
            f"{metadata[IGNORED]!r}; write {IGNORED}: true to keep queries and Bases from "
            f"selecting the note, or remove the field."
        )
    try:
        profile = metadata.get("obsHtml")
        if profile is not None:
            validate_note_profile(profile, path)
        if "query" in metadata:
            validate_count_query(metadata["query"])
    except InputError as error:
        raise VaultError(str(error)) from error
    body_start = closing + 4
    if source[body_start:body_start + 1] == "\n":
        body_start += 1
    return metadata, source[body_start:]


def _parse_manifest(
    body: str, manifest_path: Path, vault_root: Path, identities: dict[Path, str],
) -> tuple[list[dict[str, object]], int]:
    lines = body.splitlines(keepends=True)
    chapters: list[dict[str, object]] = []
    parents: list[dict[str, object]] = []
    seen: set[Path] = set()
    abstract_start = 0
    found = False
    for index, line in enumerate(lines):
        if not line.strip():
            if found:
                abstract_start = sum(len(item) for item in lines[:index + 1])
                break
            continue
        match = _MANIFEST_ITEM.fullmatch(line.rstrip("\r\n"))
        if match is None:
            if not found:
                return [], 0
            abstract_start = sum(len(item) for item in lines[:index])
            break
        found = True
        depth = len(match["indent"]) // 2
        if len(match["indent"]) % 2:
            raise VaultError(f"Manifest line {index + 1} must use two-space indentation.")
        if depth > len(parents):
            raise VaultError(f"Manifest line {index + 1} skips a nesting level.")
        target = match["target"].strip()
        relative = Path(target)
        if relative.is_absolute() or ".." in relative.parts:
            raise VaultError(f"Manifest line {index + 1} escapes the vault.")
        if not relative.suffix:
            relative = relative.with_suffix(".md")
        if relative.suffix.lower() != ".md":
            raise VaultError(f"Manifest line {index + 1} must link to a Markdown note.")
        path = (vault_root / relative).resolve()
        if not path.is_relative_to(vault_root) or path == manifest_path or not path.is_file():
            raise VaultError(f"Manifest target does not resolve: {target}")
        if path in seen:
            raise VaultError(f"Manifest target is duplicated: {target}")
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
            raise VaultError(f"Manifest line {index + 1} has an empty chapter title.")
        if depth == 0:
            chapters.append(chapter)
        else:
            parents[depth - 1]["children"].append(chapter)
        parents[depth:] = [chapter]
    else:
        abstract_start = len(body)
    return chapters, abstract_start


def _frontmatter_nodes(
    metadata: dict[str, object], capability_ids: set[str], capabilities: set[str],
) -> list[dict[str, object]]:
    nodes: list[dict[str, object]] = []

    def add(identifier: str, attrs: dict[str, object]) -> None:
        if identifier in capability_ids:
            nodes.append({"type": identifier, "attrs": attrs, "children": []})
            capabilities.add(identifier)

    if metadata:
        add("markdown-frontmatter", {"metadata": _json_value(metadata)})
    if "obsHtml" in metadata:
        add("profiles", {"profile": _json_value(metadata["obsHtml"])})
    if metadata.get("kind") == "quantity":
        add("quantities", {"metadata": _json_value(metadata)})
    if "query" in metadata:
        query = _json_value(metadata["query"])
        add("queries", {"query": query})
        add("count-query", {"query": query})
    if metadata.get("kind") in {"glossary", "reference"} or "reference" in metadata:
        add("references", {"metadata": _json_value(metadata)})
    return nodes


def _nodes(
    source: str, source_path: Path, vault: _Vault, links: list[dict[str, str]],
    assets: list[dict[str, str]], link_ids: set[str], asset_ids: set[str],
    capability_ids: set[str], capabilities: set[str],
) -> list[dict[str, object]]:
    tokens = MarkdownIt("commonmark", {"html": False, "linkify": False}).parse(source)
    result: list[dict[str, object]] = []
    position = 0
    base_fences = 0
    while position < len(tokens):
        token = tokens[position]
        if token.type == "heading_open" and position + 1 < len(tokens):
            result.append({
                "type": "section", "attrs": {"level": int(token.tag[1:])},
                "children": _inline_nodes(tokens[position + 1], source_path, vault, links, assets, link_ids, asset_ids, capability_ids, capabilities),
            })
            position += 3
        elif token.type == "paragraph_open" and position + 1 < len(tokens):
            result.append({
                "type": "paragraph", "attrs": {},
                "children": _inline_nodes(tokens[position + 1], source_path, vault, links, assets, link_ids, asset_ids, capability_ids, capabilities),
            })
            position += 3
        elif token.type in {"bullet_list_open", "ordered_list_open"}:
            node, position = _list_node(
                tokens, position, source_path, vault, links, assets, link_ids, asset_ids, capability_ids, capabilities,
            )
            result.append(node)
        elif token.type == "fence":
            info = token.info.strip().split()
            language = info[0] if info else ""
            silent_command = info == ["cmd", "silent"]
            figure_descriptor: dict[str, object] | None = None
            try:
                if language == "base":
                    specification = yaml.safe_load(token.content)
                    validate_base_definition(specification, source_path)
                    base_fences += 1
                    _base_selection(specification, source_path, vault, f"base fence {base_fences}")
                elif language == "cards":
                    specification = parse_card_spec(token.content)
                    card_bodies = []
                    body_capabilities: set[str] = set()
                    for card in specification["cards"]:
                        for metric in card.get("metrics", []):
                            _query_selection(metric, source_path, vault)
                        card_bodies.append({"type": "document", "attrs": {}, "children": _nodes(
                            card["body"], source_path, vault, links, assets, link_ids, asset_ids,
                            capability_ids, body_capabilities,
                        )})
                elif language == "property-editor":
                    parse_property_editor(token.content, source_path)
                elif language == "cmd":
                    validate_command(token.content)
                elif language == "figure":
                    try:
                        figure_descriptor = json.loads(token.content)
                    except json.JSONDecodeError:
                        figure_descriptor = None
                    if figure_descriptor is not None:
                        if not isinstance(figure_descriptor, dict):
                            raise FigureDescriptorError("Figure descriptor must be an object.")
                        validate_figure_descriptor(figure_descriptor)
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
            if fence_type in capability_ids:
                attrs: dict[str, object] = {"source": token.content}
                if silent_command:
                    attrs["silent"] = True
                if language == "figure" and figure_descriptor is not None:
                    attrs = {"descriptor": figure_descriptor}
                elif language in {"base", "figure"}:
                    try:
                        spec = yaml.safe_load(token.content)
                    except yaml.YAMLError as error:
                        raise VaultError(f"Invalid {language} fence in {source_path}: {error}") from error
                    if spec is not None:
                        attrs["spec"] = _json_value(spec)
                elif language == "cards":
                    attrs["spec"] = _json_value(specification)
                    capabilities.update(body_capabilities)
                result.append({
                    "type": fence_type, "attrs": attrs,
                    "children": card_bodies if language == "cards" else [],
                })
                capabilities.add(fence_type)
            else:
                result.append({
                    "type": "code", "attrs": {"language": language},
                    "children": [], "text": token.content,
                })
            position += 1
        elif token.type == "blockquote_open" and position + 2 < len(tokens):
            inline = next((item for item in tokens[position:] if item.type == "inline"), None)
            lines = inline.content.splitlines() if inline else []
            callout = parse_callout(lines[0].strip()) if lines else None
            if callout and "callouts" in capability_ids:
                closing = next(
                    index for index in range(position + 1, len(tokens))
                    if tokens[index].type == "blockquote_close" and tokens[index].level == token.level
                )
                start, end = token.map
                body = [_QUOTE_PREFIX.sub("", line, count=1) for line in source.splitlines()[start:end]]
                result.append({
                    "type": "callouts",
                    "attrs": {"kind": callout["type"], "title": callout["title"]},
                    "children": _nodes(
                        "\n".join(body[1:]), source_path, vault, links, assets, link_ids, asset_ids,
                        capability_ids, capabilities,
                    ),
                })
                capabilities.add("callouts")
                position = closing + 1
            else:
                position += 1
        else:
            position += 1
    return result


def _list_node(
    tokens: list[Token], position: int, source_path: Path, vault: _Vault,
    links: list[dict[str, str]], assets: list[dict[str, str]], link_ids: set[str], asset_ids: set[str],
    capability_ids: set[str], capabilities: set[str],
) -> tuple[dict[str, object], int]:
    opening = tokens[position]
    items: list[dict[str, object]] = []
    position += 1
    while position < len(tokens) and tokens[position].type != opening.type.replace("_open", "_close"):
        if tokens[position].type != "list_item_open":
            position += 1
            continue
        position += 1
        children: list[dict[str, object]] = []
        while position < len(tokens) and tokens[position].type != "list_item_close":
            token = tokens[position]
            if token.type == "paragraph_open" and position + 1 < len(tokens):
                children.append({
                    "type": "paragraph", "attrs": {},
                    "children": _inline_nodes(tokens[position + 1], source_path, vault, links, assets, link_ids, asset_ids, capability_ids, capabilities),
                })
                position += 3
            elif token.type in {"bullet_list_open", "ordered_list_open"}:
                child, position = _list_node(
                    tokens, position, source_path, vault, links, assets, link_ids, asset_ids, capability_ids, capabilities,
                )
                children.append(child)
            else:
                position += 1
        items.append({"type": "list-item", "attrs": {}, "children": children})
        position += 1
    return {"type": "list", "attrs": {"ordered": opening.type == "ordered_list_open"}, "children": items}, position + 1


def _inline_nodes(
    token: Token, source_path: Path, vault: _Vault, links: list[dict[str, str]],
    assets: list[dict[str, str]], link_ids: set[str], asset_ids: set[str],
    capability_ids: set[str], capabilities: set[str],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    link: dict[str, str] | None = None
    children = token.children or []
    for index, child in enumerate(children):
        if child.type == "link_open":
            href = child.attrGet("href") or ""
            link = _resource(links, link_ids, _link_label(children[index + 1:]), href)
        elif child.type == "link_close":
            link = None
        elif child.type == "image":
            src = child.attrGet("src") or ""
            asset = _asset(assets, asset_ids, child.content or src, src)
            if "attachments" in capability_ids:
                result.append({
                    "type": "attachments", "attrs": {"asset": asset["id"], "label": child.content},
                    "children": [],
                })
                capabilities.add("attachments")
            else:
                result.append({"type": "text", "attrs": {"asset": asset["id"]}, "children": [], "text": child.content})
        elif child.type == "code_inline":
            result.append({"type": "code", "attrs": {}, "children": [], "text": child.content})
        elif child.type in {"text", "softbreak", "hardbreak"}:
            attrs = {"link": link["id"]} if link else {}
            text = "\n" if child.type != "text" else child.content
            if attrs:
                result.append({"type": "text", "attrs": attrs, "children": [], "text": text})
            else:
                result.extend(_semantic_text_nodes(
                    text, source_path, vault, links, link_ids, capability_ids, capabilities,
                ))
    return result


def _semantic_text_nodes(
    text: str, source_path: Path, vault: _Vault, links: list[dict[str, str]],
    link_ids: set[str], capability_ids: set[str], capabilities: set[str],
) -> list[dict[str, object]]:
    nodes: list[dict[str, object]] = []
    position = 0
    for match in _SEMANTIC.finditer(text):
        if match.start() > position:
            nodes.append({"type": "text", "attrs": {}, "children": [], "text": text[position:match.start()]})
        value = match.group(0)
        if match["embed"] and Path(match["target"].strip()).suffix == ".base" and "registers" in capability_ids:
            target = match["target"].strip()
            base_file = _link(target, source_path, vault)
            if base_file is not None:
                try:
                    definition = yaml.safe_load(base_file.read_text(encoding="utf-8-sig"))
                except (OSError, yaml.YAMLError) as error:
                    raise VaultError(
                        f"Cannot read the Base {target} embedded in {vault.relative(source_path)}: "
                        f"{error}; make the .base file valid YAML."
                    ) from error
                _base_selection(definition, source_path, vault, f"embedded {target}")
            nodes.append({
                "type": "registers",
                "attrs": {"target": target, "heading": match["heading"] or ""},
                "children": [],
            })
            capabilities.add("registers")
        elif match["embed"] and "embeds" in capability_ids:
            target = match["target"].strip()
            attrs = {"target": target, "chapter": None}
            vault.links.append((attrs, _link(target, source_path, vault)))
            nodes.append({"type": "embeds", "attrs": attrs, "children": []})
            capabilities.add("embeds")
        elif value.startswith("[[") and "wikilinks" in capability_ids:
            target = match["target"].strip()
            attrs = {"target": target, "chapter": None, "heading": match["heading"] or "", "label": match["label"] or target}
            vault.links.append((attrs, _link(target, source_path, vault)))
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


def _asset(
    assets: list[dict[str, str]], identifiers: set[str], label: str, href: str,
) -> dict[str, str]:
    existing = next((item for item in assets if item["href"] == href), None)
    if existing is not None:
        return existing
    asset = {
        "id": _unique_identifier(label or href, identifiers),
        "href": href,
        "mediaType": mimetypes.guess_type(href)[0] or "application/octet-stream",
    }
    assets.append(asset)
    return asset


def _link(target: str, source_path: Path, vault: _Vault) -> Path | None:
    """Resolve a link target and include a reached note; warn for a missing note.

    Resolution follows input-model ("Remaining chapter content"): source-relative path,
    vault-relative path, unique note name, then alias.
    """
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
        if relative.suffix == ".md" and len(relative.parts) == 1:
            name = relative.stem.casefold()
            matches = [note for note in vault.notes if note != vault.manifest and note.stem.casefold() == name]
            if not matches:
                matches = [
                    note for note, (metadata, _) in vault.notes.items()
                    if note != vault.manifest and name in _aliases(metadata)
                ]
            if len(matches) > 1:
                raise VaultError(
                    f"Ambiguous note name in {source}: [[{target}]] matches "
                    f"{', '.join(vault.relative(note) for note in matches)}; link the vault path instead."
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
