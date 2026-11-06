"""The long-paragraph lint (input-model, Long paragraphs): a paragraph whose estimated line count
exceeds the core configuration's limit is a warning in the Document's diagnostics, naming its note
and line; ported from the interim's paragraph warnings."""
import json
from pathlib import Path

import pytest

from obs.config import CoreConfigError, load_core_config
from obs.document import build_document, main
from test_vault import capability_reference

PREFIX = "---\nstatus: draft\n---\n# Chapter\n\n"


def _vault(tmp_path: Path, chapter: str, manifest: str = "- [[chapter]]\n") -> Path:
    (tmp_path / "manifest.md").write_text(manifest, encoding="utf-8")
    (tmp_path / "chapter.md").write_text(chapter, encoding="utf-8")
    return tmp_path / "manifest.md"


def _warnings(manifest: Path, configuration: Path | None = None) -> list[str]:
    document = build_document(manifest, capability_reference(), configuration)
    return [diagnostic["message"] for diagnostic in document["diagnostics"]
            if "long paragraph" in diagnostic["message"]]


def _configuration(tmp_path: Path, long_paragraphs: dict[str, object]) -> Path:
    path = tmp_path.parent / f"{tmp_path.name}-core.json"
    path.write_text(json.dumps({
        "input": {"manifestFilename": "manifest.md", "projectConfigFilename": "project.json",
                  "longParagraphs": long_paragraphs},
        "execution": {"commandTimeoutSeconds": 15},
    }), encoding="utf-8")
    return path


@pytest.mark.parametrize("setting", [
    {"warningLines": 0}, {"warningLines": 31}, {"lineCharacters": 19}, {"lineCharacters": 201},
    {"warningLines": 2.5}])
def test_limits_outside_the_interims_range_are_refused(tmp_path, setting) -> None:
    with pytest.raises(CoreConfigError) as error:
        load_core_config(_configuration(tmp_path, setting))
    assert f"input.longParagraphs.{next(iter(setting))}" in str(error.value)
