"""The links a figure's SVG holds, as written; src/obs/vault.py resolves each like a prose link.

Reader: whoever changes which links the core reads in a figure (capabilities/wikilinks, Links
inside a figure).

A figure's SVG is the body's ``svg`` (an ``svg``, ``mermaid`` or ``plantuml`` figure) or the
decoded ``data`` of an SVG ``image``. Its links are each ``a`` element's ``href`` or
``xlink:href`` that names no URL scheme and no fragment of the drawing itself, and the text of
every element but ``style``, ``script``, ``title``, ``desc`` and ``metadata``, in which the
caller finds wikilink text. Mermaid's ``click`` and PlantUML's ``[[...]]`` draw ``a`` elements,
so a diagram's links are read the same way.
"""
from __future__ import annotations

import base64
import re
from typing import Iterator
from xml.etree import ElementTree

SVG = "http://www.w3.org/2000/svg"
XLINK = "http://www.w3.org/1999/xlink"
HREFS = ("href", f"{{{XLINK}}}href")
"""The attributes an ``a`` element names its target in; ``href`` wins where both are given."""
TEXTLESS = frozenset({"style", "script", "title", "desc", "metadata"})
"""Elements whose text is no drawn text, so no wikilink is read there."""
_EXTERNAL = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|//|#)")
"""An href with a URL scheme, a network path or only a fragment: not a vault note."""


def figure_svg(body: dict[str, object]) -> str | None:
    """The SVG markup of a figure body, or None for a kind that draws no SVG."""
    if isinstance(body.get("svg"), str):
        return body["svg"]
    if body.get("mediaType") == "image/svg+xml":
        return base64.b64decode(body["data"]).decode("utf-8")
    return None


def local_name(element: ElementTree.Element) -> str:
    return element.tag.rpartition("}")[2] if isinstance(element.tag, str) else ""


def element_href(element: ElementTree.Element) -> str | None:
    """An ``a`` element's target as written, or None."""
    if local_name(element) != "a":
        return None
    return next((element.get(name) for name in HREFS if element.get(name)), None)


def links(svg: str) -> Iterator[tuple[str, str]]:
    """Each place in document order: ``("href", value)`` for an ``a`` element's vault target and
    ``("text", text)`` for a text run, where wikilinks may be written."""
    root = ElementTree.fromstring(svg)

    def walk(element: ElementTree.Element) -> Iterator[tuple[str, str]]:
        textless = local_name(element) in TEXTLESS
        href = element_href(element)
        if href and not _EXTERNAL.match(href.strip()):
            yield "href", href
        if element.text and not textless:
            yield "text", element.text
        for child in element:
            yield from walk(child)
            if child.tail and not textless:
                yield "text", child.tail

    yield from walk(root)
