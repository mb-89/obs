import json
import re
from pathlib import Path

from jsonschema import ValidationError, validate
import pytest

from obs.capabilities import build_capability_reference
from obs.document import STRUCTURAL_NODE_TYPES, DocumentError, build_document


ROOT = Path(__file__).parents[1]
INPUT_CAPABILITY_GAPS: frozenset[str] = frozenset({"extensions"})
"""Capabilities no input syntax yields yet; capabilities/extensions owns why."""


def capability_reference() -> dict[str, object]:
    return build_capability_reference(
        ROOT / "spec" / "capabilities", ROOT / "spec" / "capabilities" / "coverage.json",
    )


def node_types(document: dict[str, object]) -> set[str]:
    def descend(node: dict[str, object]):
        yield node["type"]
        for child in node["children"]:
            yield from descend(child)

    def chapters(items: list[dict[str, object]]):
        for chapter in items:
            for node in chapter["content"]:
                yield from descend(node)
            yield from chapters(chapter["children"])

    return {
        *[kind for node in document["manifest"]["abstract"] for kind in descend(node)],
        *chapters(document["chapters"]),
    }


def recognized_capability_document(tmp_path) -> dict[str, object]:
    return build_document(recognized_capability_vault(tmp_path) / "manifest.md", capability_reference())


def recognized_capability_vault(tmp_path) -> Path:
    vault = tmp_path / "recognized"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "target.md").write_text("# Target\n", encoding="utf-8")
    (vault / "chapter.md").write_text(
        "# Chapter\n\nBefore [[target#Heading|Label]] ![[target]] #mark/risk/watch.\n\n"
        "> [!warning] Be careful\n> Callout body.\n\n"
        "```base\nviews: []\n```\n\n```figure\ncaption: Diagram\n```\n\n```cmd\necho example\n```\n",
        encoding="utf-8",
    )
    return vault


def additional_capability_document(tmp_path) -> dict[str, object]:
    return build_document(additional_capability_vault(tmp_path) / "manifest.md", capability_reference())


def additional_capability_vault(tmp_path) -> Path:
    vault = tmp_path / "additional"
    vault.mkdir()
    (vault / "manifest.md").write_text(
        "---\ntitle: Fixture\n---\n- [[chapter]]\n",
        encoding="utf-8",
    )
    (vault / "register.base").write_text(
        "views:\n  - type: table\n    name: Open\n    order: [file.name]\n", encoding="utf-8",
    )
    (vault / "source.csv").write_text("value\n1\n", encoding="utf-8")
    (vault / "chapter.md").write_text(
        "---\nkind: quantity\naliases: [coverage]\nsource: '[[manifest]]'\nquery: {where: []}\n"
        "obsHtml: {document: false}\n"
        "reference: https://example.test/source\n---\n"
        "![Source](source.csv)\n\n![[register.base#Open]]\n\n"
        "```cards\nversion: 1\ncards: [{title: Coverage, body: Current state.}]\n```\n\n"
        "```figure\n"
        '{"schemaVersion": 1, "id": "comparison", "data": {}, "panels": [{"id": "overview", '
        '"bounds": {"x": 0, "y": 0, "width": 1, "height": 1}, '
        '"grid": {"row": 0, "column": 0, "rowSpan": 1, "columnSpan": 1}, '
        '"axes": [{"id": "time", "scale": "linear", "limits": {"minimum": 0, "maximum": 1}, '
        '"label": "Time"}]}], '
        '"provenance": {"command": ["generate-figure"]}}\n'
        "```\n\n"
        "```property-editor\nversion: 1\nfield: source\nlabel: Source\n```\n",
        encoding="utf-8",
    )
    return vault


