from pathlib import Path

import pytest
import yaml

from obs.capabilities import build_capability_reference
from obs.document import build_document
from obs_html.content import (
    Chapter, base_note_value, collect_notes, compile_base_filter, read_chapter_content, read_manifest,
)


ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "spec" / "manifest.md"


@pytest.fixture(scope="module")
def spec_records() -> list[dict[str, object]]:
    reference = build_capability_reference(
        ROOT / "spec" / "capabilities", ROOT / "spec" / "capabilities" / "coverage.json",
    )
    return build_document(MANIFEST, reference)["records"]


def _authored_base_filters() -> list[object]:
    filters = []
    for path in sorted((ROOT / "spec").rglob("*.md")):
        source = path.read_text(encoding="utf-8")
        for block in source.split("```base\n")[1:]:
            definition = yaml.safe_load(block.split("\n```", 1)[0])
            if isinstance(definition, dict) and "filters" in definition:
                filters.append(definition["filters"])
    return filters


def test_spec_document_has_a_note_record_per_capability(spec_records) -> None:
    capabilities = {
        record["path"] for record in spec_records if record["fields"].get("kind") == "capability"
    }
    assert "capabilities/bases.md" in capabilities
    assert all(record["type"] == "note" for record in spec_records)
    assert len({record["id"] for record in spec_records}) == len(spec_records)
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
