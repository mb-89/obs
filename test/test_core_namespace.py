"""The core reads only its own namespace `obs` (input-model#Core and adapter namespaces).

An adapter's namespace (`obsHtml` for obs-html) is the adapter's alone: the core neither reads nor
validates it. A key the core used to read there is an input error naming the new key. Errors are
matched by their field path and owner reference (AGENTS.md), never by wording.
"""
from pathlib import Path
import re

import pytest

from obs.capabilities import build_capability_reference
from obs.document import DocumentError, build_document

ROOT = Path(__file__).parents[1]
RECORD_TYPES = ("note", "chapter", "tag", "glossary", "documentMetadata", "documentHistory")


def _vault(tmp_path: Path, base: str) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text("# Chapter\n\n![[x.base]]\n", encoding="utf-8")
    (vault / "x.base").write_text(base, encoding="utf-8")
    for name in ("a", "b", "c"):
        (vault / f"{name}.md").write_text("---\nkind: point\n---\n", encoding="utf-8")
    return vault


def _build(vault: Path) -> dict[str, object]:
    capabilities = ROOT / "spec" / "capabilities"
    return build_document(vault / "manifest.md",
                          build_capability_reference(capabilities, capabilities / "coverage.json"))


def _message(vault: Path) -> str:
    with pytest.raises(DocumentError) as raised:
        _build(vault)
    return str(raised.value)


VIEW = "views:\n  - type: table\n    name: Points\n    order: [file.name]\n"


@pytest.mark.parametrize(("base", "field"), [
    (VIEW + "    obs: {records: nonsense}\n", "views[0].obs.records"),
    ("obs: {records: nonsense}\n" + VIEW, "obs.records"),
])
def test_an_unknown_record_type_names_the_note_the_value_and_the_six_types(tmp_path, base, field) -> None:
    vault = _vault(tmp_path, base)

    message = _message(vault)

    assert message.startswith(f"{vault / 'x.base'}: {field}: "), message
    assert "nonsense" in message
    assert all(f'"{kind}"' in message for kind in RECORD_TYPES), message
    assert "; see capabilities/bases." in message


MOVED = {
    "view records": (VIEW + "    obsHtml: {records: tag}\n", "views[0].obsHtml.records", "views[0].obs.records"),
    "base records": ("obsHtml: {records: tag}\n" + VIEW, "obsHtml.records", "obs.records"),
    "view members": (VIEW + "    obsHtml:\n      members:\n        - path: a.md\n",
                     "views[0].obsHtml.members", "views[0].obs.members"),
    "base members": ("obsHtml:\n  members:\n    - path: a.md\n" + VIEW, "obsHtml.members", "obs.members"),
}


@pytest.mark.parametrize("key", MOVED)
def test_a_base_key_the_core_reads_under_the_adapter_namespace_names_its_new_key(tmp_path, key) -> None:
    base, old, new = MOVED[key]
    vault = _vault(tmp_path, base)

    message = _message(vault)

    assert message.startswith(f"{vault / 'x.base'}: {old}: "), message
    assert new in message
    assert "; see capabilities/bases." in message


@pytest.mark.parametrize(("card", "old", "new"), [
    ('"obsHtml": {"metricsFrom": {"sourceNote": "a", "property": "p", "labelProperty": "l", '
     '"distinctProperty": "d", "where": []}}', "cards[0].obsHtml.metricsFrom", "cards[0].obs.metricsFrom"),
    ('"metrics": [{"label": "L", "where": [], "obsHtml": {"projection": "review.current"}}]',
     "cards[0].metrics[0].obsHtml.projection", "cards[0].metrics[0].obs.projection"),
])
def test_a_card_key_the_core_reads_under_the_adapter_namespace_names_its_new_key(tmp_path, card, old, new) -> None:
    vault = _vault(tmp_path, VIEW)
    (vault / "chapter.md").write_text(
        f'```cards\n{{"version": 1, "cards": [{{"title": "T", "body": "", {card}}}]}}\n```\n', encoding="utf-8",
    )

    message = _message(vault)

    assert message.startswith(f"{vault / 'chapter.md'}: cards fence 1, {old}: "), message
    assert new in message
    assert "; see capabilities/cards-metrics." in message


def test_a_document_profile_under_the_adapter_namespace_names_its_new_key(tmp_path) -> None:
    vault = _vault(tmp_path, VIEW)
    (vault / "chapter.md").write_text("---\nobsHtml: {document: false}\n---\nBody.\n", encoding="utf-8")

    message = _message(vault)

    assert message.startswith(f"{vault / 'chapter.md'}: obsHtml.document: "), message
    assert "obs.document" in message
    assert "; see capabilities/profiles." in message


@pytest.mark.parametrize(("frontmatter", "field"), [
    ("obs: {document: maybe}", "obs.document"),
    ("obs: {layout: paged}", "obs.layout"),
])
def test_the_core_validates_every_key_of_its_note_profile(tmp_path, frontmatter, field) -> None:
    vault = _vault(tmp_path, VIEW)
    (vault / "chapter.md").write_text(f"---\n{frontmatter}\n---\nBody.\n", encoding="utf-8")

    message = _message(vault)

    assert message.startswith(f"{vault / 'chapter.md'}: {field}: "), message
    assert "; see capabilities/profiles." in message


def test_an_unknown_key_in_a_views_core_namespace_is_an_input_error(tmp_path) -> None:
    vault = _vault(tmp_path, VIEW + "    obs: {wide: true}\n")

    message = _message(vault)

    assert message.startswith(f"{vault / 'x.base'}: views[0].obs.wide: "), message
    assert "; see capabilities/bases." in message


def test_the_core_does_not_interpret_the_adapter_namespace(tmp_path) -> None:
    vault = _vault(tmp_path, "obsHtml: {maxRows: 3}\n" + VIEW + "    obsHtml: {wide: true, anything: [1]}\n"
                   "    obs: {records: note}\n")
    (vault / "chapter.md").write_text(
        "---\nobsHtml: {layout: anything, query: 7}\nobs: {document: true}\n---\n# Chapter\n\n![[x.base]]\n",
        encoding="utf-8",
    )
    (vault / "manifest.md").write_text(
        "---\ntitle: T\nobs: {document: true}\nobsHtml: {layout: paged}\nobsPdf: {paper: A4}\n---\n\n- [[chapter]]\n",
        encoding="utf-8",
    )

    document = _build(vault)

    keys = {record["fields"]["key"] for record in document["records"] if record["type"] == "documentMetadata"}
    assert keys == {"title"}


MOVED_TABLE = re.compile(r"^MOVED_KEYS\b.*?^}\n", re.MULTILINE | re.DOTALL)


def test_no_core_source_file_reads_an_adapter_key() -> None:
    """The adapter's namespace appears in the core only in the table of keys that moved out of it."""
    readers = []
    for path in sorted((ROOT / "src" / "obs").iterdir()):
        if path.suffix not in {".py", ".json"}:
            continue
        text = path.read_text(encoding="utf-8")
        if path.name == "input.py":
            text = MOVED_TABLE.sub("", text, count=1)
        readers += [f"{path.name}:{number}" for number, line in enumerate(text.splitlines(), 1)
                    if "obsHtml" in line]
    assert readers == []
