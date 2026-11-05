import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from obs_html.cli import main
from obs_html.artifact_data import decode_artifact_data
from obs_html.reproduction import embedded_archive


def _vault(root: Path, body: str, frontmatter: str = "", manifest: str = "") -> Path:
    vault = root / "vault"
    (vault / "input").mkdir(parents=True)
    (vault / "input" / "data.bin").write_bytes(b"x" * 4096)
    (vault / "icon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>',
                                    encoding="utf-8")
    (vault / "manifest.md").write_text(manifest + "- [[one]]\n", encoding="utf-8")
    (vault / "one.md").write_text(frontmatter + "# One\n\n" + body + "\n", encoding="utf-8")
    return vault


def _build(tmp_path: Path, vault: Path, *flags: str) -> dict:
    output = tmp_path / "document.html"
    assert main(["--source", str(vault), "--output", str(output), *flags]) == 0
    return decode_artifact_data(output.read_text(encoding="utf-8"))


def _note(data: dict) -> dict:
    return next(note for note in data["notes"] if note["slug"] == "one")


LINKS = {
    "markdown": "See [the data](input/data.bin).",
    "wikilink": "See [[data.bin|the data]].",
}
MARKED = {
    "markdown": "See ![the data](input/data.bin).",
    "wikilink": "See ![[data.bin|the data]].",
}


@pytest.mark.parametrize("syntax", sorted(LINKS))
@pytest.mark.parametrize("flag", [False, True])
def test_unmarked_links_never_embed(tmp_path, syntax, flag) -> None:
    vault = _vault(tmp_path, LINKS[syntax])
    html = _note(_build(tmp_path, vault, *(["--embed-attachments"] if flag else [])))["html"]
    assert "data:application/octet-stream" not in html
    assert 'data-source-path="input/data.bin"' in html
    assert ">the data<" in html
    assert str(tmp_path) not in html


@pytest.mark.parametrize("syntax", sorted(MARKED))
def test_marked_file_without_the_flag_renders_as_provenance_text(tmp_path, syntax) -> None:
    html = _note(_build(tmp_path, _vault(tmp_path, MARKED[syntax])))["html"]
    assert "data:application/octet-stream" not in html
    assert 'data-source-path="input/data.bin"' in html
    assert "(<code>input/<wbr>data.<wbr>bin</code>)" in html
    assert "!" not in html.split("See", 1)[1].split("data-source-path", 1)[0]


@pytest.mark.parametrize("syntax", sorted(MARKED))
def test_marked_file_with_the_flag_embeds_a_download(tmp_path, syntax) -> None:
    html = _note(_build(tmp_path, _vault(tmp_path, MARKED[syntax]), "--embed-attachments"))["html"]
    assert 'download="data.bin"' in html
    assert "data:application/octet-stream;base64," in html or "obs-asset:" in html
    assert "data-source-path" not in html
    assert ">the data</a>" in html


def test_marked_frontmatter_link_embeds_with_the_flag(tmp_path) -> None:
    vault = _vault(tmp_path, "Body.", frontmatter="---\nsnapshot: '![Snapshot](input/data.bin)'\n---\n")
    data = _build(tmp_path, vault, "--embed-attachments")
    assert 'download=\\"data.bin\\"' in json.dumps(_note(data)["frontmatterHtml"])


def test_marked_image_wikilink_is_embedded_document_content(tmp_path) -> None:
    html = _note(_build(tmp_path, _vault(tmp_path, "![[icon.svg]]")))["html"]
    assert "<img" in html and "data:image/svg+xml;base64," in html


def test_file_wikilinks_resolve_by_unique_name_and_reject_ambiguity(tmp_path, capsys) -> None:
    vault = _vault(tmp_path, "See [[input/data.bin]] and [[data.bin]].")
    html = _note(_build(tmp_path, vault))["html"]
    assert html.count('data-source-path="input/data.bin"') == 2

    (vault / "data.bin").write_bytes(b"root copy")
    html = _note(_build(tmp_path, vault))["html"]
    assert 'data-source-path="data.bin"' in html

    (vault / "one.md").write_text("# One\n\nSee [[nested.bin]].\n", encoding="utf-8")
    (vault / "input" / "nested.bin").write_bytes(b"1")
    (vault / "other").mkdir()
    (vault / "other" / "nested.bin").write_bytes(b"2")
    with pytest.raises(SystemExit, match="2"):
        main(["--source", str(vault), "--output", str(tmp_path / "x.html")])
    assert "Ambiguous attachment name: nested.bin" in capsys.readouterr().err

    (vault / "one.md").write_text("# One\n\nSee [[missing.bin]].\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="2"):
        main(["--source", str(vault), "--output", str(tmp_path / "x.html")])
    assert "Attachment does not exist: missing.bin" in capsys.readouterr().err


def test_manifest_attachments_key_is_rejected_with_a_migration_message(tmp_path, capsys) -> None:
    vault = _vault(tmp_path, "Body.", manifest="---\nobsHtml: {attachments: embed}\n---\n")
    with pytest.raises(SystemExit, match="2"):
        main(["--source", str(vault), "--output", str(tmp_path / "document.html")])
    error = capsys.readouterr().err
    assert "obsHtml.attachments was removed" in error
    assert "![label](file)" in error and "--embed-attachments" in error


@pytest.mark.parametrize("flag", [False, True])
def test_source_archive_rebuilds_with_the_same_attachment_flag(tmp_path, flag) -> None:
    vault = _vault(tmp_path, MARKED["markdown"])
    output = tmp_path / "document.html"
    flags = ["--embed-source", *(["--embed-attachments"] if flag else [])]
    assert main(["--source", str(vault), "--output", str(output), *flags]) == 0
    archive = ZipFile(BytesIO(embedded_archive(output.read_text(encoding="utf-8"))))
    assert ("'--embed-attachments'" in archive.read("reproduce.py").decode("utf-8")) == flag
    assert ("--embed-attachments" in archive.read("REPRODUCE.txt").decode("utf-8")) == flag
