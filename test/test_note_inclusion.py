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


def test_a_query_selects_by_marks_and_ignores_case(tmp_path) -> None:
    """capabilities/queries#Conditions: marks are selectable; text and names ignore case."""
    manifest = _vault(tmp_path, {
        "manifest.md": "- [[count]]\n",
        "count.md": "---\nquery: {where: [{field: mark.open_point, exists: true}]}\n---\nCount.\n",
        "marked.md": "Does it hold? #mark/open_point/holds\n",
        "coded.md": "`#mark/open_point/code` is code.\n",
        "cased.md": "---\nStatus: OPEN\n---\nCased.\n",
        "exact.md": "---\nquery: {where: [{field: status, equals: open}]}\n---\nExact.\n",
        "flagged.md": "---\nquery: {where: [{field: status, equals: Shut, matchCase: true}]}\n---\nFlag.\n",
        "shut.md": "---\nstatus: shut\n---\nShut.\n",
    })
    (tmp_path / "manifest.md").write_text("- [[count]]\n- [[exact]]\n- [[flagged]]\n", encoding="utf-8")

    identifiers = {chapter["id"] for chapter in build_document(manifest, capability_reference())["chapters"]}

    assert {"marked", "cased"} <= identifiers
    assert not {"coded", "shut"} & identifiers


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

    assert [attrs["chapter"] for attrs in _links(document)] == [
        "part-intro", "part-sibling", "home", "home-2", "linked-from-metadata",
    ]
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


def test_spec_document_leaves_no_link_to_an_existing_note_unresolved(spec_document) -> None:
    document = spec_document

    assert [attrs["target"] for attrs in _links(document) if attrs["chapter"] is None] == []
    assert document["diagnostics"] == []


INVALID_NOTES = {
    "quantity": "---\nkind: quantity\naliases: [maxLoad]\nsource: '[[chapter]]'\nvalue: 12 kN\n---\n",
    "profile": "---\nobsHtml: {layout: sideways}\n---\n",
    "query": "---\nquery: {where: invalid}\n---\n",
}


@pytest.mark.parametrize("contract", sorted(INVALID_NOTES))
def test_an_invalid_note_nothing_reaches_does_not_fail_the_build(tmp_path, contract) -> None:
    manifest = _vault(tmp_path, {
        "manifest.md": "- [[chapter]]\n",
        "chapter.md": "Chapter.\n",
        "stray.md": INVALID_NOTES[contract],
    })

    document = build_document(manifest, capability_reference())

    assert [chapter["id"] for chapter in document["chapters"]] == ["chapter"]


def test_an_invalid_quantity_note_an_included_note_links_fails_with_its_message(tmp_path) -> None:
    manifest = _vault(tmp_path, {
        "manifest.md": "- [[chapter]]\n",
        "chapter.md": "See [[stray]].\n",
        "stray.md": INVALID_NOTES["quantity"],
    })

    with pytest.raises(ValueError) as error:
        build_document(manifest, capability_reference())

    assert str(error.value) == (
        f"{tmp_path / 'stray.md'}: value: must be a finite number, not '12 kN'. "
        "Write the bare number and put the unit in unit; see capabilities/quantities."
    )


def test_a_card_includes_its_source_notes_and_populations(tmp_path) -> None:
    """input-model "Chapter content": card references are inclusion edges."""
    cards = json.dumps({"version": 1, "cards": [{
        "title": "Series", "body": "",
        "obsHtml": {"metricsFrom": {
            "sourceNote": "lists/categories", "property": "categories", "labelProperty": "name",
            "distinctProperty": "field", "where": [{"field": "kind", "equals": "counted"}],
            "link": {"note": "register", "groupProperty": "category"},
        }},
        "metrics": [{
            "label": "Closed", "where": [{"field": "status", "equals": "closed"}],
            "denominator": [{"field": "status", "exists": True}],
        }],
    }]})
    manifest = _vault(tmp_path, {
        "manifest.md": "- [[dashboard]]\n",
        "dashboard.md": f"```cards\n{cards}\n```\n",
        "lists/categories.md": "---\nignored: true\ncategories: [{name: a, field: b}]\n---\n",
        "register.md": "Register.\n",
        "counted.md": "---\nkind: counted\n---\n",
        "open.md": "---\nstatus: open\n---\n",
        "unrelated.md": "Stays out.\n",
    })

    identifiers = [chapter["id"] for chapter in build_document(manifest, capability_reference())["chapters"]]

    assert identifiers == ["dashboard", "counted", "lists-categories", "open", "register"]


def test_a_card_source_note_that_does_not_resolve_names_card_field_and_remedy(tmp_path) -> None:
    cards = json.dumps({"version": 1, "cards": [{"title": "Series", "body": "", "obsHtml": {
        "metricsFrom": {"sourceNote": "missing", "property": "p", "labelProperty": "l",
                        "distinctProperty": "d", "where": []},
    }}]})
    manifest = _vault(tmp_path, {
        "manifest.md": "- [[dashboard]]\n",
        "dashboard.md": f"```cards\n{cards}\n```\n",
    })

    with pytest.raises(ValueError) as error:
        build_document(manifest, capability_reference())

    assert str(error.value) == (
        "Card metricsFrom.sourceNote does not resolve in dashboard.md: missing; "
        "name a vault note by its path without .md."
    )


def test_empty_conditions_select_every_selectable_note_so_the_build_validates_it(tmp_path) -> None:
    manifest = _vault(tmp_path, {
        "manifest.md": "- [[chapter]]\n",
        "chapter.md": "---\nquery: {where: []}\n---\nChapter.\n",
        "stray.md": INVALID_NOTES["profile"],
        "hidden.md": "---\nignored: true\nobsHtml: {layout: sideways}\n---\n",
    })

    with pytest.raises(ValueError) as error:
        build_document(manifest, capability_reference())

    assert str(error.value).startswith(f"{tmp_path / 'stray.md'}: obsHtml.layout: ")
    (tmp_path / "stray.md").write_text("Stray.\n", encoding="utf-8")
    chapters = [chapter["id"] for chapter in build_document(manifest, capability_reference())["chapters"]]
    assert "stray" in chapters and "hidden" not in chapters
