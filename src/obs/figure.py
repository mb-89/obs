"""The figure kinds and the language-neutral FigureDescriptor contract."""
import base64
from dataclasses import dataclass
from functools import cache
import json
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree

from jsonschema import Draft202012Validator

from obs import diagram
from obs.input import schema_error


FIGURE_SCHEMA_PATH = Path(__file__).with_name("figure.schema.json")
FIGURES, DESCRIPTOR = "capabilities/figures", "capabilities/figure-descriptor"
"""The notes owning a figure fence's and a FigureDescriptor's contracts."""


class FigureDescriptorError(ValueError):
    """Raised when a FigureDescriptor violates the neutral contract."""


def validate_figure_descriptor(
    descriptor: dict[str, object], source: object = "FigureDescriptor", place: str = "",
) -> None:
    error = schema_error(list(_figure_validator().iter_errors(descriptor)), source, DESCRIPTOR, place=place)
    if error:
        raise FigureDescriptorError(str(error))


def read_figure_descriptor(path: Path) -> dict[str, object]:
    try:
        descriptor = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FigureDescriptorError(f"Invalid FigureDescriptor {path}: {error}") from error
    if not isinstance(descriptor, dict):
        raise FigureDescriptorError(f"Invalid FigureDescriptor {path}.")
    validate_figure_descriptor(descriptor, path)
    return descriptor


def write_figure_descriptor(descriptor: dict[str, object], path: Path) -> None:
    validate_figure_descriptor(descriptor, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(descriptor, indent=2) + "\n", encoding="utf-8")


class FigureContentError(ValueError):
    """A figure's content its kind cannot read; ``field`` names it within the fence, ``line`` the
    content's 1-based line where the kind names one, and ``reference`` the note that owns the
    kind's contract where it is not capabilities/figures."""

    def __init__(self, field: str, problem: str, remedy: str, line: int | None = None,
                 reference: str | None = None) -> None:
        super().__init__(problem)
        self.field, self.problem, self.remedy, self.line, self.reference = field, problem, remedy, line, reference


Content = "bytes | object"
"""A figure's content: the bytes of its ``source`` file, or its inline ``content`` value."""


def _image(content: object, media_type: str | None) -> dict[str, object]:
    """An image: its file's bytes and media type, or inline SVG markup."""
    if isinstance(content, bytes):
        if not (media_type or "").startswith("image/"):
            raise FigureContentError("source", f"names a file of media type {media_type or 'unknown'}, "
                                     "not an image", "Name a raster image or an SVG file")
        return {"mediaType": media_type, "data": base64.b64encode(content).decode("ascii")}
    return {"mediaType": "image/svg+xml",
            "data": base64.b64encode(_svg_markup(content).encode("utf-8")).decode("ascii")}


def _svg_markup(content: object) -> str:
    """SVG markup: an ``svg`` root element, from a file's bytes or inline text."""
    field = "source" if isinstance(content, bytes) else "content"
    try:
        text = content.decode("utf-8") if isinstance(content, bytes) else content
        root = ElementTree.fromstring(text) if isinstance(text, str) else None
    except (UnicodeDecodeError, ElementTree.ParseError):
        root = None
    if root is None or root.tag != "{http://www.w3.org/2000/svg}svg":
        raise FigureContentError(field, "is not SVG markup with an svg root element",
                                 "Give SVG markup, such as <svg xmlns=\"http://www.w3.org/2000/svg\" ...>")
    return text


def _json(content: object) -> object:
    """A JSON file's value, or the inline YAML value as it is."""
    if not isinstance(content, bytes):
        return content
    try:
        return json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FigureContentError("source", f"is not JSON: {error}", "Write the file as JSON") from error


@cache
def _figure_validator(definition: str | None = None) -> Draft202012Validator:
    """figure.schema.json's validator: of the FigureDescriptor, or of one of its ``$defs``."""
    schema = json.loads(FIGURE_SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema if definition is None else {
        "$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": f"#/$defs/{definition}"})


def _checked(value: object, validator: Draft202012Validator, field: str, reference: str) -> None:
    """Raise the value's first schema failure, at ``field`` within the fence, its remedy naming
    ``reference``."""
    error = schema_error(list(validator.iter_errors(value)), "", reference, field=field)
    if error:
        message = str(error).removeprefix(": ")
        at, _, rest = message.partition(": ")
        raise FigureContentError(at, *rest.removesuffix(".").split(". ", 1))


