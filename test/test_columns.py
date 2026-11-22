"""Two-column blocks (capabilities/columns): the core reads ``|||`` delimiter lines into ``columns`` nodes.

Reader: whoever changes how the core reads a two-column block, its Document node or its input errors.

Splitting a body into blocks, reading their weights and finding malformed blocks is one pure
function, ``obs.note.column_blocks``; the rest is the build, through ``build_document`` and the
``obs-document`` command. The adapter html's side of the interim adapter's cases is its
test/test_columns.py and test_columns_browser.py, in its own repository.
"""
import json
from pathlib import Path

import pytest

from obs.document import AdapterError, DocumentError, _deliver, build_document, main
from obs.note import ColumnBlock, ColumnsError, column_blocks
from schemas import capability_reference


OWNER = "capabilities/columns"
CARDS = {"version": 1, "cards": [{"title": "Coverage", "body": "See [[chapter#Details]].",
                                  "metrics": [{"label": "Items", "where": []}]}]}
BASE = "```base\nviews:\n  - type: table\n    order: [file.name]\n```\n"
# The interim adapter's ten malformed bodies (its test_columns.py), a %% comment for its HTML one.
MALFORMED = {
    "unclosed after the first column": ("|||\nLeft\n", 1),
    "unclosed after the second column": ("|||\nLeft\n|||\nRight\n", 1),
    "empty first column": ("|||\n|||\nRight\n|||\n", 1),
    "first column only a comment": ("|||\n%% invisible %%\n|||\nRight\n|||\n", 1),
    "empty second column": ("|||\nLeft\n|||\n|||\n", 1),
    "nested": ("|||\nLeft\n|||\nInner\n|||\nRight\n|||\n", 2),
    "in a blockquote": ("> |||\n> Left\n> |||\n> Right\n> |||\n", 1),
    "in a list item": ("- |||\n\n  Left\n\n  |||\n\n  Right\n\n  |||\n", 1),
    "weight out of range": ("||| 0:2\nLeft\n|||\nRight\n|||\n", 1),
    "weights on the separator": ("|||\nLeft\n||| 1:2\nRight\n|||\n", 1),
}


def _vault(tmp_path: Path, chapter: str, home: str = "") -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text(f"- [[chapter]]\n\n{home}", encoding="utf-8")
    (vault / "chapter.md").write_text(chapter, encoding="utf-8")
    return vault


def _build(tmp_path: Path, chapter: str, home: str = "", reference: dict | None = None) -> dict:
    return build_document(_vault(tmp_path, chapter, home) / "manifest.md", reference or capability_reference())


def _columns(nodes: list[dict]) -> list[dict]:
    return [node for node in nodes if node["type"] == "columns"]


def _types(nodes: list[dict]) -> list[str]:
    return [node["type"] for node in nodes]


def test_the_lines_of_a_body_split_into_blocks_with_their_weights_and_delimiter_lines() -> None:
    body = ("```text\n|||\n|||\n|||\n```\n\n    |||\n\ninline ||| stays prose\n\n"
            "||| 1:2\nLeft `|||`.\n|||\nRight.\n|||\n\n"
            "|||\nSecond left.\n|||\nSecond right.\n|||\n")

    assert column_blocks(body) == [ColumnBlock(1, (1, 2), 10, 12, 14), ColumnBlock(2, (1, 1), 16, 18, 20)]
    assert column_blocks("No delimiter here.\n") == []


@pytest.mark.parametrize("name", MALFORMED)
def test_each_malformed_body_is_a_columns_error_naming_its_block(name: str) -> None:
    body, number = MALFORMED[name]
    body = body.replace("%% invisible %%\n", "")  # The note reader removes comments before this.

    with pytest.raises(ColumnsError) as raised:
        column_blocks(body)

    assert raised.value.number == number
    assert str(raised.value).startswith(f"columns block {number}: ")
    assert OWNER in raised.value.remedy


@pytest.mark.parametrize("name", MALFORMED)
def test_each_malformed_body_fails_the_build_naming_the_note_and_the_block(tmp_path: Path, name: str) -> None:
    body, number = MALFORMED[name]

    with pytest.raises(DocumentError) as raised:
        _build(tmp_path, body)

    assert str(raised.value).startswith(f"{tmp_path.resolve() / 'vault' / 'chapter.md'}: columns block {number}: ")
    assert str(raised.value).endswith(f"see {OWNER}.")


def test_weights_are_two_integers_from_one_to_eight() -> None:
    for weights in ("1:9", "2", "a:b", "1:2:3", "1 : 2"):
        with pytest.raises(ColumnsError) as raised:
            column_blocks(f"||| {weights}\nLeft\n|||\nRight\n|||\n")
        assert raised.value.number == 1 and raised.value.line == 0
    with pytest.raises(ColumnsError) as raised:
        column_blocks("|||\nLeft\n|||\nRight\n||| 1:1\n")
    assert raised.value.line == 4
    assert column_blocks("||| 8:1\nLeft\n|||\nRight\n|||\n")[0].weights == (8, 1)
    assert column_blocks("   |||   \nLeft\n|||\nRight\n|||\n")[0].weights == (1, 1)


