"""Bless requests and answers in the core (input-model, Bless requests; cli, Answers).

Reader: whoever changes how the core reads a chapter's bless request, its version or an answers file.

A chapter asks with ``obs.bless: pending``; the Document carries its version, the SHA-256 of the
note and of every vault file it embeds. ``obs-document --answers`` puts a reader's verdicts into
the Document: a verdict at the chapter's version is its answer, one at another version is outdated.
"""
import base64
import json
from pathlib import Path

import pytest
import yaml

from obs.document import DocumentError, build_document, main
from test_vault import capability_reference

OWNER = "input-model#Bless requests"
ANSWERS_OWNER = "input-model#Answers"
PIXEL = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
MATRIX = {"criteria": [{"key": "cost", "label": "Cost", "weight": 2, "better": "lower"}],
          "candidates": [{"key": "now", "label": "Now", "values": {"cost": 3}},
                         {"key": "next", "label": "Next", "values": {"cost": 2}}]}


def _vault(tmp_path: Path, profile: str = "obs: {bless: pending}\n") -> Path:
    (tmp_path / "manifest.md").write_text("- [[decision]]\n- [[record]]\n", encoding="utf-8")
    (tmp_path / "decision.md").write_text(
        f"---\n{profile}---\n# Decision\n\n![[pixel.png]]\n\n![[aside]]\n\n"
        "```figure\nversion: 1\nkind: pugh\ncaption: The choice.\nsource: matrix.yaml\n```\n^choice\n",
        encoding="utf-8")
    (tmp_path / "record.md").write_text("# Record\n\nNothing to bless.\n", encoding="utf-8")
    (tmp_path / "aside.md").write_text("An embedded aside.\n", encoding="utf-8")
    (tmp_path / "matrix.yaml").write_text(yaml.safe_dump(MATRIX), encoding="utf-8")
    (tmp_path / "pixel.png").write_bytes(PIXEL)
    (tmp_path / "unrelated.md").write_text("Not embedded.\n", encoding="utf-8")
    return tmp_path / "manifest.md"


def _chapters(manifest: Path) -> dict[str, dict]:
    return {chapter["id"]: chapter for chapter in build_document(manifest, capability_reference())["chapters"]}


def _version(manifest: Path) -> str:
    return _chapters(manifest)["decision"]["bless"]["version"]


def test_a_chapter_that_asks_carries_its_version_and_one_without_the_property_asks_nothing(tmp_path) -> None:
    chapters = _chapters(_vault(tmp_path))

    assert set(chapters["decision"]["bless"]) == {"version"}
    assert len(chapters["decision"]["bless"]["version"]) == 64
    assert "bless" not in chapters["record"]


@pytest.mark.parametrize("edit", [
    lambda root: (root / "decision.md").write_text((root / "decision.md").read_text() + "\nMore.\n"),
    lambda root: (root / "pixel.png").write_bytes(PIXEL + b"\0"),
    lambda root: (root / "aside.md").write_text("A changed aside.\n"),
    lambda root: (root / "matrix.yaml").write_text(yaml.safe_dump({**MATRIX, "title": "Changed"})),
], ids=["note", "image", "embedded note", "figure source"])
def test_the_version_changes_when_the_note_or_an_embed_changes(tmp_path, edit) -> None:
    manifest = _vault(tmp_path)
    before = _version(manifest)
    edit(tmp_path)

    assert _version(manifest) != before


def test_the_version_stays_the_same_otherwise(tmp_path) -> None:
    manifest = _vault(tmp_path)
    before = _version(manifest)
    (tmp_path / "unrelated.md").write_text("Changed, but not embedded.\n", encoding="utf-8")
    (tmp_path / "record.md").write_text("# Record\n\nAnother record.\n", encoding="utf-8")

    assert _version(manifest) == before


def test_a_bless_value_other_than_pending_names_its_field_and_owner(tmp_path) -> None:
    with pytest.raises(DocumentError) as failure:
        _chapters(_vault(tmp_path, "obs: {bless: yes}\n"))

    message = str(failure.value)
    assert message.startswith(f"{tmp_path / 'decision.md'}: obs.bless:"), message
    assert "capabilities/profiles" in message


def _answered(tmp_path: Path, verdicts: list[dict]) -> dict[str, dict]:
    manifest = _vault(tmp_path / "vault")
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps({"verdicts": verdicts}), encoding="utf-8")
    document = tmp_path / "document.json"
    assert main(["--source", str(manifest), "--document", str(document), "--answers", str(answers)]) == 0
    return {chapter["id"]: chapter for chapter in json.loads(document.read_text(encoding="utf-8"))["chapters"]}


def _verdict(version: str, **fields) -> dict:
    return {"chapter": "decision", "version": version, "verdict": "pick", "comment": "B costs less.",
            "pick": {"figure": "choice", "option": "B"},
            "figures": {"choice": {"weights": {"cost": 3}, "marks": {}, "rulings": {"B": {"ruling": "could",
                                                                                          "tripwire": "A price cut"}},
                                   "winner": "B"}}, **fields}


def test_an_answer_at_the_chapters_version_is_its_answer_and_one_at_another_is_outdated(tmp_path) -> None:
    (tmp_path / "vault").mkdir()
    version = _version(_vault(tmp_path / "vault"))

    current = _answered(tmp_path, [_verdict(version)])["decision"]["bless"]
    assert current == {"version": version, "answer": _verdict(version)}

    old = "0" * 64
    outdated = _answered(tmp_path, [_verdict(old)])["decision"]["bless"]
    assert outdated == {"version": version, "outdated": _verdict(old)}


@pytest.mark.parametrize(("verdicts", "field"), [
    ([{"chapter": "record", "version": "0" * 64, "verdict": "bless"}], "verdicts[0].chapter"),
    ([{"chapter": "decision", "version": "0" * 64, "verdict": "bless"}] * 2, "verdicts[1].chapter"),
    ([{"chapter": "decision", "version": "0" * 64, "verdict": "decline"}], "verdicts[0].comment"),
    ([{"chapter": "decision", "version": "0" * 64, "verdict": "decline", "comment": " "}], "verdicts[0].comment"),
    ([{"chapter": "decision", "version": "0" * 64, "verdict": "pick", "comment": "B."}], "verdicts[0].pick"),
    ([{"chapter": "decision", "version": "short", "verdict": "bless"}], "verdicts[0].version"),
    ([{"chapter": "decision", "version": "0" * 64, "verdict": "keep"}], "verdicts[0].verdict"),
], ids=["no request", "twice", "decline without comment", "blank comment", "pick without option", "version",
        "verdict"])
def test_an_answers_file_the_core_refuses_names_the_file_the_field_and_the_owner(tmp_path, verdicts, field) -> None:
    (tmp_path / "vault").mkdir()
    with pytest.raises(SystemExit) as failure:
        _answered(tmp_path, verdicts)

    message = str(failure.value)
    assert message.startswith(f"obs-document: {tmp_path / 'answers.json'}: {field}:"), message
    assert ANSWERS_OWNER in message


def test_answers_need_a_source(tmp_path) -> None:
    with pytest.raises(SystemExit) as failure:
        main(["--document", str(tmp_path / "document.json"), "--adapter", "html", "--destination",
              str(tmp_path / "out.html"), "--answers", str(tmp_path / "answers.json")])

    assert "--answers" in str(failure.value) and "--source" in str(failure.value)
