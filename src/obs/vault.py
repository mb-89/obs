"""Parse a Markdown vault into the neutral Document data model."""
from __future__ import annotations

import mimetypes
from pathlib import Path
import re
from typing import Iterator

from markdown_it import MarkdownIt
from markdown_it.token import Token
import yaml


_MANIFEST_ITEM = re.compile(
    r"^(?P<indent> *)[-*+] \[\[(?P<target>[^\]|#]+)(?:\|(?P<label>[^\]]+))?\]\]$"
)
_WIKILINK = re.compile(r"(?<!!)\[\[(?P<target>[^\]|#]+)(?:#[^\]|]+)?(?:\|(?P<label>[^\]]+))?\]\]")


class VaultError(ValueError):
    """Raised when vault input violates the neutral parsing contract."""


def build_document(
    manifest_path: Path, capability_ids: set[str] | None = None,
) -> dict[str, object]:
    """Build semantic Document data from a manifest and its linked chapters."""
    manifest_path = manifest_path.resolve()
    vault_root = manifest_path.parent
    metadata, body = _read_note(manifest_path)
    title = metadata.get("title", manifest_path.stem.replace("-", " ").title())
    if not isinstance(title, str) or not title.strip():
        raise VaultError("Manifest title must be a non-empty string.")
    chapters, abstract = _parse_manifest(body, manifest_path, vault_root)
    links: list[dict[str, str]] = []
    assets: list[dict[str, str]] = []
    link_ids: set[str] = set()
    asset_ids: set[str] = set()
    capabilities: set[str] = set()

    def parse_chapter(chapter: dict[str, object]) -> None:
        path = chapter.pop("_path")
        chapter_metadata, chapter_body = _read_note(path)
        chapter["metadata"] = _json_value(chapter_metadata)
        chapter["content"] = _nodes(
            chapter_body, path, vault_root, links, assets, link_ids, asset_ids,
        )
        chapter["content"].extend(_capability_nodes(chapter_body, capability_ids or set(), capabilities))
        for child in chapter["children"]:
            parse_chapter(child)

    for chapter in chapters:
        parse_chapter(chapter)
    return {
        "schemaVersion": 1,
        "manifest": {
            "title": title,
            "metadata": _json_value(metadata),
            "abstract": _nodes(body[abstract:], manifest_path, vault_root, links, assets, link_ids, asset_ids),
        },
        "chapters": chapters,
        "links": links,
        "assets": assets,
        "records": [],
        "semanticResources": [],
        "diagnostics": [],
        "capabilities": sorted(capabilities),
    }


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
    body_start = closing + 4
    if source[body_start:body_start + 1] == "\n":
        body_start += 1
    return metadata, source[body_start:]


