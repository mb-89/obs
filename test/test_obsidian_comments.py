"""Obsidian comments (`%% … %%`) are hidden: input-model "Manifest contract" and "Chapter content"."""

import json
from pathlib import Path

import pytest

from obs.document import DocumentError, build_document
from test_vault import capability_reference


def _vault(tmp_path: Path, manifest: str, **notes: str) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text(manifest, encoding="utf-8")
    for name, body in notes.items():
        (vault / f"{name}.md").write_text(body, encoding="utf-8")
    return vault / "manifest.md"


def _tree(chapters: list[dict[str, object]]) -> list[object]:
    return [(chapter["id"], _tree(chapter["children"])) for chapter in chapters]


def test_a_manifest_line_inside_a_comment_is_no_chapter_and_the_list_continues(tmp_path) -> None:
    manifest = _vault(
        tmp_path,
        "- [[one]]\n  - [[one-a]]\n  %% - [[secret]] %%\n  - [[one-b]]\n%%\n- [[gone]]\n%%\n- [[two]]\n",
        **{name: f"{name} body.\n" for name in ("one", "one-a", "one-b", "two")},
    )

    document = build_document(manifest, capability_reference())

    assert _tree(document["chapters"]) == [("one", [("one-a", []), ("one-b", [])]), ("two", [])]
    assert document["manifest"]["abstract"] == [
        node for node in document["manifest"]["abstract"] if node["type"] != "paragraph"
    ]
    text = json.dumps(document)
    assert "secret" not in text
    assert "gone" not in text


def test_a_note_body_renders_without_its_inline_and_block_comments(tmp_path) -> None:
    manifest = _vault(
        tmp_path,
        "- [[chapter]]\n\nAbstract %%abstract note%% prose.\n",
        chapter="Before %% inline remark %% after.\n\n%%\nBlock remark.\n\nStill hidden.\n%%\n\nLast.\n",
    )

    document = build_document(manifest, capability_reference())

    text = json.dumps(document)
    for hidden in ("inline remark", "Block remark", "Still hidden", "abstract note"):
        assert hidden not in text
    for shown in ("Before", "after.", "Last.", "Abstract", "prose."):
        assert shown in text


def test_percent_signs_in_code_are_no_comment(tmp_path) -> None:
    manifest = _vault(
        tmp_path,
        "- [[chapter]]\n",
        chapter="Format `%%d%%` here.\n\n```text\n%%\nkept\n%%\n```\n",
    )

    document = build_document(manifest, capability_reference())

    text = json.dumps(document)
    assert "%%d%%" in text
    assert "%%\\nkept\\n%%" in text


def test_an_unclosed_comment_fails_naming_the_note_and_its_line(tmp_path) -> None:
    manifest = _vault(tmp_path, "- [[chapter]]\n", chapter="Shown.\n\n%% never closed\n")

    with pytest.raises(DocumentError) as raised:
        build_document(manifest, capability_reference())

    assert "chapter.md: line 3:" in str(raised.value)
