from pathlib import Path

import pytest
import yaml

from obs_html_interim.content import (
    Chapter, base_note_value, collect_notes, compile_base_filter, read_chapter_content, read_manifest,
)


ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "spec" / "manifest.md"


@pytest.fixture
def spec_document_records(spec_document) -> list[dict[str, object]]:
    return spec_document["records"]


@pytest.fixture
def spec_records(spec_document_records) -> list[dict[str, object]]:
    return [record for record in spec_document_records if record["type"] == "note"]


def _authored_base_filters() -> list[object]:
    filters = []
    for path in sorted((ROOT / "spec").rglob("*.md")):
        source = path.read_text(encoding="utf-8")
        for block in source.split("```base\n")[1:]:
            definition = yaml.safe_load(block.split("\n```", 1)[0])
            if isinstance(definition, dict) and "filters" in definition:
                filters.append(definition["filters"])
    return filters


def test_spec_document_has_a_note_record_per_capability(spec_records, spec_document_records) -> None:
    capabilities = {
        record["path"] for record in spec_records if record["fields"].get("kind") == "capability"
    }
    assert "capabilities/bases.md" in capabilities
    assert len({record["id"] for record in spec_document_records}) == len(spec_document_records)
    bases = next(record for record in spec_records if record["path"] == "capabilities/bases.md")
    assert bases["id"] == "capabilities-bases"
    assert bases["fields"]["capability"]["id"] == "bases"


def test_base_filters_on_records_select_the_adapter_vault_collection(spec_records) -> None:
    manifest = read_manifest(MANIFEST)
    home = Chapter(0, "Home", "home", MANIFEST, "", "home")
    home_document = read_chapter_content(home, manifest.metadata["subtitle"])
    _, _, index = collect_notes(MANIFEST, manifest.chapters, home, home_document, manifest.metadata)
    vault = MANIFEST.resolve().parent
    collected = {
        path.relative_to(vault).as_posix(): metadata for path, metadata in index.metadata_by_path.items()
    }
    assert {record["path"] for record in spec_records} == set(collected)
    filters = _authored_base_filters()
    assert 'kind == "capability"' in filters
    for filters_ in filters:
        matches = compile_base_filter(filters_)
        from_records = {
            record["path"] for record in spec_records
            if matches(lambda field, record=record: base_note_value(record["fields"], record["path"], field))
        }
        from_vault = {
            path for path, metadata in collected.items()
            if matches(lambda field, path=path, metadata=metadata: base_note_value(metadata, path, field))
        }
        assert from_records == from_vault, filters_


def test_note_outside_the_vault_is_refused_with_its_source_and_remedy(tmp_path) -> None:
    from obs.vault import VaultError, build_document as build_vault_document

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("# Home\n", encoding="utf-8")
    (tmp_path / "outside.md").write_text("---\nkind: item\n---\n", encoding="utf-8")
    try:
        (vault / "linked.md").symlink_to(tmp_path / "outside.md")
    except OSError:
        pytest.skip("symbolic links are unavailable")
    with pytest.raises(VaultError, match=r"Note path escapes the vault: linked\.md \(vault .*\); replace"):
        build_vault_document(vault / "manifest.md")


RECORD_BADGES = (
    "https://img.shields.io/badge/Obsidian-7C3AED?style=for-the-badge",
    "https://img.shields.io/badge/HTML5-E34F26?style=for-the-badge",
)


def _record_vault(tmp_path: Path, capability: str) -> Path:
    """A manifest listing x, with a two-badge subtitle, and a record-only capability note."""
    vault = tmp_path / "vault"
    vault.mkdir()
    subtitle = f"![Obsidian]({RECORD_BADGES[0]}) → ![HTML5]({RECORD_BADGES[1]})"
    (vault / "manifest.md").write_text(f"---\nsubtitle: '{subtitle}'\n---\n- [[x]]\n", encoding="utf-8")
    (vault / "x.md").write_text("# X\n", encoding="utf-8")
    (vault / "cap.md").write_text(f"---\nkind: capability\ncapability:\n{capability}---\n# Cap\n",
                                  encoding="utf-8")
    return vault


def _record_document(vault: Path, remote_images) -> dict[str, object]:
    from obs.document import build_document as build_checked_document
    from test_vault import capability_reference

    served, _ = remote_images
    for href in RECORD_BADGES:
        served[href] = (b'<svg xmlns="http://www.w3.org/2000/svg"/>', "image/svg+xml")
    return build_checked_document(vault / "manifest.md", capability_reference())


def _record_fields(document: dict[str, object], path: str) -> dict[str, list[dict[str, object]]]:
    [record] = [item for item in document["records"] if item.get("path") == path]
    return {node["attrs"]["name"]: node["children"] for node in record["fieldNodes"]}


def test_a_record_only_note_s_wikilink_arrives_as_a_resolved_field_node(tmp_path, remote_images) -> None:
    document = _record_document(_record_vault(tmp_path, '  dependsOn: ["[[x]]"]\n'), remote_images)

    [link] = _record_fields(document, "cap.md")["capability.dependsOn.0"]
    assert link["type"] == "wikilinks"
    assert (link["attrs"]["target"], link["attrs"]["chapter"]) == ("x", "x")
    assert [chapter["id"] for chapter in document["chapters"]] == ["x"]
    assert all("fieldNodes" in record for record in document["records"] if record["type"] == "note")


def test_the_manifest_record_s_subtitle_arrives_as_image_nodes_of_its_two_assets(tmp_path, remote_images) -> None:
    document = _record_document(_record_vault(tmp_path, "  id: cap\n"), remote_images)

    images = [node for node in _record_fields(document, "manifest.md")["subtitle"] if node["type"] == "attachments"]
    assets = {asset["id"]: asset["href"] for asset in document["assets"]}
    assert [assets[node["attrs"]["asset"]] for node in images] == list(RECORD_BADGES)


def test_a_bare_url_in_a_string_value_arrives_as_a_link_node(tmp_path, remote_images) -> None:
    document = _record_document(_record_vault(
        tmp_path, "  source: https://example.org/a\n  summary: 'See https://example.org/b?c=1&d=2.'\n",
    ), remote_images)

    fields = _record_fields(document, "cap.md")
    links = {link["id"]: link["href"] for link in document["links"]}
    [source] = fields["capability.source"]
    assert links[source["attrs"]["link"]] == source["text"] == "https://example.org/a"
    before, url, after = fields["capability.summary"]
    assert (before["text"], url["text"], after["text"]) == ("See ", "https://example.org/b?c=1&d=2", ".")
    assert links[url["attrs"]["link"]] == "https://example.org/b?c=1&d=2"


def test_typed_values_stay_data_and_each_string_item_of_a_list_is_its_own_field_node(tmp_path, remote_images) -> None:
    document = _record_document(_record_vault(
        tmp_path, "  version: 2\n  stable: true\n  since: 2026-11-06\n  tags: [plain, '*marked*', 3]\n",
    ), remote_images)

    [record] = [item for item in document["records"] if item.get("path") == "cap.md"]
    fields = _record_fields(document, "cap.md")
    assert {key: record["fields"]["capability"][key] for key in ("version", "stable", "since")} == {
        "version": 2, "stable": True, "since": "2026-11-06",
    }
    assert [name for name in fields if name.startswith("capability.")] == ["capability.tags.0", "capability.tags.1"]
    assert fields["capability.tags.0"] == [{"type": "text", "attrs": {}, "children": [], "text": "plain"}]
    assert [node["type"] for node in fields["capability.tags.1"]] == ["emphasis"]
