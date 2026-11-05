"""Render a JSON Document as one portable HTML file.

The Document is the only input: no vault, no core package. Each capability this adapter
renders registers one node renderer in ``CAPABILITIES``; ``adapter.json`` declares the same
identifiers.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html import escape
from typing import Callable

from obs_html.config import Config, paper
from obs_html.timings import stage


STRUCTURAL = {"document", "section", "paragraph", "text", "list", "list-item", "code"}
DEFAULT_PAGES = ({"page": "cover"}, {"page": "abstract", "title": "Abstract"},
                 {"page": "contents", "title": "Contents"})
COVER_FIELDS = ("authors", "reviewers", "approvers", "sap number", "legal entity")
STYLE = """
body{font-family:system-ui,sans-serif;line-height:1.5;margin:0 auto;max-width:48rem;padding:1rem}
pre{white-space:pre-wrap;overflow-wrap:anywhere}
table{border-collapse:collapse}th,td{border:1px solid currentColor;padding:.2rem .4rem;text-align:left}
.mark{font-size:.8em;opacity:.7}.unresolved{text-decoration:underline dotted}
@media print{body{max-width:none;padding:0}.front-page,.chapter{break-before:page}}
"""


class RenderError(ValueError):
    """Raised when a Document cannot be rendered."""


@dataclass
class Context:
    document: dict[str, object]
    command_runner: Callable[[str], str] | None
    chapter: str = ""
    links: dict[str, dict[str, str]] = field(default_factory=dict)
    assets: dict[str, dict[str, str]] = field(default_factory=dict)
    chapters: dict[str, str] = field(default_factory=dict)
    headings: dict[str, str] = field(default_factory=dict)


Renderer = Callable[[dict[str, object], Context], str]


def _nothing(_node: dict[str, object], _context: Context) -> str:
    """A marker or data-only node: it states the source used the capability, nothing to show."""
    return ""


def _frontmatter(node: dict[str, object], context: Context) -> str:
    if not context.chapter:
        return ""  # The cover owns the manifest's metadata.
    rows = "".join(f"<dt>{escape(key)}</dt><dd>{escape(value)}</dd>"
                   for key, value in _flatten(node["attrs"]["metadata"]))
    return f'<dl class="properties">{rows}</dl>\n' if rows else ""


def _wikilink(node: dict[str, object], context: Context) -> str:
    attrs = node["attrs"]
    label = escape(attrs["label"])
    chapter = _resolve_chapter(attrs["target"], context)
    if chapter is None:
        return f'<span class="unresolved" title="{escape(attrs["target"], quote=True)}">{label}</span>'
    anchor = context.headings.get(f"{chapter}#{_identifier(attrs['heading'])}", chapter) \
        if attrs["heading"] else chapter
    return f'<a class="internal-link" href="#{anchor}">{label}</a>'


def _mark(node: dict[str, object], _context: Context) -> str:
    category, identifier = (escape(node["attrs"][key], quote=True) for key in ("category", "id"))
    return (f'<span class="mark" data-mark-category="{category}" data-mark-id="{identifier}">'
            f'#mark/{category}/{identifier}</span>')


def _command(node: dict[str, object], context: Context) -> str:
    if node["attrs"].get("silent"):
        return ""
    if context.command_runner is None:
        raise RenderError("A command fence requires explicit command execution authorization "
                          "(--execute-commands).")
    output = context.command_runner(node["attrs"]["source"].strip())
    return f'<pre class="command-output">{escape(output)}</pre>\n'


def _base(node: dict[str, object], context: Context) -> str:
    spec = node["attrs"]["spec"]
    properties = spec.get("properties") or {}
    accept = _base_filter(spec.get("filters"))
    matching = [record for record in context.document["records"] if accept(record)]
    tables = []
    for view in spec.get("views") or []:
        if view.get("type") != "table":
            raise RenderError(f"Unsupported Base view type: {view.get('type')!r}.")
        records = list(matching)
        for key in reversed(view.get("sort") or []):
            records.sort(key=lambda record: _text(_record_value(record, key["property"])),
                         reverse=key.get("direction") == "DESC")
        columns = view.get("order") or []
        head = "".join(f"<th>{escape(_display_name(column, properties))}</th>" for column in columns)
        rows = "".join(
            "<tr>" + "".join(f"<td>{escape(_text(_record_value(record, column)))}</td>"
                             for column in columns) + "</tr>"
            for record in records
        )
        caption = f"<caption>{escape(view['name'])}</caption>" if view.get("name") else ""
        tables.append(f'<table class="base">{caption}<thead><tr>{head}</tr></thead>'
                      f"<tbody>{rows}</tbody></table>\n")
    return "".join(tables)


CAPABILITIES: dict[str, Renderer] = {
    "bases": _base,
    "chapter-inclusion": _nothing,
    "command-fences": _command,
    "manifest": _nothing,
    "markdown": _nothing,
    "markdown-frontmatter": _frontmatter,
    "marks": _mark,
    "profiles": _nothing,
    "queries": _nothing,
    "wikilinks": _wikilink,
}


@stage("render")
def render(document: dict[str, object], config: Config,
           command_runner: Callable[[str], str] | None = None) -> str:
    if document.get("schemaVersion") != 1:
        raise RenderError(f"Unsupported Document schema version: {document.get('schemaVersion')!r}.")
    unsupported = sorted(set(document["capabilities"]) - set(CAPABILITIES))
    if unsupported:
        raise RenderError(f"Document uses capabilities this adapter does not render: "
                          f"{', '.join(unsupported)}.")
    context = Context(
        document, command_runner,
        links={item["id"]: item for item in document["links"]},
        assets={item["id"]: item for item in document["assets"]},
    )
    _index(document["chapters"], context)
    manifest = document["manifest"]
    profile = next((node["attrs"]["profile"] for node in manifest.get("abstract", [])
                    if node["type"] == "profiles"), {})
    geometry = paper({**config.print_default, **(profile.get("print") or {})}, config)
    title = escape(manifest["title"])
    front = "".join(_front_page(page, manifest, context) for page in profile.get("pages", DEFAULT_PAGES))
    body = front + _chapters(document["chapters"], context, 1)
    layout = escape(str(profile.get("layout", "paged")), quote=True)
    return (
        "<!doctype html>\n"
        f'<html lang="en" data-layout="{layout}" data-report-status="ready">\n<head>\n'
        '<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{title}</title>\n<style>{STYLE}"
        f"@page{{size:{_mm(geometry['widthMillimeters'])} {_mm(geometry['heightMillimeters'])};"
        f"margin:{_mm(geometry['marginMillimeters'])}}}\n</style>\n</head>\n<body>\n{body}</body>\n</html>\n"
    )


def _front_page(page: dict[str, str], manifest: dict[str, object], context: Context) -> str:
    kind = page["page"]
    heading = f"<h1>{escape(page['title'])}</h1>\n" if page.get("title") else ""
    if kind == "cover":
        return f'<header class="front-page cover">{_cover(manifest)}</header>\n'
    if kind == "abstract":
        content = _nodes(manifest.get("abstract", []), context)
        return f'<section class="front-page abstract">{heading}{content}</section>\n' if content else ""
    if kind == "contents":
        return f'<nav class="front-page contents">{heading}{_contents(context.document["chapters"])}</nav>\n'
    raise RenderError(f"Unsupported front page: {kind!r}.")


def _cover(manifest: dict[str, object]) -> str:
    metadata = manifest["metadata"]
    parts = []
    product = metadata.get("product")
    if isinstance(product, dict):
        name = " ".join(_text(product[key]) for key in ("name", "version") if product.get(key))
        if name:
            parts.append(f'<p class="cover-product">{escape(name)}</p>')
    if metadata.get("organization"):
        parts.append(f'<p class="cover-organization">{escape(_text(metadata["organization"]))}</p>')
    parts.append(f'<h1 class="document-title">{escape(manifest["title"])}</h1>')
    for key, css in (("document type", "cover-type"), ("subtitle", "document-subtitle")):
        if metadata.get(key):
            parts.append(f'<p class="{css}">{escape(_text(metadata[key]))}</p>')
    facts = "".join(f"<dt>{escape(key.title())}</dt><dd>{escape(_text(metadata[key]))}</dd>"
                    for key in COVER_FIELDS if metadata.get(key))
    if facts:
        parts.append(f'<dl class="cover-facts">{facts}</dl>')
    parts.extend(f'<p class="cover-{key}">{escape(_text(metadata[key]))}</p>'
                 for key in ("copyright", "confidentiality") if metadata.get(key))
    return "".join(parts)


def _contents(chapters: list[dict[str, object]]) -> str:
    if not chapters:
        return ""
    items = "".join(
        f'<li><a href="#{chapter["id"]}">{escape(chapter["title"])}</a>{_contents(chapter["children"])}</li>'
        for chapter in chapters
    )
    return f"<ol>{items}</ol>"


def _chapters(chapters: list[dict[str, object]], context: Context, depth: int) -> str:
    rendered = []
    for chapter in chapters:
        context.chapter = chapter["id"]
        content = _nodes(chapter["content"], context)
        if not any(node["type"] == "section" for node in chapter["content"]):
            content = f"<h{min(depth, 6)}>{escape(chapter['title'])}</h{min(depth, 6)}>\n" + content
        children = _chapters(chapter["children"], context, depth + 1)
        rendered.append(f'<section class="chapter" id="{chapter["id"]}">\n{content}{children}</section>\n')
    context.chapter = ""
    return "".join(rendered)


def _nodes(nodes: list[dict[str, object]], context: Context) -> str:
    return "".join(_node(node, context) for node in nodes)


def _node(node: dict[str, object], context: Context) -> str:
    kind = node["type"]
    if kind in CAPABILITIES:
        return CAPABILITIES[kind](node, context)
    if kind not in STRUCTURAL:
        raise RenderError(f"Document node uses a capability this adapter does not render: {kind}.")
    inner = _nodes(node["children"], context)
    if kind == "text":
        return _text_node(node, context)
    if kind == "code":
        return f"<code>{escape(node.get('text', ''))}</code>"
    if kind == "paragraph":
        return f"<p>{inner}</p>\n"
    if kind == "section":
        level = min(max(int(node["attrs"].get("level", 1)), 1), 6)
        anchor = context.headings.get(f"{context.chapter}#{_identifier(_plain(node))}", "")
        identifier = f' id="{anchor}"' if anchor else ""
        return f"<h{level}{identifier}>{inner}</h{level}>\n"
    if kind == "list":
        tag = "ol" if node["attrs"].get("ordered") else "ul"
        return f"<{tag}>\n{inner}</{tag}>\n"
    if kind == "list-item":
        return f"<li>{inner}</li>\n"
    return f'<div class="document">{inner}</div>\n'


def _text_node(node: dict[str, object], context: Context) -> str:
    text = escape(node.get("text", ""))
    attrs = node["attrs"]
    if "link" in attrs:
        link = context.links.get(attrs["link"])
        if link is None:
            raise RenderError(f"Text links to an unknown link: {attrs['link']}.")
        return f'<a href="{escape(link["href"], quote=True)}">{text}</a>'
    if "asset" in attrs:
        asset = context.assets.get(attrs["asset"])
        if asset is None:
            raise RenderError(f"Text names an unknown asset: {attrs['asset']}.")
        return f'<img src="{escape(asset["href"], quote=True)}" alt="{escape(node.get("text", ""), quote=True)}">'
    return text


def _index(chapters: list[dict[str, object]], context: Context) -> None:
    """Record every chapter and heading anchor before rendering, so links can point forward."""
    for chapter in chapters:
        context.chapters[chapter["id"]] = chapter["title"]
        seen: set[str] = set()
        for node in chapter["content"]:
            if node["type"] == "section":
                slug = _identifier(_plain(node))
                if slug not in seen:
                    seen.add(slug)
                    context.headings[f"{chapter['id']}#{slug}"] = f"{chapter['id']}--{slug}"
        _index(chapter["children"], context)


def _resolve_chapter(target: str, context: Context) -> str | None:
    """Find the one chapter a link target names: its identifier, or a unique path suffix of it."""
    identifier = _identifier(target.removesuffix(".md"))
    if identifier in context.chapters:
        return identifier
    matches = [chapter for chapter in context.chapters if chapter.endswith(f"-{identifier}")]
    return matches[0] if len(matches) == 1 else None


def _base_filter(filters: object) -> Callable[[dict[str, object]], bool]:
    if filters is None:
        return lambda _record: True
    if isinstance(filters, str):
        match = re.fullmatch(r'\s*([\w.]+)\s*(==|!=)\s*("[^"]*"|null|true|false|-?[0-9]+(?:\.[0-9]+)?)\s*',
                             filters)
        if match is None:
            raise RenderError(f"Unsupported Base filter: {filters!r}.")
        name, operator, literal = match.groups()
        value = json.loads(literal)
        if operator == "==":
            return lambda record: _record_value(record, name) == value
        return lambda record: _record_value(record, name) != value
    if isinstance(filters, dict) and len(filters) == 1:
        (combinator, items), = filters.items()
        if combinator in {"and", "or"} and isinstance(items, list):
            parts = [_base_filter(item) for item in items]
            combine = all if combinator == "and" else any
            return lambda record: combine(part(record) for part in parts)
    raise RenderError(f"Unsupported Base filter: {filters!r}.")


def _record_value(record: dict[str, object], name: str) -> object:
    if name == "file.name":
        return record["id"]
    value: object = record["fields"]
    for part in name.removeprefix("note.").split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _display_name(column: str, properties: dict[str, object]) -> str:
    settings = properties.get(column)
    if isinstance(settings, dict) and settings.get("displayName"):
        return str(settings["displayName"])
    return column


def _flatten(value: object, prefix: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _flatten(item, f"{prefix}.{key}" if prefix else str(key))
    elif prefix:
        yield prefix, _text(value)


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(_text(item) for item in value)
    return str(value)


def _plain(node: dict[str, object]) -> str:
    return node.get("text", "") + "".join(
        _plain(child) if child["type"] != "wikilinks" else child["attrs"]["label"]
        for child in node["children"]
    )


def _identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _mm(value: float) -> str:
    return f"{value:g}mm"
