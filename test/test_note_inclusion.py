"""Recursive note inclusion: see input-model "Chapter content"."""
import json
from pathlib import Path

import pytest

from obs.document import build_document, main
from test_vault import capability_reference


ROOT = Path(__file__).parents[1]


def _vault(tmp_path: Path, notes: dict[str, str]) -> Path:
    for name, text in notes.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path / "manifest.md"


def _chapters(items: list[dict[str, object]]):
    for chapter in items:
        yield chapter
        yield from _chapters(chapter["children"])


def _links(document: dict[str, object]):
    def descend(nodes):
        for node in nodes:
            if node["type"] in {"wikilinks", "embeds"}:
                yield node["attrs"]
            yield from descend(node["children"])

    yield from descend(document["manifest"]["abstract"])
    for chapter in _chapters(document["chapters"]):
        yield from descend(chapter["content"])


def test_links_from_included_notes_include_their_targets_recursively(tmp_path) -> None:
    manifest = _vault(tmp_path, {
        "manifest.md": "- [[first]]\n",
        "first.md": "See [[second]].\n",
        "second.md": "See ![[third]].\n",
        "third.md": "End.\n",
        "unreferenced.md": "Stays out.\n",
    })

    document = build_document(manifest, capability_reference())

    assert [(chapter["id"], chapter.get("toc", True)) for chapter in document["chapters"]] == [
        ("first", True), ("second", False), ("third", False),
    ]
    assert [attrs["chapter"] for attrs in _links(document)] == ["second", "third"]
    assert document["diagnostics"] == []


def test_a_query_or_base_in_an_included_note_includes_every_selected_note(tmp_path) -> None:
    items = {f"items/item-{index:02}.md": f"---\nkind: item\n---\nSee [[detail-{index:02}]].\n"
             for index in range(12)}
    details = {f"detail-{index:02}.md": "Detail.\n" for index in range(12)}
    manifest = _vault(tmp_path, {
        "manifest.md": "- [[register]]\n- [[count]]\n",
        "register.md": "```base\nfilters: 'kind == \"item\"'\nviews:\n  - type: table\n"
                       "    order: [file.name]\n```\n\n![[open.base]]\n",
        "open.base": "filters: 'status == \"open\"'\nviews:\n  - type: table\n    order: [file.name]\n",
        "open-point.md": "---\nstatus: open\n---\nOpen.\n",
        "count.md": "---\nquery: {from: owner, where: [{field: severity, exists: true}]}\n---\nCount.\n",
        "owner.md": "---\nquery: {where: [{field: kind, equals: finding}]}\n---\nOwner.\n",
        "finding.md": "---\nkind: finding\nseverity: high\n---\nFinding.\n",
        "other-finding.md": "---\nkind: finding\n---\nNo severity.\n",
        "unselected.md": "---\nkind: other\n---\nStays out.\n",
        **items, **details,
    })

    document = build_document(manifest, capability_reference())
    identifiers = [chapter["id"] for chapter in document["chapters"]]

    assert identifiers[:2] == ["register", "count"]
    assert {f"items-item-{index:02}" for index in range(12)} <= set(identifiers)
    assert {f"detail-{index:02}" for index in range(12)} <= set(identifiers)
    assert {"open-point", "owner", "finding", "other-finding"} <= set(identifiers)
    assert "unselected" not in identifiers
    assert len(identifiers) == len(set(identifiers))
    assert identifiers[2:] == sorted(identifiers[2:], key=lambda identifier: next(
        record["path"].casefold() for record in document["records"]
        if record["id"] == identifier
    ))


def test_a_link_cycle_terminates_with_each_note_once(tmp_path) -> None:
    manifest = _vault(tmp_path, {
        "manifest.md": "- [[a]]\n",
        "a.md": "[[b]] [[a]]\n",
        "b.md": "[[c]] [[a]]\n",
        "c.md": "[[a]] [[b]] [[c]]\n",
    })

    document = build_document(manifest, capability_reference())

    assert [chapter["id"] for chapter in _chapters(document["chapters"])] == ["a", "b", "c"]


def test_a_link_to_a_missing_note_warns_with_source_target_and_remedy(tmp_path, capsys) -> None:
    manifest = _vault(tmp_path, {
        "manifest.md": "- [[chapter]]\n",
        "chapter.md": "See [[missing-note]] and [[missing-note|again]].\n",
    })

    document = build_document(manifest, capability_reference())

    assert [attrs["chapter"] for attrs in _links(document)] == [None, None]
    assert document["diagnostics"] == [{
        "level": "warning",
        "message": "Link target does not exist in chapter.md: [[missing-note]]; "
                   "create missing-note.md in the vault or correct the link.",
    }]
    reference = tmp_path / "reference.json"
    reference.write_text(json.dumps(capability_reference()), encoding="utf-8")
    assert main([
        "--source", str(manifest), "--document", str(tmp_path / "document.json"),
        "--capability-reference", str(reference),
    ]) == 0
    assert capsys.readouterr().err == (
        "obs-document: warning: Link target does not exist in chapter.md: [[missing-note]]; "
        "create missing-note.md in the vault or correct the link.\n"
    )


def test_links_resolve_vault_relative_and_to_home(tmp_path) -> None:
    manifest = _vault(tmp_path, {
        "manifest.md": "---\nsummary: Starts at [[part/intro]].\n---\n- [[part/intro]]\n",
        "part/intro.md": "[[part/sibling]] [[manifest]] [[home]]\n",
        "part/sibling.md": "---\nsee: '[[linked-from-metadata]]'\n---\nSibling.\n",
        "linked-from-metadata.md": "Linked.\n",
        "home.md": "A note named home.\n",
    })

    document = build_document(manifest, capability_reference())

    assert [attrs["chapter"] for attrs in _links(document)] == ["part-sibling", "home", "home-2"]
    assert "linked-from-metadata" in [chapter["id"] for chapter in document["chapters"]]


def test_an_ambiguous_note_name_is_an_error_naming_source_and_remedy(tmp_path) -> None:
    manifest = _vault(tmp_path, {
        "manifest.md": "- [[chapter]]\n",
        "chapter.md": "[[note]]\n",
        "a/note.md": "",
        "b/note.md": "",
    })

    with pytest.raises(ValueError) as error:
        build_document(manifest, capability_reference())

    assert str(error.value) == (
        "Ambiguous note name in chapter.md: [[note]] matches a/note.md, b/note.md; "
        "link the vault path instead."
    )


def test_spec_document_leaves_no_link_to_an_existing_note_unresolved() -> None:
    document = build_document(ROOT / "spec" / "manifest.md", capability_reference())

    assert [attrs["target"] for attrs in _links(document) if attrs["chapter"] is None] == []
    assert document["diagnostics"] == []
