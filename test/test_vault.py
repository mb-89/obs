import json
from pathlib import Path

from jsonschema import validate

from obs.capabilities import build_capability_reference
from obs.document import build_document


ROOT = Path(__file__).parents[1]


def capability_reference() -> dict[str, object]:
    return build_capability_reference(
        ROOT / "spec" / "capabilities", ROOT / "spec" / "capabilities" / "coverage.json",
    )


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
        "title": "Fixture vault", "metadata": {"title": "Fixture vault"}, "abstract": [],
    }
    chapter = document["chapters"][0]
    assert chapter["metadata"] == {"kind": "finding"}
    assert [node["type"] for node in chapter["content"]] == [
        "section", "paragraph", "paragraph", "code",
    ]
    assert document["links"] == [{
        "id": "reference", "href": "https://example.test/reference", "label": "reference",
    }]
    assert document["assets"] == [{
        "id": "diagram", "href": "diagram.svg", "mediaType": "image/svg+xml",
    }]
    assert all(node["type"] != "html" for node in chapter["content"])


def test_core_parses_the_spec_vault_as_neutral_document() -> None:
    document = build_document(ROOT / "spec" / "manifest.md", capability_reference())
    structural = {"document", "section", "paragraph", "text", "list", "list-item", "code"}
    references = {item["id"] for item in capability_reference()["capabilities"]}

    def nodes(chapters):
        for chapter in chapters:
            yield from chapter["content"]
            yield from nodes(chapter["children"])

    assert {node["type"] for node in nodes(document["chapters"])} <= structural | references
    assert set(document["capabilities"]) <= references
    assert all(node["type"] != "html" for node in nodes(document["chapters"]))