def _sankey_nodes_exist(graph: dict[str, object], field: str, reference: str) -> None:
    """Refuse a link to a node the graph does not have, a cross-reference no schema states; the
    graph has passed ``$defs/sankeyGraph``."""
    ids = {node["id"] for node in graph["nodes"]}
    for index, link in enumerate(graph["links"]):
        for end in ("source", "target"):
            if link[end] not in ids:
                raise FigureContentError(
                    f"{field}.links[{index}].{end}", f"is {link[end]!r}, which is no node of the graph",
                    f"Name the id of one of the graph's nodes, or add a node with id {link[end]!r}; "
                    f"see {reference}")


def _sankey(content: object, _media_type: str | None) -> dict[str, object]:
    """A Sankey graph, inline or from its JSON file, static or a dynamic projection."""
    graph, field = _json(content), "source" if isinstance(content, bytes) else "content"
    _checked(graph, _figure_validator("sankeyGraph"), field, FIGURES)
    _sankey_nodes_exist(graph, field, FIGURES)
    return {"graph": graph}


def _descriptor(content: object, _media_type: str | None) -> dict[str, object]:
    descriptor, field = _json(content), "source" if isinstance(content, bytes) else "content"
    _checked(descriptor, _figure_validator(), field, DESCRIPTOR)
    if "sankey" in descriptor["data"]:
        _sankey_nodes_exist(descriptor["data"]["sankey"], f"{field}.data.sankey", DESCRIPTOR)
    return {"descriptor": descriptor}


def _diagram(kind: str) -> Callable[[object, "str | None"], dict[str, object]]:
    """A diagram language's figure body: its text, and the SVG drawn from it at build time."""

    def read(content: object, _media_type: str | None) -> dict[str, object]:
        field = "source" if isinstance(content, bytes) else "content"
        try:
            text = content.decode("utf-8") if isinstance(content, bytes) else content
        except UnicodeDecodeError as error:
            raise FigureContentError(field, "is not UTF-8 text", "Save the diagram file as UTF-8",
                                     reference=f"capabilities/{kind}") from error
        if not isinstance(text, str) or not text.strip():
            raise FigureContentError(field, f"is no {kind} diagram text", f"Write the diagram's {kind} text",
                                     reference=f"capabilities/{kind}")
        try:
            return {"source": text, "svg": diagram.render(kind, text)}
        except diagram.DiagramError as error:
            raise FigureContentError(field, error.problem, error.remedy, error.line,
                                     f"capabilities/{kind}") from error

    return read


@dataclass(frozen=True)
class FigureContext:
    """What a kind that resolves its content against the vault gets from the note it is in."""

    field: str
    """The fence field the content comes from: content, or source for a file."""
    quantity: Callable[[str], "tuple[str, dict[str, object]] | None"]
    """A link target's note: its vault-relative path and frontmatter, or None without a note."""
    line: Callable[[str], str]
    """Where text of the content stands, such as \"line 12\", or empty where it is not found."""


def _equations(content: object, media_type: str | None) -> dict[str, object]:
    from obs.equations import read  # SymPy loads only for an equation figure.
    return read(content, media_type)


def _equation_body(content: dict[str, object], context: FigureContext) -> dict[str, object]:
    from obs.equations import resolve
    return resolve(content, context)


@dataclass(frozen=True)
class FigureKind:
    """One kind of figure: how its content becomes its body (the figures node's one child).

    The body's schema is ``$defs/figureBodies/<kind>`` of document.schema.json; the kind's own
    fence options are copied into the body beside what ``read`` returns, so that schema checks them.
    """

    read: Callable[[object, "str | None"], dict[str, object]]
    """The body from the content and, for a source file, its media type."""
    capability: str | None = None
    """A capability whose contract the body carries, which a Document with the kind uses."""
    resolve: "Callable[[dict[str, object], FigureContext], dict[str, object]] | None" = None
    """The body from what ``read`` returned and the note's vault, for a kind whose content links notes."""
    fence: bool = False
    """Whether a plain fence of the kind's name (```` ```mermaid ````) is a figure of the kind,
    without caption, where the kind's capability is supported."""


FIGURE_KINDS: dict[str, FigureKind] = {
    "image": FigureKind(_image),
    "svg": FigureKind(lambda content, _type: {"svg": _svg_markup(content)}),
    "sankey": FigureKind(_sankey),
    "plot": FigureKind(_descriptor, "figure-descriptor"),
    "equations": FigureKind(_equations, "equation-figures", resolve=_equation_body),
    "mermaid": FigureKind(_diagram("mermaid"), "mermaid", fence=True),
    "plantuml": FigureKind(_diagram("plantuml"), "plantuml", fence=True),
}
"""The figure kinds; see input-model, Figure input direction. Adding a kind is one entry here and
one body schema in document.schema.json."""