def test_columns_hold_cards_a_base_table_a_mark_and_a_heading_a_link_targets(tmp_path: Path) -> None:
    document = _build(tmp_path, (
        "||| 1:2\n```cards\n" + json.dumps(CARDS) + "\n```\n"
        "|||\n## Details\n\nQuestion #mark/open_point/columns\n\n" + BASE + "|||\n"))

    [block] = _columns(document["chapters"][0]["content"])
    first, second = block["children"]
    assert block["attrs"] == {"weights": [1, 2]}
    assert _types(block["children"]) == ["document", "document"]
    assert first["attrs"] == {} and second["attrs"] == {}
    assert _types(first["children"]) == ["cards-metrics"]
    assert _types(second["children"]) == ["section", "paragraph", "bases"]
    link = first["children"][0]["children"][0]["children"][0]["children"][1]
    assert link["attrs"] | {"chapter": "chapter"} == {"target": "chapter", "chapter": "chapter",
                                                      "heading": "Details", "label": "Chapter > Details"}
    assert second["children"][1]["children"][-1] == {
        "type": "marks", "attrs": {"category": "open_point", "id": "columns"}, "children": []}
    assert {"columns", "cards-metrics", "bases", "marks", "wikilinks"} <= set(document["capabilities"])
    [tag] = [record for record in document["records"] if record["type"] == "tag"]
    assert tag["fields"]["text"] == "Question"


def test_delimiters_end_a_paragraph_and_a_table_and_stay_text_in_code(tmp_path: Path) -> None:
    document = _build(tmp_path, (
        "```text\n|||\n|||\n|||\n```\n\n    |||\n\ninline ||| stays prose\n\n"
        "|||\n| Left | Value |\n|---|---|\n| One | 1 |\n"
        "|||\n| Right | Value |\n|---|---|\n| Two | 2 |\n|||\n"
        "|||\nSecond left.\n|||\nSecond right.\n|||\n"))
    content = document["chapters"][0]["content"]

    assert content[2]["attrs"]["language"] == "text" and content[2]["text"] == "|||\n|||\n|||\n"
    assert content[3]["type"] == "code" and content[3]["text"] == "|||\n"
    assert content[4]["children"][0]["text"] == "inline ||| stays prose"
    first, second = _columns(content)
    tables = [column["children"] for column in first["children"]]
    assert [[node["type"] for node in column] for column in tables] == [["table"], ["table"]]
    assert [len(column[0]["children"]) for column in tables] == [2, 2]
    assert [paragraph["children"][0]["text"] for column in second["children"] for paragraph in column["children"]] \
        == ["Second left.", "Second right."]


def test_a_block_in_the_manifest_home_works_as_one_in_a_chapter(tmp_path: Path) -> None:
    document = _build(tmp_path, "# Details\n", "|||\nLeft **overview**.\n|||\n" + BASE + "|||\n")

    [block] = _columns(document["manifest"]["abstract"])
    assert [_types(column["children"]) for column in block["children"]] == [["paragraph"], ["bases"]]
    assert block["attrs"]["weights"] == [1, 1]


def test_the_block_and_its_columns_keep_their_ids_when_a_column_or_the_weights_change(tmp_path: Path) -> None:
    def ids(body: str, name: str) -> list[str]:
        (tmp_path / name).mkdir()
        [block] = _columns(_build(tmp_path / name, f"# Topic\n\n{body}")["chapters"][0]["content"])
        return [block["id"], *(column["id"] for column in block["children"]),
                *(node["id"] for column in block["children"] for node in column["children"])]

    before = ids("||| 1:2\nClaim.\n|||\nEvidence.\n|||\n", "before")
    after = ids("|||\nAnother claim.\n|||\nEvidence.\n|||\n", "after")

    assert all(before) and len(set(before)) == 5
    assert after[:3] == before[:3] and after[4] == before[4] and after[3] != before[3]


def test_without_the_capability_delimiter_lines_parse_as_they_did(tmp_path: Path) -> None:
    body = "|||\nLeft\n|||\nRight\n|||\n\n|||\nUnclosed\n"
    reference = capability_reference()
    reference["capabilities"] = [item for item in reference["capabilities"] if item["id"] != "columns"]

    document = _build(tmp_path, body, reference=reference)

    assert "columns" not in document["capabilities"]
    texts = [child.get("text") for node in document["chapters"][0]["content"] if node["type"] == "paragraph"
             for child in node["children"] if child["type"] == "text" and child["text"].strip()]
    assert texts == ["|||", "Left", "|||", "Right", "|||", "|||", "Unclosed"]


def test_an_adapter_that_does_not_declare_columns_refuses_a_document_that_uses_it(tmp_path: Path) -> None:
    document = _build(tmp_path, "|||\nLeft\n|||\nRight\n|||\n")
    reference = capability_reference()
    adapter = {"name": "plain", "contractVersion": 1, "command": ["never-run"],
               "capabilities": sorted(set(document["capabilities"]) - {"columns"} | {"markdown"})}

    with pytest.raises(AdapterError, match="columns"):
        _deliver(adapter, [], document, tmp_path / "document.json", tmp_path / "out.html", reference)


def test_a_failing_source_check_names_the_block_and_writes_nothing(tmp_path: Path) -> None:
    vault = _vault(tmp_path, "|||\nUnclosed column.\n")
    reference = tmp_path / "capabilities.json"
    reference.write_text(json.dumps(capability_reference()), encoding="utf-8")
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    with pytest.raises(SystemExit) as raised:
        main(["--source", str(vault), "--document", str(tmp_path / "document.json"),
              "--capability-reference", str(reference)])

    assert "chapter.md: columns block 1: " in str(raised.value.code)
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == before


def test_a_lint_inside_a_column_names_its_own_note_line(tmp_path: Path) -> None:
    document = _build(tmp_path, "# Topic\n\n|||\nShort.\n|||\n" + "A long column paragraph. " * 30 + "\n|||\n")

    [warning] = [item["message"] for item in document["diagnostics"]]
    assert warning.startswith("chapter.md:6: long paragraph")
