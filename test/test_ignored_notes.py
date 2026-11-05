"""Ignored notes: see markdown-frontmatter ("Ignored notes") and input-model "Chapter content"."""
from pathlib import Path

import pytest

from obs.document import DocumentError, build_document
from obs.selection import base_selects, conditions_select
from test_note_inclusion import _vault
from test_vault import capability_reference


ROOT = Path(__file__).parents[1]
MATCH_ALL_BASE = {"views": [{"type": "table"}]}


def _selected(records, selects) -> list[str]:
    return [record["path"] for record in records if selects(record["fields"], record["path"])]


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