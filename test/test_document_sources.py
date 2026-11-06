"""Source data the Document carries for an adapter: the source archive, only on request.

Owner: spec/design_input/architecture.md ("Source archive"). Errors are matched by their field path
and owner reference (AGENTS.md), never by wording.
"""
import base64
import json
import os
import subprocess
import tomllib
from pathlib import Path

import pytest

from obs import sources
from obs.document import DocumentError, build_document, main, validate_document
from test_document_contract import recording_adapter
from test_vault import capability_reference


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def source_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    for folder in ("media", "scripts", ".obsidian", "data_output", "__pycache__", "venv", "lib.egg-info"):
        (vault / folder).mkdir(parents=True)
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text("# Chapter\n\n![Pixel](media/pixel.png)\n", encoding="utf-8")
    (vault / "media" / "pixel.png").write_bytes(PNG)
    (vault / "scripts" / "produce.py").write_bytes(b"print('data')\n")
    (vault / "data.csv").write_bytes(b"value\r\n1\r\n")
    (vault / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (vault / ".obsidian" / "workspace.json").write_text("{}", encoding="utf-8")
    (vault / "data_output" / "generated.json").write_text("{}", encoding="utf-8")
    (vault / "__pycache__" / "produce.cpython-312.pyc").write_bytes(b"\0")
    (vault / "scripts" / "produce.pyc").write_bytes(b"\0")
    (vault / "venv" / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    (vault / "lib.egg-info" / "PKG-INFO").write_text("Name: lib\n", encoding="utf-8")
    return vault


def _files(document: dict[str, object]) -> dict[str, dict[str, str]]:
    return {entry["path"]: entry for entry in document["sourceArchive"]["files"]}


def test_without_the_option_the_document_carries_no_source_archive(tmp_path) -> None:
    document = build_document(source_vault(tmp_path) / "manifest.md", capability_reference())

    assert "sourceArchive" not in document


def test_the_option_carries_the_vault_s_source_files_and_leaves_out_hidden_and_generated_ones(tmp_path) -> None:
    reference = capability_reference()
    document = build_document(source_vault(tmp_path) / "manifest.md", reference, embed_source=True)

    files = _files(document)
    assert sorted(files) == ["chapter.md", "data.csv", "manifest.md", "media/pixel.png", "scripts/produce.py"]
    assert base64.b64decode(files["data.csv"]["data"]) == b"value\r\n1\r\n"
    [asset] = document["assets"]
    assert files["media/pixel.png"] == {"path": "media/pixel.png", "asset": asset["id"]}, (
        "a file the Document holds as an asset carries the asset's id, not a second copy of its bytes")
    validate_document(document, reference)


def test_a_source_file_naming_an_unknown_asset_is_refused_at_its_field_path(tmp_path) -> None:
    reference = capability_reference()
    document = build_document(source_vault(tmp_path) / "manifest.md", reference, embed_source=True)
    document["sourceArchive"]["files"][0] = {"path": "chapter.md", "asset": "missing"}

    with pytest.raises(DocumentError) as refused:
        validate_document(document, reference)

    assert "sourceArchive.files[0].asset" in str(refused.value)
    assert "architecture.md" in str(refused.value)


@pytest.mark.skipif(os.name == "nt", reason="creating a symlink needs a privilege on Windows")
def test_a_symlink_in_the_vault_fails_the_source_archive_naming_its_path(tmp_path) -> None:
    vault = source_vault(tmp_path)
    (tmp_path / "outside.txt").write_text("outside\n", encoding="utf-8")
    (vault / "linked.txt").symlink_to(tmp_path / "outside.txt")

    with pytest.raises(DocumentError) as refused:
        build_document(vault / "manifest.md", capability_reference(), embed_source=True)

    assert "linked.txt" in str(refused.value) and "--embed-source" in str(refused.value)


def test_the_one_call_build_hands_the_adapter_the_source_archive_only_with_the_option(tmp_path) -> None:
    vault = source_vault(tmp_path)
    (tmp_path / "adapter").mkdir()
    configuration = recording_adapter(tmp_path / "adapter")
    kept = tmp_path / "document.json"

    assert main(["--source", str(vault / "manifest.md"), "--adapter", "fixture", "--adapter-config",
                 str(configuration), "--destination", str(tmp_path / "out.json"), "--document", str(kept),
                 "--embed-source"]) == 0

    assert "scripts/produce.py" in _files(json.loads(kept.read_text(encoding="utf-8")))


CHECKOUT = Path(__file__).resolve().parents[1]


def test_the_archive_records_the_obs_commit_and_lockfiles_that_rebuild_it(tmp_path) -> None:
    """The record names what rebuilds the artifact: obs's public repository, the commit of the
    checkout obs runs from and the versions of every lockfile Git tracks there."""
    build = build_document(source_vault(tmp_path) / "manifest.md", capability_reference(),
                           embed_source=True)["sourceArchive"]["build"]

    head = subprocess.run(["git", "-C", str(CHECKOUT), "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()
    project = tomllib.loads((CHECKOUT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    locked = {item["name"]: item["version"]
              for item in tomllib.loads((CHECKOUT / "uv.lock").read_text(encoding="utf-8"))["package"]}
    assert build["repository"] == project["urls"]["Repository"]
    assert build["commit"] == head
    assert build["lockfiles"]["uv.lock"] == locked
    diagrams = json.loads((CHECKOUT / "src/obs/diagrams/package-lock.json").read_text(encoding="utf-8"))
    assert build["lockfiles"]["src/obs/diagrams/package-lock.json"]["mermaid"] == \
        diagrams["packages"]["node_modules/mermaid"]["version"]
    assert build["arguments"] == ["--embed-source"]


def test_the_one_call_build_records_its_arguments_without_a_path_of_the_build_machine(tmp_path) -> None:
    vault = source_vault(tmp_path)
    (tmp_path / "adapter").mkdir()
    configuration = recording_adapter(tmp_path / "adapter", options={"evidence": {"type": "boolean",
                                                                                  "summary": "Evidence."}})
    kept = tmp_path / "document.json"

    assert main(["--embed-source", "--source", str(vault / "manifest.md"), "--adapter", "fixture",
                 "--adapter-config", str(configuration), "--destination", str(tmp_path / "out.json"),
                 "--document", str(kept), "--adapter-option", "evidence=true", "--execute-commands"]) == 0

    build = json.loads(kept.read_text(encoding="utf-8"))["sourceArchive"]["build"]
    assert build["arguments"] == ["--adapter", "fixture", "--destination", "out.json",
                                  "--adapter-option", "evidence=true", "--execute-commands", "--embed-source"]
    assert str(tmp_path) not in json.dumps(build)


def test_an_obs_outside_a_git_checkout_cannot_name_its_commit(tmp_path) -> None:
    with pytest.raises(sources.SourceError) as refused:
        sources.generator(tmp_path)

    assert "--embed-source" in str(refused.value) and str(tmp_path) in str(refused.value)
    assert sources.OWNER in str(refused.value)


def test_the_option_needs_a_source_to_archive(tmp_path) -> None:
    with pytest.raises(SystemExit) as refused:
        main(["--document", str(tmp_path / "document.json"), "--adapter", "fixture",
              "--destination", str(tmp_path / "out.json"), "--embed-source"])

    assert "--embed-source" in str(refused.value.code) and "--source" in str(refused.value.code)


def snippet_vault(tmp_path: Path, folder: str = ".obsidian/snippets") -> Path:
    vault = tmp_path / "vault"
    (vault / folder).mkdir(parents=True)
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text("# Chapter\n", encoding="utf-8")
    (vault / folder / "wide.css").write_text(".wide { width: 100%; }\n", encoding="utf-8")
    (vault / folder / "house-style.css").write_text("body { font-family: serif; }\n", encoding="utf-8")
    (vault / folder / "notes.txt").write_text("not a snippet\n", encoding="utf-8")
    return vault


def test_the_document_carries_the_vault_s_css_snippets_in_name_order(tmp_path) -> None:
    document = build_document(snippet_vault(tmp_path) / "manifest.md", capability_reference())

    assert document["cssSnippets"] == [
        {"name": "house-style", "path": ".obsidian/snippets/house-style.css",
         "text": "body { font-family: serif; }\n"},
        {"name": "wide", "path": ".obsidian/snippets/wide.css", "text": ".wide { width: 100%; }\n"},
    ]


def test_a_vault_without_a_snippet_folder_carries_no_snippets(tmp_path) -> None:
    vault = snippet_vault(tmp_path)
    for path in (vault / ".obsidian" / "snippets").iterdir():
        path.unlink()
    (vault / ".obsidian" / "snippets").rmdir()

    assert build_document(vault / "manifest.md", capability_reference())["cssSnippets"] == []


def test_core_configuration_names_another_snippet_folder(tmp_path) -> None:
    vault = snippet_vault(tmp_path, "styles/snippets")
    configuration = tmp_path / "core.json"
    configuration.write_text(json.dumps({
        "input": {"manifestFilename": "manifest.md", "projectConfigFilename": "project.json",
                  "cssSnippetFolder": "styles/snippets"},
        "execution": {"commandTimeoutSeconds": 15},
    }), encoding="utf-8")

    snippets = build_document(vault / "manifest.md", capability_reference(), configuration)["cssSnippets"]

    assert [snippet["path"] for snippet in snippets] == ["styles/snippets/house-style.css",
                                                         "styles/snippets/wide.css"]


def test_a_snippet_that_is_not_utf8_text_names_its_path(tmp_path) -> None:
    vault = snippet_vault(tmp_path)
    (vault / ".obsidian" / "snippets" / "broken.css").write_bytes(b"\xff\xfe")

    with pytest.raises(DocumentError) as refused:
        build_document(vault / "manifest.md", capability_reference())

    assert ".obsidian/snippets/broken.css" in str(refused.value)
    assert "architecture.md (CSS snippets)" in str(refused.value)


def test_the_source_archive_carries_the_snippets_despite_their_hidden_folder(tmp_path) -> None:
    document = build_document(snippet_vault(tmp_path) / "manifest.md", capability_reference(), embed_source=True)

    assert sorted(_files(document)) == [".obsidian/snippets/house-style.css", ".obsidian/snippets/wide.css",
                                        "chapter.md", "manifest.md"]


def two_vaults(tmp_path: Path) -> list[Path]:
    manifests = []
    for name in ("first", "second"):
        vault = tmp_path / name
        vault.mkdir()
        (vault / "manifest.md").write_text(f"---\ntitle: {name}\n---\n- [[chapter]]\n", encoding="utf-8")
        (vault / "chapter.md").write_text("# Chapter\n", encoding="utf-8")
        manifests.append(vault / "manifest.md")
    return manifests


def test_one_call_builds_each_source_into_the_destination_that_follows_it(tmp_path) -> None:
    first, second = two_vaults(tmp_path)
    configuration = recording_adapter(tmp_path)

    assert main(["--adapter", "fixture", "--adapter-config", str(configuration),
                 "--source", str(first), "--destination", str(tmp_path / "first.json"),
                 "--source", str(second), "--destination", str(tmp_path / "second.json")]) == 0

    for name, manifest in (("first", first), ("second", second)):
        called = json.loads((tmp_path / f"{name}.json").read_text(encoding="utf-8"))
        assert called["arguments"][1:] == [str((tmp_path / f"{name}.json").resolve()),
                                           "--vault-root", str(manifest.parent)]


@pytest.mark.parametrize(("adapter", "extra", "named"), [
    (True, ["--destination", "first.json"], "--destination"),
    (True, ["--destination", "first.json", "--destination", "second.json", "--document", "kept.json"],
     "--document"),
    (False, ["--destination", "first.json", "--destination", "second.json"], "--adapter"),
])
def test_several_sources_need_one_destination_each_an_adapter_and_no_document(
        tmp_path, adapter, extra, named) -> None:
    first, second = two_vaults(tmp_path)
    configuration = recording_adapter(tmp_path)
    given = ["--source", str(first), "--source", str(second), "--adapter-config", str(configuration),
             *[str(tmp_path / item) if item.endswith(".json") else item for item in extra],
             *(["--adapter", "fixture"] if adapter else [])]

    with pytest.raises(SystemExit) as refused:
        main(given)

    assert named in str(refused.value.code) and "--source" in str(refused.value.code)
    assert not (tmp_path / "first.json").exists()


def test_a_failing_source_stops_the_call_naming_it_and_keeps_the_artifacts_built_before(tmp_path) -> None:
    first, second = two_vaults(tmp_path)
    (second.parent / "chapter.md").unlink()
    configuration = recording_adapter(tmp_path)

    with pytest.raises(SystemExit) as refused:
        main(["--adapter", "fixture", "--adapter-config", str(configuration),
              "--source", str(first), "--destination", str(tmp_path / "first.json"),
              "--source", str(second), "--destination", str(tmp_path / "second.json")])

    assert str(second) in str(refused.value.code)
    assert (tmp_path / "first.json").is_file() and not (tmp_path / "second.json").exists()
