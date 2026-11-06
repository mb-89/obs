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


def test_a_long_paragraph_warns_once_naming_its_note_and_line(tmp_path, capsys) -> None:
    manifest = _vault(tmp_path, PREFIX + "word " * 80 + "\n\n```text\n" + "code " * 300 + "\n```\n")
    assert _warnings(manifest) == []
    (tmp_path / "chapter.md").write_text(PREFIX + "word " * 81, encoding="utf-8")
    assert _warnings(manifest) == [
        "chapter.md:6: long paragraph (6 estimated lines at 80 characters; maximum 5). "
        "Split it into shorter paragraphs; see input-model#Long paragraphs."]
    assert main(["--source", str(manifest), "--document", str(tmp_path.parent / "document.json")]) == 0
    printed = [line for line in capsys.readouterr().err.splitlines() if "long paragraph" in line]
    assert [line.split(": ")[:3] for line in printed] == [["obs-document", "warning", "chapter.md:6"]]
    (tmp_path / "chapter.md").write_text(PREFIX + "word " * 40 + "\n\n" + "word " * 41, encoding="utf-8")
    assert _warnings(manifest) == []


def test_the_home_abstract_is_measured_but_not_the_title_or_subtitle(tmp_path) -> None:
    manifest = _vault(tmp_path, "# Chapter\n", f"---\ntitle: {'title ' * 81}\nsubtitle: {'subtitle ' * 81}\n---\n"
                                               "- [[chapter]]\n\n" + "word " * 81 + "\n")
    assert [warning.split(": ")[0] for warning in _warnings(manifest)] == ["manifest.md:7"]


def test_the_estimate_measures_prose_not_tables_math_code_or_link_payloads(tmp_path) -> None:
    manifest = _vault(tmp_path, (
        "# Chapter\n\n| Source | Formula |\n| --- | --- |\n| " + "word " * 200 + " | value |\n\n"
        "[Download](https://example.org/" + "a" * 4000 + ")\n\n$$\n" + "x+" * 300 + "x\n$$\n\n"
        "[[chapter|Short note link]] `short` #mark/decision/reuse\n\n> [!note]\n> " + "word " * 80 + "\n"))
    assert _warnings(manifest) == []


def test_a_wikilink_counts_as_the_title_it_shows_not_its_target(tmp_path) -> None:
    manifest = _vault(tmp_path, PREFIX + "[[other]] " * 20)
    (tmp_path / "other.md").write_text("# A long title that the other note shows\n", encoding="utf-8")
    assert [warning.split(" (")[1].split(";")[0] for warning in _warnings(manifest)] == [
        "10 estimated lines at 80 characters"]
    (tmp_path / "chapter.md").write_text(PREFIX + "[[other|o]] " * 20, encoding="utf-8")
    assert _warnings(manifest) == []


def test_the_core_configuration_sets_the_limit_and_the_line_width(tmp_path) -> None:
    manifest = _vault(tmp_path, PREFIX + "word " * 20)
    assert _warnings(manifest, _configuration(tmp_path, {"warningLines": 1, "lineCharacters": 20})) == [
        "chapter.md:6: long paragraph (5 estimated lines at 20 characters; maximum 1). "
        "Split it into shorter paragraphs; see input-model#Long paragraphs."]


@pytest.mark.parametrize("setting", [
    {"warningLines": 0}, {"warningLines": 31}, {"lineCharacters": 19}, {"lineCharacters": 201},
    {"warningLines": 2.5}])
def test_limits_outside_the_interims_range_are_refused(tmp_path, setting) -> None:
    with pytest.raises(CoreConfigError) as error:
        load_core_config(_configuration(tmp_path, setting))
    assert f"input.longParagraphs.{next(iter(setting))}" in str(error.value)