def _parse_manifest(
    body: str, manifest_path: Path, vault_root: Path,
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
        chapter = {
            "id": _identifier(relative.with_suffix("").as_posix()),
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


def _nodes(
    source: str, source_path: Path, vault_root: Path, links: list[dict[str, str]],
    assets: list[dict[str, str]], link_ids: set[str], asset_ids: set[str],
) -> list[dict[str, object]]:
    tokens = MarkdownIt("commonmark", {"html": False, "linkify": False}).parse(source)
    result: list[dict[str, object]] = []
    position = 0
    while position < len(tokens):
        token = tokens[position]
        if token.type == "heading_open" and position + 1 < len(tokens):
            result.append({
                "type": "section", "attrs": {"level": int(token.tag[1:])},
                "children": _inline_nodes(tokens[position + 1], source_path, vault_root, links, assets, link_ids, asset_ids),
            })
            position += 3
        elif token.type == "paragraph_open" and position + 1 < len(tokens):
            result.append({
                "type": "paragraph", "attrs": {},
                "children": _inline_nodes(tokens[position + 1], source_path, vault_root, links, assets, link_ids, asset_ids),
            })
            position += 3
        elif token.type in {"bullet_list_open", "ordered_list_open"}:
            node, position = _list_node(
                tokens, position, source_path, vault_root, links, assets, link_ids, asset_ids,
            )
            result.append(node)
        elif token.type == "fence":
            result.append({
                "type": "code", "attrs": {"language": token.info.strip().split(maxsplit=1)[0]},
                "children": [], "text": token.content,
            })
            position += 1
        else:
            position += 1
    for match in _WIKILINK.finditer(source):
        target = match["target"].strip()
        _resolve_note(target, source_path, vault_root)
        _resource(links, link_ids, match["label"] or target, target)
    return result


def _list_node(
    tokens: list[Token], position: int, source_path: Path, vault_root: Path,
    links: list[dict[str, str]], assets: list[dict[str, str]], link_ids: set[str], asset_ids: set[str],
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
                    "children": _inline_nodes(tokens[position + 1], source_path, vault_root, links, assets, link_ids, asset_ids),
                })
                position += 3
            elif token.type in {"bullet_list_open", "ordered_list_open"}:
                child, position = _list_node(
                    tokens, position, source_path, vault_root, links, assets, link_ids, asset_ids,
                )
                children.append(child)
            else:
                position += 1
        items.append({"type": "list-item", "attrs": {}, "children": children})
        position += 1
    return {"type": "list", "attrs": {"ordered": opening.type == "ordered_list_open"}, "children": items}, position + 1


def _inline_nodes(
    token: Token, source_path: Path, vault_root: Path, links: list[dict[str, str]],
    assets: list[dict[str, str]], link_ids: set[str], asset_ids: set[str],
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
            result.append({"type": "text", "attrs": {"asset": asset["id"]}, "children": [], "text": child.content})
        elif child.type == "code_inline":
            result.append({"type": "code", "attrs": {}, "children": [], "text": child.content})
        elif child.type in {"text", "softbreak", "hardbreak"}:
            attrs = {"link": link["id"]} if link else {}
            text = "\n" if child.type != "text" else child.content
            result.append({"type": "text", "attrs": attrs, "children": [], "text": text})
    return result


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


def _resolve_note(target: str, source_path: Path, vault_root: Path) -> None:
    relative = Path(target)
    if relative.is_absolute() or ".." in relative.parts:
        raise VaultError(f"Link escapes the vault in {source_path}: {target}")
    if not relative.suffix:
        relative = relative.with_suffix(".md")
    path = (source_path.parent / relative).resolve()
    if not path.is_file() and len(relative.parts) == 1:
        matches = list(vault_root.rglob(relative.name))
        if len(matches) == 1:
            path = matches[0].resolve()
    if not path.is_relative_to(vault_root):
        raise VaultError(f"Link escapes the vault in {source_path}: {target}")


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


_CAPABILITY_PATTERNS = {
    "wikilinks": re.compile(r"(?<!!)\[\[[^\]]+\]\]"),
    "embeds": re.compile(r"!\[\[[^\]]+\]\]"),
    "callouts": re.compile(r"(?m)^>\s*\[![^\]]+\]"),
    "marks": re.compile(r"#mark/[a-z_]+/[a-z0-9_]+"),
    "bases": re.compile(r"(?m)^```base(?:\s|$)"),
    "figures": re.compile(r"(?m)^```figure(?:\s|$)"),
    "quantities": re.compile(r"(?m)^```quantity(?:\s|$)"),
    "command-fences": re.compile(r"(?m)^```cmd(?:\s|$)"),
}


def _capability_nodes(
    source: str, capability_ids: set[str], capabilities: set[str],
) -> list[dict[str, object]]:
    nodes = []
    for identifier, pattern in _CAPABILITY_PATTERNS.items():
        if identifier in capability_ids and (match := pattern.search(source)):
            capabilities.add(identifier)
            nodes.append({
                "type": identifier, "attrs": {"source": match.group(0)}, "children": [],
            })
    return nodes
