"""Template manifests, template nodes and filled documents (input-model#Templates).

A template manifest marks itself with ``obs.template``; each chapter that carries ``obs.guidance``
is a template node, its guidance a ``templates`` node apart from its one ``{{slot}}`` paragraph. A
note that carries ``derived_from``, or any note of a manifest that does, is filled: it holds no
guidance and no slot. capabilities/templates owns the Document nodes.
"""
from typing import Iterator

from obs.input import input_error, input_validator, schema_error


OWNER = "capabilities/templates"
SLOT = "{{slot}}"
GUIDANCE_TEXTS = ("contents", "motivation", "form", "sources")
"""The guidance's texts in the order its node's field children carry them."""

Node = dict[str, object]


def _profile(metadata: dict[str, object]) -> dict[str, object]:
    profile = metadata.get("obs")
    return profile if isinstance(profile, dict) else {}


def is_template(metadata: dict[str, object]) -> bool:
    """Whether a manifest's frontmatter marks it a template manifest."""
    return "template" in _profile(metadata)


def is_filled(metadata: dict[str, object]) -> bool:
    """Whether a note's frontmatter says it was filled from a template."""
    return "derived_from" in metadata


def guidance(metadata: dict[str, object]) -> dict[str, object] | None:
    """A note's ``obs.guidance``, or None for a note that is no template node."""
    return _profile(metadata).get("guidance")


def validate(metadata: dict[str, object], source_path: object, manifest: bool) -> None:
    """Check a note's template fields: ``obs.template`` on the ``manifest`` only, ``obs.guidance`` on a
    chapter only, each and ``derived_from`` against input.schema.json."""
    profile = _profile(metadata)
    if "template" in profile:
        if not manifest:
            raise input_error(source_path, "obs.template", "marks a template, which only a manifest marks",
                              f"Move obs.template into the manifest's frontmatter; see {OWNER}")
        _check("templateMark", profile["template"], source_path, "obs.template")
    if "guidance" in profile:
        if manifest:
            raise input_error(source_path, "obs.guidance", "is a template node's guidance, which a chapter of a "
                              "template manifest carries, not the manifest",
                              f"Move obs.guidance into the chapter note of its section; see {OWNER}")
        _check("templateGuidance", profile["guidance"], source_path, "obs.guidance")
    if "derived_from" in metadata:
        _check("derivedFrom", metadata["derived_from"], source_path, "derived_from")


def _check(definition: str, value: object, source_path: object, field: str) -> None:
    error = schema_error(list(input_validator(definition).iter_errors(value)), source_path, OWNER, field=field)
    if error:
        raise error


def frontmatter_attrs(metadata: dict[str, object]) -> list[dict[str, object]]:
    """The attrs of a note's frontmatter ``templates`` nodes: its template mark and its derived_from."""
    attrs: list[dict[str, object]] = []
    if "template" in _profile(metadata):
        attrs.append({"part": "template", **_profile(metadata)["template"]})
    if "derived_from" in metadata:
        attrs.append({"part": "derived-from", **metadata["derived_from"]})
    return attrs


def guidance_node(values: dict[str, object], fields: list[Node]) -> Node:
    """A template node's guidance, its ``fields`` one field node per text of ``values``."""
    return {"type": "templates", "attrs": {"part": "guidance", "gate": values["gate"]}, "children": fields}


def place_slot(nodes: list[Node], source_path: object) -> list[Node]:
    """``nodes`` with the template node's one ``{{slot}}`` paragraph as its ``slot`` node; a node with
    none, more, or a slot inside other text fails naming the note."""
    alone = [index for index, node in enumerate(nodes) if _is_slot(node)]
    held = sum(text.count(SLOT) for _, text in _texts(nodes, ""))
    if len(alone) != 1 or held != 1:
        raise input_error(source_path, "obs.guidance", f"is a template node's, whose body holds {held} "
                          f"{SLOT} with {len(alone)} as a paragraph of its own",
                          f"Write its fill slot once, as a paragraph of {SLOT} alone; see {OWNER}")
    [index] = alone
    return [*nodes[:index], {"type": "templates", "attrs": {"part": "slot"}, "children": []}, *nodes[index + 1:]]


def refuse_guidance(metadata: dict[str, object], source_path: object) -> None:
    """A note of a document that is no template carries no guidance, so none renders into it."""
    if guidance(metadata) is not None:
        raise input_error(source_path, "obs.guidance", "is a template node's guidance, which renders only in "
                          "its template manifest, and this document is none",
                          f"Keep the guidance in the template and remove obs.guidance here; see {OWNER}")


def refuse_slots(nodes: list[Node], source_path: object, title: str) -> None:
    """A filled note's text holds no ``{{slot}}``; one fails naming the note and its section, the
    heading above it or, without one, ``title``."""
    for heading, text in _texts(nodes, title):
        if SLOT in text:
            raise input_error(source_path, f"section {heading}", f"still holds the fill slot {SLOT} of its "
                              "template", f"Fill the section in place of {SLOT}; see {OWNER}")


def _is_slot(node: Node) -> bool:
    children = node["children"]
    return (node["type"] == "paragraph" and len(children) == 1 and children[0]["type"] == "text"
            and children[0]["text"].strip() == SLOT)


def _texts(nodes: list[Node], title: str) -> Iterator[tuple[str, str]]:
    """Each text node's text below ``nodes``, in document order, with the heading it stands under,
    or ``title`` above every heading; code is literal and holds no text."""
    heading = [title]

    def walk(items: list[Node]) -> Iterator[tuple[str, str]]:
        for node in items:
            if node["type"] == "section":
                heading[0] = _plain(node["children"]) or heading[0]
            if node["type"] == "text":
                yield heading[0], node["text"]
            yield from walk(node["children"])

    return walk(nodes)


def _plain(nodes: list[Node]) -> str:
    return "".join(str(node.get("text", "")) + _plain(node["children"]) for node in nodes).strip()