def test_core_parses_a_vault_into_semantic_document_json(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text(
        "---\ntitle: Fixture vault\n---\n- [[chapter|Chapter]]\n",
        encoding="utf-8",
    )
    (vault / "chapter.md").write_text(
        "---\nkind: finding\n---\n# Heading\n\nA [reference](https://example.test/reference).\n\n"
        "![Diagram](diagram.svg)\n\n```text\nliteral\n```\n",
        encoding="utf-8",
    )
    (vault / "diagram.svg").write_text("<svg/>", encoding="utf-8")

    document = build_document(vault / "manifest.md", capability_reference())

    validate(document, json.loads((ROOT / "src" / "obs" / "document.schema.json").read_text(
        encoding="utf-8",
    )))
    assert document["manifest"] == {
        "title": "Fixture vault", "metadata": {"title": "Fixture vault"},
        "abstract": [
            {"type": "markdown-frontmatter", "attrs": {"metadata": {"title": "Fixture vault"}}, "children": [
                {"type": "field", "attrs": {"name": "title"}, "children": [
                    {"type": "text", "attrs": {}, "children": [], "text": "Fixture vault"},
                ]},
            ]},
            {"type": "manifest", "attrs": {}, "children": []},
        ],
    }
    chapter = document["chapters"][0]
    assert chapter["metadata"] == {"kind": "finding"}
    assert [node["type"] for node in chapter["content"]] == [
        "markdown-frontmatter", "chapter-inclusion", "markdown", "section", "paragraph",
        "paragraph", "code",
    ]
    assert document["links"] == [{
        "id": "reference", "href": "https://example.test/reference", "label": "reference",
    }]
    assert document["assets"] == [{
        "id": "diagram", "href": "diagram.svg", "mediaType": "image/svg+xml",
        "path": "diagram.svg", "data": "PHN2Zy8+",
    }]
    assert all(node["type"] != "html" for node in chapter["content"])


def test_core_places_recognized_capabilities_in_content_nodes(tmp_path) -> None:
    document = recognized_capability_document(tmp_path)
    content = document["chapters"][0]["content"]

    assert [node["type"] for node in content] == [
        "chapter-inclusion", "markdown", "section", "paragraph", "callouts", "bases",
        "figures", "command-fences",
    ]
    assert content[3]["children"][1] == {
        "type": "wikilinks",
        "attrs": {"target": "target", "chapter": "target", "heading": "Heading", "label": "Label"},
        "children": [],
    }
    assert content[3]["children"][3] == {
        "type": "embeds", "attrs": {"target": "target", "chapter": "target"}, "children": [],
    }
    assert content[3]["children"][5] == {
        "type": "marks", "attrs": {"category": "risk", "id": "watch"}, "children": [],
    }
    assert content[4]["attrs"] == {"kind": "warning", "title": "Be careful"}
    assert content[4]["children"] == [{
        "type": "paragraph", "attrs": {},
        "children": [{"type": "text", "attrs": {}, "children": [], "text": "Callout body."}],
    }]
    assert content[5]["attrs"] == {"source": "views: []\n", "spec": {"views": []}}
    assert content[6]["attrs"] == {"source": "caption: Diagram\n", "spec": {"caption": "Diagram"}}
    assert content[7]["attrs"] == {"source": "echo example\n"}
    assert set(document["capabilities"]) == {
        "bases", "callouts", "chapter-inclusion", "command-fences", "embeds", "figures",
        "manifest", "markdown", "marks", "wikilinks",
    }


def test_a_vault_whose_only_special_syntax_is_a_callout_uses_callouts_not_extensions(
    tmp_path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text("> [!warning] Check the limits\n> Body.\n", encoding="utf-8")

    document = build_document(vault / "manifest.md", capability_reference())

    assert "callouts" in document["capabilities"]
    assert "extensions" not in document["capabilities"]
    assert "extensions" not in node_types(document)


def test_a_callout_body_arrives_as_parsed_nodes_like_chapter_content(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "target.md").write_text("# Target\n", encoding="utf-8")
    (vault / "chapter.md").write_text(
        "> [!warning] Check the limits\n"
        "> Read *carefully*, see [[target|Target]] and [site](https://example.test).\n"
        ">\n> - item `one`\n>\n"
        "> > [!note] Inner\n> > Nested body.\n",
        encoding="utf-8",
    )

    document = build_document(vault / "manifest.md", capability_reference())

    validate(document, json.loads((ROOT / "src" / "obs" / "document.schema.json").read_text(
        encoding="utf-8",
    )))
    [callout] = [node for node in document["chapters"][0]["content"] if node["type"] == "callouts"]
    assert callout["attrs"] == {"kind": "warning", "title": "Check the limits"}
    paragraph, listing, nested = callout["children"]
    assert paragraph == {"type": "paragraph", "attrs": {}, "children": [
        {"type": "text", "attrs": {}, "children": [], "text": "Read "},
        {"type": "emphasis", "attrs": {}, "children": [
            {"type": "text", "attrs": {}, "children": [], "text": "carefully"},
        ]},
        {"type": "text", "attrs": {}, "children": [], "text": ", see "},
        {"type": "wikilinks", "attrs": {
            "target": "target", "chapter": "target", "heading": "", "label": "Target",
        }, "children": []},
        {"type": "text", "attrs": {}, "children": [], "text": " and "},
        {"type": "text", "attrs": {"link": "site"}, "children": [], "text": "site"},
        {"type": "text", "attrs": {}, "children": [], "text": "."},
    ]}
    assert listing["type"] == "list"
    assert listing["children"][0]["children"][0]["children"][1] == {
        "type": "code", "attrs": {}, "children": [], "text": "one",
    }
    assert nested == {"type": "callouts", "attrs": {"kind": "note", "title": "Inner"}, "children": [
        {"type": "paragraph", "attrs": {}, "children": [
            {"type": "text", "attrs": {}, "children": [], "text": "Nested body."},
        ]},
    ]}
    assert {"callouts", "wikilinks"} <= set(document["capabilities"])
    assert {"id": "site", "href": "https://example.test", "label": "site"} in document["links"]


def test_a_card_body_arrives_as_parsed_nodes_with_its_capability_fences(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "target.md").write_text("---\nstatus: open\n---\n# Target\n", encoding="utf-8")
    inner_cards = '{"version": 1, "cards": [{"title": "Inner", "body": "Nested body."}]}'
    body = (
        "See [[target|Target]].\n\n"
        "```base\nfilters: 'status == \"open\"'\nviews: []\n```\n\n"
        "```cmd\necho card\n```\n\n"
        "```figure\ncaption: Diagram\n```\n\n"
        f"```cards\n{inner_cards}\n```\n\n"
        "```property-editor\nversion: 1\nfield: status\nlabel: Status\n```\n"
    )
    cards = {"version": 1, "cards": [
        {"title": "First", "body": body},
        {"title": "Second", "body": "Plain text."},
    ]}
    (vault / "chapter.md").write_text(
        f"```cards\n{json.dumps(cards)}\n```\n", encoding="utf-8",
    )
    document = build_document(vault / "manifest.md", capability_reference())

    validate(document, json.loads((ROOT / "src" / "obs" / "document.schema.json").read_text(
        encoding="utf-8",
    )))
    [node] = [node for node in document["chapters"][0]["content"] if node["type"] == "cards-metrics"]
    assert node["attrs"]["spec"] == cards
    first, second = node["children"]
    assert first["type"] == second["type"] == "document"
    assert first["attrs"] == second["attrs"] == {}
    assert [child["type"] for child in first["children"]] == [
        "paragraph", "bases", "command-fences", "figures", "cards-metrics", "property-editors",
    ]
    assert first["children"][0]["children"][1]["attrs"]["chapter"] == "target"
    assert first["children"][4]["children"][0]["children"] == [
        {"type": "paragraph", "attrs": {}, "children": [
            {"type": "text", "attrs": {}, "children": [], "text": "Nested body."},
        ]},
    ]
    assert second["children"] == [{"type": "paragraph", "attrs": {}, "children": [
        {"type": "text", "attrs": {}, "children": [], "text": "Plain text."},
    ]}]
    assert {
        "bases", "command-fences", "figures", "cards-metrics", "property-editors", "wikilinks",
    } <= set(document["capabilities"])
    assert "target" in [chapter["id"] for chapter in document["chapters"]]


def test_a_cards_document_node_holds_only_card_body_documents() -> None:
    schema = json.loads((ROOT / "src" / "obs" / "document.schema.json").read_text(encoding="utf-8"))
    node_schema = {"$defs": schema["$defs"], "$ref": "#/$defs/node"}
    body = {"type": "document", "attrs": {}, "children": []}
    node = {"type": "cards-metrics", "attrs": {"source": "", "spec": {}}, "children": [body]}
    validate(node, node_schema)
    with pytest.raises(ValidationError):
        validate({**node, "children": [{**body, "type": "paragraph"}]}, node_schema)


def test_a_callout_document_node_has_only_kind_and_title_attrs() -> None:
    schema = json.loads((ROOT / "src" / "obs" / "document.schema.json").read_text(encoding="utf-8"))
    node_schema = {"$defs": schema["$defs"], "$ref": "#/$defs/node"}
    node = {"type": "callouts", "attrs": {"kind": "warning", "title": ""}, "children": []}
    validate(node, node_schema)
    with pytest.raises(ValidationError):
        validate({**node, "attrs": {"kind": "warning"}}, node_schema)
    with pytest.raises(ValidationError):
        validate({**node, "attrs": {**node["attrs"], "body": "x"}}, node_schema)


def test_core_marks_silent_command_fences_as_non_rendering_producers(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text(
        "```cmd silent\nproduce-file\n```\n", encoding="utf-8",
    )

    document = build_document(vault / "manifest.md", capability_reference())

    assert document["chapters"][0]["content"][-1] == {
        "type": "command-fences",
        "attrs": {"source": "produce-file\n", "silent": True},
        "children": [],
    }


def test_core_emits_data_only_nodes_for_additional_input_capabilities(tmp_path) -> None:
    document = additional_capability_document(tmp_path)
    nodes = document["chapters"][0]["content"]
    emitted = [
        node for parent in nodes
        for node in (parent["children"] if parent["type"] == "paragraph" else [parent])
    ]

    assert [node["type"] for node in emitted] == [
        "markdown-frontmatter", "profiles", "quantities", "queries", "count-query",
        "references", "chapter-inclusion", "markdown", "attachments", "registers",
        "cards-metrics", "figure-descriptor", "property-editors",
    ]
    assert emitted[-2]["attrs"]["descriptor"]["id"] == "comparison"
    assert emitted[-1]["attrs"] == {
        "source": "version: 1\nfield: source\nlabel: Source\n",
        "spec": {"version": 1, "field": "source", "label": "Source"},
    }
    assert {
        "attachments", "cards-metrics", "count-query", "figure-descriptor",
        "markdown-frontmatter", "profiles", "property-editors", "quantities", "queries",
        "references", "registers",
    } <= set(document["capabilities"])


def register_vault(tmp_path, embed: str = "![[x.base#Open points]]") -> Path:
    vault = tmp_path / "registers"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text(f"# Chapter\n\n{embed}\n", encoding="utf-8")
    (vault / "x.base").write_text(
        "filters: 'kind == \"point\"'\n"
        "views:\n"
        "  - type: table\n    name: All points\n    order: [file.name]\n"
        "  - type: table\n    name: Open points\n    filters: 'status == \"open\"'\n"
        "    order: [file.name, status]\n"
        "  - type: table\n    name: Marked\n    order: [label]\n    obsHtml: {records: tag}\n",
        encoding="utf-8",
    )
    for name, status in (("a-point", "open"), ("b-point", "closed"), ("c-point", "Open")):
        (vault / f"{name}.md").write_text(f"---\nkind: point\nstatus: {status}\n---\n", encoding="utf-8")
    (vault / "d-point.md").write_text(
        "---\nkind: point\nstatus: open\nignored: true\n---\n", encoding="utf-8",
    )
    (vault / "other.md").write_text("---\nstatus: open\n---\n", encoding="utf-8")
    return vault


def _registers(document: dict[str, object]) -> list[dict[str, object]]:
    return [
        node for node in document["chapters"][0]["content"] if node["type"] == "paragraph"
        for node in node["children"] if node["type"] == "registers"
    ]


def test_a_register_embed_carries_the_base_definition_and_its_view_rows(tmp_path) -> None:
    document = build_document(register_vault(tmp_path) / "manifest.md", capability_reference())

    validate(document, json.loads((ROOT / "src" / "obs" / "document.schema.json").read_text(
        encoding="utf-8",
    )))
    [register] = _registers(document)
    assert register["attrs"]["target"] == "x.base"
    assert register["attrs"]["heading"] == "Open points"
    assert register["attrs"]["base"]["filters"] == 'kind == "point"'
    assert [view["name"] for view in register["attrs"]["base"]["views"]] == [
        "All points", "Open points", "Marked",
    ]
    assert register["attrs"]["view"] == 1
    assert register["attrs"]["rows"] == [
        ["a-point", "b-point", "c-point"], ["a-point", "c-point"], [],
    ]
    records = {record["id"] for record in document["records"]}
    assert {identifier for rows in register["attrs"]["rows"] if rows for identifier in rows} <= records


def test_a_register_embed_without_a_view_embeds_all_views(tmp_path) -> None:
    document = build_document(
        register_vault(tmp_path, "![[x.base]]") / "manifest.md", capability_reference(),
    )

    [register] = _registers(document)
    assert register["attrs"]["heading"] == ""
    assert register["attrs"]["view"] is None
    assert register["attrs"]["rows"][0] == ["a-point", "b-point", "c-point"]


@pytest.mark.parametrize(("embed", "message"), [
    ("![[x.base#Closed]]", r"Register view does not exist in chapter\.md: !\[\[x\.base#Closed\]\] "
     r"names no view of x\.base; name one of: All points, Open points, Marked\."),
    ("![[missing.base#Open]]", r"Base does not exist in chapter\.md: !\[\[missing\.base#Open\]\] matches no "
     r"vault file; create missing\.base in the vault or embed the vault path of an existing \.base file\."),
])
def test_a_register_embed_that_does_not_resolve_names_the_note_and_the_remedy(
    tmp_path, embed: str, message: str,
) -> None:
    with pytest.raises(DocumentError, match=message):
        build_document(register_vault(tmp_path, embed) / "manifest.md", capability_reference())


def test_a_bare_base_name_embeds_the_one_vault_file_it_matches(tmp_path) -> None:
    vault = register_vault(tmp_path)
    (vault / "bases").mkdir()
    (vault / "x.base").rename(vault / "bases" / "x.base")

    document = build_document(vault / "manifest.md", capability_reference())

    [register] = _registers(document)
    assert register["attrs"]["view"] == 1
    assert register["attrs"]["rows"][1] == ["a-point", "c-point"]


def test_a_bare_base_name_that_matches_two_files_names_both_and_the_remedy(tmp_path) -> None:
    vault = register_vault(tmp_path)
    for folder in ("a", "b"):
        (vault / folder).mkdir()
        (vault / folder / "x.base").write_text((vault / "x.base").read_text(encoding="utf-8"), encoding="utf-8")
    (vault / "x.base").unlink()

    with pytest.raises(DocumentError) as raised:
        build_document(vault / "manifest.md", capability_reference())

    message = str(raised.value)
    assert "in chapter.md: ![[x.base#Open points]]" in message
    assert "a/x.base, b/x.base" in message
    assert "vault path" in message


def test_each_view_selects_its_own_members(tmp_path) -> None:
    vault = register_vault(tmp_path, "![[x.base]]")
    (vault / "x.base").write_text(
        "filters: 'kind == \"point\"'\n"
        "views:\n"
        "  - type: table\n    name: First\n    order: [file.name]\n"
        "    obsHtml:\n      members:\n        - path: b-point.md\n        - path: a-point.md\n"
        "  - type: table\n    name: Second\n    order: [file.name]\n"
        "    obsHtml:\n      members:\n        - path: c-point.md\n"
        "  - type: table\n    name: All\n    order: [file.name]\n",
        encoding="utf-8",
    )

    document = build_document(vault / "manifest.md", capability_reference())

    [register] = _registers(document)
    assert register["attrs"]["rows"] == [["a-point", "b-point"], ["c-point"], ["a-point", "b-point", "c-point"]]


@pytest.mark.parametrize(("note", "text", "field"), [
    ("chapter.md", "# Chapter\n\n```base\nobsHtml:\n  members:\n    - path: a-point.md\n"
     "views:\n  - type: table\n    order: [file.name]\n```\n", "base fence 1, obsHtml.members"),
    ("x.base", "obsHtml:\n  members:\n    - path: a-point.md\n"
     "views:\n  - type: table\n    order: [file.name]\n", "obsHtml.members"),
])
def test_base_level_members_fail_naming_the_note_and_the_remedy(tmp_path, note: str, text: str, field: str) -> None:
    vault = register_vault(tmp_path, "![[x.base]]")
    (vault / note).write_text(text, encoding="utf-8")

    with pytest.raises(DocumentError) as raised:
        build_document(vault / "manifest.md", capability_reference())

    message = str(raised.value)
    assert message.startswith(f"{vault / note}: {field}: "), message
    assert "; see capabilities/bases." in message


def test_an_invalid_register_base_names_the_embedding_note_and_the_remedy(tmp_path) -> None:
    vault = register_vault(tmp_path)
    (vault / "x.base").write_text("views:\n  - type: table\n", encoding="utf-8")

    with pytest.raises(DocumentError, match=(
        r"^.*x\.base: views\[0\]\.order: is missing\. Add order; see capabilities/bases\. "
        r"chapter\.md embeds it as x\.base\.$"
    )):
        build_document(vault / "manifest.md", capability_reference())


def test_core_resolves_link_and_embed_targets_to_chapter_ids(tmp_path) -> None:
    vault = tmp_path / "vault"
    (vault / "part").mkdir(parents=True)
    (vault / "manifest.md").write_text("- [[intro]]\n- [[part/details]]\n", encoding="utf-8")
    (vault / "outside.md").write_text("Outside.\n", encoding="utf-8")
    (vault / "part" / "details.md").write_text("Details.\n", encoding="utf-8")
    (vault / "intro.md").write_text(
        "[[details#Part|Read]] ![[part/details]] [[outside]] ![[outside]] [[missing]]\n",
        encoding="utf-8",
    )

    document = build_document(vault / "manifest.md", capability_reference())
    nodes = [
        node for node in document["chapters"][0]["content"][-1]["children"]
        if node["type"] in {"wikilinks", "embeds"}
    ]

    assert [(node["type"], node["attrs"]["chapter"]) for node in nodes] == [
        ("wikilinks", "part-details"), ("embeds", "part-details"),
        ("wikilinks", "outside"), ("embeds", "outside"), ("wikilinks", None),
    ]


def test_spec_document_wikilinks_name_their_included_chapter(spec_document) -> None:
    document = spec_document
    manifest = (ROOT / "spec" / "manifest.md").read_text(encoding="utf-8")
    listed = {
        target: re.sub(r"[^a-z0-9]+", "-", target.lower()).strip("-")
        for target in re.findall(r"^ *- \[\[([^\]|]+)", manifest, re.MULTILINE)
    }

    def listed_chapter(target: str) -> str | None:
        """The listed chapter a link names: by its path, or by note name when it has no folder."""
        if "/" in target:
            return listed.get(target)
        return next((chapter for path, chapter in listed.items() if Path(path).name == target), None)

    def links(nodes: list[dict[str, object]]):
        for node in nodes:
            if node["type"] in {"wikilinks", "embeds"}:
                yield node["attrs"]
            yield from links(node["children"])

    def chapters(items: list[dict[str, object]]):
        for chapter in items:
            yield from links(chapter["content"])
            yield from chapters(chapter["children"])

    resolved = list(chapters(document["chapters"]))
    included = [attrs for attrs in resolved if listed_chapter(attrs["target"])]
    assert included
    assert all(attrs["chapter"] == listed_chapter(attrs["target"]) for attrs in included)
    unlisted = {chapter["id"] for chapter in document["chapters"] if chapter.get("toc") is False}
    assert all(
        attrs["chapter"] in unlisted | {"home"}
        for attrs in resolved if not listed_chapter(attrs["target"])
    )


def test_core_parses_the_spec_vault_as_neutral_document(tmp_path, spec_document) -> None:
    reference = capability_reference()
    document = spec_document
    structural = STRUCTURAL_NODE_TYPES
    references = {item["id"] for item in reference["capabilities"]}
    types = node_types(document)
    assert types <= structural | references
    assert {"wikilinks", "bases", "command-fences", "marks"} <= types
    assert set(document["capabilities"]) <= references
    assert set(document["capabilities"]) == types & references
    coverage = json.loads((ROOT / "spec" / "capabilities" / "coverage.json").read_text(
        encoding="utf-8",
    ))["sections"]
    input_ids = {
        item["id"] for item in reference["capabilities"]
        if coverage[item["source"].removesuffix("]]").split("#", 1)[1]] == "input"
    }
    emitted = types | node_types(recognized_capability_document(tmp_path)) | node_types(
        additional_capability_document(tmp_path),
    )
    assert input_ids <= emitted | INPUT_CAPABILITY_GAPS
    assert INPUT_CAPABILITY_GAPS == {"extensions"}
    assert not INPUT_CAPABILITY_GAPS & emitted
    with pytest.raises(AssertionError):
        assert input_ids <= (emitted - {"attachments"}) | INPUT_CAPABILITY_GAPS
    assert "html" not in types


def test_a_callout_nested_under_a_list_item_is_a_callout_of_that_item(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text(
        "- Item\n\n  > [!warning] Risk\n  > Body.\n\n  ```text\n  literal\n  ```\n"
        "- > [!note]\n  > Marked item.\n",
        encoding="utf-8",
    )

    document = build_document(vault / "manifest.md", capability_reference())

    validate(document, json.loads((ROOT / "src" / "obs" / "document.schema.json").read_text(
        encoding="utf-8",
    )))
    [listing] = [node for node in document["chapters"][0]["content"] if node["type"] == "list"]
    first, second = listing["children"]
    assert [child["type"] for child in first["children"]] == ["paragraph", "callouts", "code"]
    assert first["children"][1] == {
        "type": "callouts", "attrs": {"kind": "warning", "title": "Risk"}, "children": [
            {"type": "paragraph", "attrs": {}, "children": [
                {"type": "text", "attrs": {}, "children": [], "text": "Body."},
            ]},
        ],
    }
    assert second["children"] == [{
        "type": "callouts", "attrs": {"kind": "note", "title": "Note"}, "children": [
            {"type": "paragraph", "attrs": {}, "children": [
                {"type": "text", "attrs": {}, "children": [], "text": "Marked item."},
            ]},
        ],
    }]
    assert "callouts" in document["capabilities"]


def test_a_list_keeps_whether_it_was_authored_tight_or_loose(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text(
        "- tight one\n- tight two\n\nText.\n\n1. loose one\n\n2. loose two\n", encoding="utf-8",
    )

    document = build_document(vault / "manifest.md", capability_reference())

    validate(document, json.loads((ROOT / "src" / "obs" / "document.schema.json").read_text(
        encoding="utf-8",
    )))
    lists = [node["attrs"] for node in document["chapters"][0]["content"] if node["type"] == "list"]
    assert lists == [{"ordered": False, "tight": True}, {"ordered": True, "tight": False}]


INLINE_SOURCE = "A *em* **strong** ~~gone~~ `code` $x^2$ [link](https://example.test)"
"""One of each inline mark the input model supports; INLINE_NODES is what it becomes."""


def _text(text: str, **attrs: str) -> dict[str, object]:
    return {"type": "text", "attrs": attrs, "children": [], "text": text}


INLINE_NODES = [
    _text("A "),
    {"type": "emphasis", "attrs": {}, "children": [_text("em")]},
    _text(" "),
    {"type": "strong", "attrs": {}, "children": [_text("strong")]},
    _text(" "),
    {"type": "strikethrough", "attrs": {}, "children": [_text("gone")]},
    _text(" "),
    {"type": "code", "attrs": {}, "children": [], "text": "code"},
    _text(" "),
    {"type": "math", "attrs": {"display": False}, "children": [], "text": "x^2"},
    _text(" "),
    _text("link", link="link"),
]


def test_inline_marks_arrive_as_inline_nodes_in_every_context(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    cards = {"version": 1, "cards": [{"title": "Card", "body": INLINE_SOURCE}]}
    (vault / "chapter.md").write_text(
        f"---\nsummary: '{INLINE_SOURCE}'\n---\n# {INLINE_SOURCE}\n\n{INLINE_SOURCE}\n\n"
        f"- {INLINE_SOURCE}\n\n> [!note] Title\n> {INLINE_SOURCE}\n\n> {INLINE_SOURCE}\n\n"
        f"| Head |\n|:---:|\n| {INLINE_SOURCE} |\n\n```cards\n{json.dumps(cards)}\n```\n\n"
        "$$\nE = mc^2\n$$\n",
        encoding="utf-8",
    )

    document = build_document(vault / "manifest.md", capability_reference())

    validate(document, json.loads((ROOT / "src" / "obs" / "document.schema.json").read_text(
        encoding="utf-8",
    )))
    content = {}
    for node in document["chapters"][0]["content"]:
        content.setdefault(node["type"], node)
    assert content["markdown-frontmatter"]["children"] == [
        {"type": "field", "attrs": {"name": "summary"}, "children": INLINE_NODES},
    ]
    assert content["section"]["children"] == INLINE_NODES
    assert content["paragraph"]["children"] == INLINE_NODES
    assert content["list"]["children"][0]["children"][0]["children"] == INLINE_NODES
    assert content["callouts"]["children"][0]["children"] == INLINE_NODES
    assert content["quote"] == {"type": "quote", "attrs": {}, "children": [
        {"type": "paragraph", "attrs": {}, "children": INLINE_NODES},
    ]}
    assert content["table"] == {"type": "table", "attrs": {}, "children": [
        {"type": "table-row", "attrs": {}, "children": [
            {"type": "table-cell", "attrs": {"header": True, "align": "center"}, "children": [
                _text("Head"),
            ]},
        ]},
        {"type": "table-row", "attrs": {}, "children": [
            {"type": "table-cell", "attrs": {"header": False, "align": "center"}, "children": INLINE_NODES},
        ]},
    ]}
    assert content["cards-metrics"]["children"][0]["children"][0]["children"] == INLINE_NODES
    assert content["math"] == {
        "type": "math", "attrs": {"display": True}, "children": [], "text": "E = mc^2",
    }


def test_a_manifest_metadata_value_arrives_as_inline_nodes_by_field_path(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text(
        "---\ntitle: Fixture\nproduct: {name: '*Name*'}\nauthors: ['**One**', 2]\n"
        "date: 2026-11-05\n---\n- [[chapter]]\n",
        encoding="utf-8",
    )
    (vault / "chapter.md").write_text("Body.\n", encoding="utf-8")

    document = build_document(vault / "manifest.md", capability_reference())

    [frontmatter] = [
        node for node in document["manifest"]["abstract"] if node["type"] == "markdown-frontmatter"
    ]
    assert frontmatter["children"] == [
        {"type": "field", "attrs": {"name": "title"}, "children": [_text("Fixture")]},
        {"type": "field", "attrs": {"name": "product.name"}, "children": [
            {"type": "emphasis", "attrs": {}, "children": [_text("Name")]},
        ]},
        {"type": "field", "attrs": {"name": "authors.0"}, "children": [
            {"type": "strong", "attrs": {}, "children": [_text("One")]},
        ]},
    ]


class _EveryCapability(set):
    """A capability set that admits every id, so the core emits every capability it can."""

    def __contains__(self, item: object) -> bool:
        return True

    def __bool__(self) -> bool:
        return True


def test_every_capability_the_core_emits_has_a_capability_note(tmp_path) -> None:
    from obs.vault import build_document as parse_vault

    emitted = set()
    for vault in (recognized_capability_vault(tmp_path), additional_capability_vault(tmp_path)):
        emitted |= set(parse_vault(vault / "manifest.md", _EveryCapability())["capabilities"])
    notes = {item["id"] for item in capability_reference()["capabilities"]}

    assert "property-editors" in emitted
    assert emitted - notes == set()


def test_a_thematic_break_yields_a_rule_node(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text(
        "Before.\n\n---\n\nBetween.\n\n***\n\n___\n\n> Quoted.\n>\n> ---\n",
        encoding="utf-8",
    )

    document = build_document(vault / "manifest.md", capability_reference())

    validate(document, json.loads((ROOT / "src" / "obs" / "document.schema.json").read_text(
        encoding="utf-8",
    )))
    rule = {"type": "rule", "attrs": {}, "children": []}
    content = document["chapters"][0]["content"][2:]
    assert [node["type"] for node in content] == [
        "paragraph", "rule", "paragraph", "rule", "rule", "quote",
    ]
    assert content[1] == rule
    assert content[-1]["children"][-1] == rule
    assert "rule" in STRUCTURAL_NODE_TYPES


def test_a_rule_document_node_has_no_attrs_and_no_children() -> None:
    schema = json.loads((ROOT / "src" / "obs" / "document.schema.json").read_text(encoding="utf-8"))
    node_schema = {"$defs": schema["$defs"], "$ref": "#/$defs/node"}
    validate({"type": "rule", "attrs": {}, "children": []}, node_schema)
    with pytest.raises(ValidationError):
        validate({"type": "rule", "attrs": {"style": "dashed"}, "children": []}, node_schema)
    with pytest.raises(ValidationError):
        validate({"type": "rule", "attrs": {}, "children": [
            {"type": "text", "attrs": {}, "children": [], "text": "x"},
        ]}, node_schema)


def test_an_untitled_callout_is_titled_by_its_capitalized_keyword(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text(
        "> [!note]\n> Body.\n\n> [!faq]-\n> Alias.\n\n> [!warning] Authored\n\n"
        "> [!important]\n> Key takeaway.\n\n> [!TIP]\n",
        encoding="utf-8",
    )

    document = build_document(vault / "manifest.md", capability_reference())

    assert [
        node["attrs"] for node in document["chapters"][0]["content"] if node["type"] == "callouts"
    ] == [
        {"kind": "note", "title": "Note"},
        {"kind": "question", "title": "Faq"},
        {"kind": "warning", "title": "Authored"},
        {"kind": "important", "title": ""},
        {"kind": "tip", "title": "Tip"},
    ]


RECORD_TYPES = json.loads((ROOT / "src" / "obs" / "document.schema.json").read_text(encoding="utf-8"))[
    "$defs"]["record"]["properties"]["type"]["enum"]
"""The record types a Base view can select (capabilities/registers, Document node)."""


def projection_vault(tmp_path) -> Path:
    vault = tmp_path / "projections"
    vault.mkdir()
    (vault / "manifest.md").write_text(
        "---\ntitle: Projections\nstatus: draft\n"
        "history:\n  - {version: '1', author: Ann, change: First}\n---\n"
        "- [[registers]]\n  - [[part|Part one]]\n",
        encoding="utf-8",
    )
    (vault / "registers.md").write_text("# Registers\n\n![[x.base]]\n", encoding="utf-8")
    (vault / "part.md").write_text(
        "---\nowner: Ann\n---\n# Part\n\nCheck it. #mark/risk/check_it\n", encoding="utf-8",
    )
    (vault / "term.md").write_text(
        "---\nkind: glossary\nterm: Datum\ndefinition: A reference.\nowner: Ann\n---\n", encoding="utf-8",
    )
    (vault / "hidden-term.md").write_text(
        "---\nkind: glossary\nterm: Hidden\ndefinition: Never.\nowner: Ann\nignored: true\n---\n",
        encoding="utf-8",
    )
    filters = {
        "note": 'file.name == "term"', "chapter": 'owner == "Ann"', "tag": 'type == "risk"',
        "glossary": 'owner == "Ann"', "documentMetadata": 'key == "status"',
        "documentHistory": 'author == "Ann"',
    }
    (vault / "x.base").write_text("views:\n" + "".join(
        f"  - type: table\n    name: {kind}\n    filters: '{filters[kind].replace(chr(39), chr(39) * 2)}'\n"
        f"    order: [file.name]\n    obsHtml: {{records: {kind}}}\n"
        for kind in RECORD_TYPES
    ), encoding="utf-8")
    return vault


def test_every_record_type_yields_records_and_rows_of_its_type(tmp_path) -> None:
    document = build_document(projection_vault(tmp_path) / "manifest.md", capability_reference())

    records = {record["id"]: record for record in document["records"]}
    [register] = [
        node for chapter in document["chapters"] for block in chapter["content"]
        for node in block["children"] if node["type"] == "registers"
    ]
    rows = dict(zip((view["name"] for view in register["attrs"]["base"]["views"]), register["attrs"]["rows"]))
    assert list(rows) == RECORD_TYPES
    for kind, selected in rows.items():
        assert selected, kind
        assert {records[identifier]["type"] for identifier in selected} == {kind}
    assert [records[identifier]["fields"] for identifier in rows["chapter"]] == [
        {"chapter": "Part one", "title": "Part one", "depth": "1", "slug": "part", "sourcePath": "part.md"},
    ]
    assert [records[identifier]["fields"] for identifier in rows["tag"]] == [
        {"sourcePath": "part.md", "type": "risk", "label": "check_it", "text": "Check it.", "source": "Part one"},
    ]
    assert [records[identifier]["fields"]["term"] for identifier in rows["glossary"]] == ["Datum"]
    assert [records[identifier]["fields"] for identifier in rows["documentMetadata"]] == [
        {"key": "status", "value": "draft"},
    ]
    assert [records[identifier]["fields"] for identifier in rows["documentHistory"]] == [
        {"version": "1", "author": "Ann", "change": "First", "date": ""},
    ]


def test_a_glossary_row_a_view_selects_includes_its_note_and_ids_are_stable(tmp_path) -> None:
    manifest = projection_vault(tmp_path) / "manifest.md"
    document = build_document(manifest, capability_reference())

    assert "term" in [chapter["id"] for chapter in document["chapters"]]
    assert "hidden-term" not in [chapter["id"] for chapter in document["chapters"]]
    assert [record["id"] for record in document["records"]] == [
        record["id"] for record in build_document(manifest, capability_reference())["records"]
    ]
    assert {record["note"]: record["id"] for record in document["records"] if record["type"] == "glossary"} == {
        "hidden-term": "glossary-hidden-term", "term": "glossary-term",
    }
