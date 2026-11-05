"""Ignored notes: see markdown-frontmatter ("Ignored notes") and input-model "Chapter content"."""
from pathlib import Path

import pytest

from obs.document import DocumentError, build_document
from obs.selection import base_selects, conditions_select
from test_note_inclusion import _vault
from test_vault import capability_reference


ROOT = Path(__file__).parents[1]
MATCH_ALL_BASE = {"views": [{"type": "table"}]}


def _notes(records):
    return [record for record in records if record["type"] == "note"]


def _selected(records, selects) -> list[str]:
    return [record["path"] for record in _notes(records) if selects(record["fields"], record["path"])]


def _base_selected(records, definition) -> list[str]:
    selects = base_selects(definition)
    return [record["path"] for record in _notes(records) if selects(record, record)]


def test_a_non_boolean_ignored_field_names_the_note_the_field_and_the_remedy(tmp_path) -> None:
    manifest = _vault(tmp_path, {
        "manifest.md": "- [[draft]]\n",
        "draft.md": "---\nignored: yes please\n---\nDraft.\n",
    })

    with pytest.raises(DocumentError) as error:
        build_document(manifest, capability_reference())

    message = str(error.value)
    assert "draft.md" in message
    assert "ignored" in message
    assert "true or false" in message


def test_a_query_or_base_never_selects_an_ignored_note_and_its_count_excludes_it(tmp_path) -> None:
    manifest = _vault(tmp_path, {
        "manifest.md": "- [[count]]\n- [[register]]\n",
        "count.md": "---\nquery: {where: [{field: kind, equals: finding}]}\n---\nCount.\n",
        "register.md": "```base\nfilters: 'kind == \"finding\"'\nviews:\n  - type: table\n    order: [file.name]\n```\n",
        "finding.md": "---\nkind: finding\n---\nSelected.\n",
        "hidden.md": "---\nkind: finding\nignored: true\n---\nIgnored.\n",
        "visible.md": "---\nkind: finding\nignored: false\n---\nNot ignored.\n",
    })

    document = build_document(manifest, capability_reference())
    query = [{"field": "kind", "equals": "finding"}]
    count = len(_selected(document["records"], lambda fields, path: conditions_select(query, fields, path)))

    assert [chapter["id"] for chapter in document["chapters"]] == ["count", "register", "finding", "visible"]
    assert count == 2
    assert _base_selected(document["records"], {"filters": 'kind == "finding"', **MATCH_ALL_BASE}) == [
        "finding.md", "visible.md",
    ]


def test_an_ignored_note_listed_in_the_manifest_or_linked_from_an_included_note_is_included(tmp_path) -> None:
    manifest = _vault(tmp_path, {
        "manifest.md": "- [[listed]]\n- [[chapter]]\n",
        "listed.md": "---\nignored: true\n---\nListed.\n",
        "chapter.md": "See [[linked]].\n",
        "linked.md": "---\nignored: true\n---\nLinked.\n",
    })

    document = build_document(manifest, capability_reference())

    assert [chapter["id"] for chapter in document["chapters"]] == ["listed", "chapter", "linked"]
    assert document["diagnostics"] == []


def test_the_record_of_an_ignored_note_says_so(tmp_path) -> None:
    manifest = _vault(tmp_path, {
        "manifest.md": "---\nignored: true\n---\n- [[chapter]]\n",
        "chapter.md": "Chapter.\n",
    })

    records = {record["path"]: record for record in _notes(build_document(manifest, capability_reference())["records"])}

    assert records["manifest.md"]["ignored"] is True
    assert "ignored" not in records["chapter.md"]


def test_the_spec_manifest_is_not_selected_by_a_query_or_base_matching_all_notes(spec_document) -> None:
    records = spec_document["records"]
    every_query = _selected(records, lambda fields, path: conditions_select([], fields, path))

    assert "manifest.md" not in every_query
    assert "manifest.md" not in _base_selected(records, MATCH_ALL_BASE)
    assert len(every_query) == len(_notes(records)) - 1


def test_an_ignored_note_is_not_a_member_of_a_base_members_projection_that_would_select_it(tmp_path) -> None:
    members = {"views": [{"type": "table", "obsHtml": {"members": [{"path": "hidden.md"}, {"path": "finding.md"}]}}]}
    manifest = _vault(tmp_path, {
        "manifest.md": "- [[register]]\n",
        "register.md": (
            "```base\nviews:\n  - type: table\n    order: [file.name]\n"
            "    obsHtml:\n      members:\n        - path: hidden.md\n        - path: finding.md\n```\n"
        ),
        "finding.md": "Selected.\n",
        "hidden.md": "---\nignored: true\n---\nIgnored.\n",
    })

    document = build_document(manifest, capability_reference())

    assert [chapter["id"] for chapter in document["chapters"]] == ["register", "finding"]
    assert _base_selected(document["records"], members) == ["finding.md"]
