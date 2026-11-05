from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

from markdown_it import MarkdownIt
import pytest

import obs_html.content as content
from obs_html.cli import main
from obs_html.report_data import decode_report_data


def test_cli_reads_and_decodes_each_note_once_per_build(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    manifest = vault / "manifest.md"
    manifest.write_text("- [[one]]\n\n# Overview\n", encoding="utf-8")
    one = vault / "one.md"
    one.write_text(
        "---\nrelated: '[[Friendly#Details]]'\n---\n# One\n\n"
        + " ".join("[[Friendly#Details]]" for _ in range(8))
        + "\n\n[[target#mark-target-risk-watch]] [[manifest#Overview]]\n",
        encoding="utf-8",
    )
    target = vault / "target.md"
    target.write_text(
        "---\naliases: [Friendly, friendly]\n---\n# Details\n\n"
        "Keep watching. #mark/risk/watch\n",
        encoding="utf-8",
    )
    reads = Counter()
    splits = Counter()
    original_read = Path.read_text
    original_split = content._split_frontmatter
    sources = {path: path.read_text(encoding="utf-8") for path in (manifest, one, target)}

    def read(path, *args, **kwargs):
        if path.parent == vault and path.suffix == ".md":
            reads[path.name] += 1
        return original_read(path, *args, **kwargs)

    def split(source, path):
        if source == sources.get(path):
            splits[path.name] += 1
        return original_split(source, path)

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(content, "_split_frontmatter", split)
    output = tmp_path / "report.html"
    assert main(["--source", str(manifest), "--output", str(output)]) == 0
    assert reads == Counter({"manifest.md": 1, "one.md": 1, "target.md": 1})
    assert splits["manifest.md"] == splits["one.md"] == splits["target.md"] == 1
    data = decode_report_data(output.read_text(encoding="utf-8"))
    rendered = next(note["html"] for note in data["notes"] if note["slug"] == "one")
    assert rendered.count('href="#target/details"') == 8
    assert 'href="#target/mark-target-risk-watch"' in rendered
    assert 'href="#home/overview"' in rendered

    target.write_text(
        "---\naliases: [Friendly]\n---\n# Changed\n", encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="2"):
        main(["--source", str(manifest), "--output", str(output)])
    assert reads["target.md"] == 2
    assert output.is_file()
    assert decode_report_data(output.read_text(encoding="utf-8")) == data


def test_queries_reuse_context_free_parses_without_validating_unselected_notes(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    manifest = vault / "manifest.md"
    manifest.write_text("- [[register]]\n", encoding="utf-8")
    query = (
        "```base\nfilters: 'kind == \"selected\"'\n"
        "views:\n  - type: table\n    order: [title]\n```\n\n"
    )
    (vault / "register.md").write_text("# Register\n\n" + query * 4, encoding="utf-8")
    target_body = "# Details\n\nA risk. #mark/risk/watch\n"
    (vault / "target.md").write_text(
        "---\nkind: selected\nrelated: '[[register]]'\n---\n" + target_body,
        encoding="utf-8",
    )
    unused_body = "# Unused\n\n```base\ninvalid\n```\n\n[[absent]]\n"
    (vault / "unused.md").write_text(unused_body, encoding="utf-8")
    parses = Counter()
    original_parse = MarkdownIt.parse

    def parse(markdown, source, *args, **kwargs):
        if source in {target_body, unused_body}:
            parses[source] += 1
        return original_parse(markdown, source, *args, **kwargs)

    monkeypatch.setattr(MarkdownIt, "parse", parse)
    output = tmp_path / "report.html"
    assert main(["--source", str(manifest), "--output", str(output)]) == 0
    assert parses[target_body] == 2  # Context-free extraction, then note-local resolution.
    assert parses[unused_body] == 1
    data = decode_report_data(output.read_text(encoding="utf-8"))
    assert {note["slug"] for note in data["notes"]} == {"home", "register", "target"}
    target = next(note for note in data["notes"] if note["slug"] == "target")
    assert target["marks"][0]["label"] == "watch"
    assert target["frontmatterHtml"]["related"] == '<a href="#register">Register</a>'


def test_identical_note_text_keeps_note_local_link_context(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    for folder in ("a", "b"):
        (vault / folder).mkdir()
        (vault / folder / "one.md").write_text(
            "# One\n\n[[target#Details]]\n", encoding="utf-8",
        )
        (vault / folder / "target.md").write_text("# Details\n", encoding="utf-8")
    manifest = vault / "manifest.md"
    manifest.write_text("- [[a/one]]\n- [[b/one]]\n", encoding="utf-8")
    output = tmp_path / "report.html"
    assert main(["--source", str(manifest), "--output", str(output)]) == 0
    notes = {note["slug"]: note for note in decode_report_data(
        output.read_text(encoding="utf-8"),
    )["notes"]}
    assert 'href="#a-target/details"' in notes["a-one"]["html"]
    assert 'href="#b-target/details"' in notes["b-one"]["html"]


def test_cli_reuses_asset_bytes_only_within_one_build(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text(
        "- [[one]]\n", encoding="utf-8",
    )
    (vault / "one.md").write_text(
        "---\nimage: '![Icon](icon.svg)'\nattachment: '![Download](example.bin)'\n---\n"
        "# One\n\n![Icon](icon.svg)\n\n![Download](example.bin)\n",
        encoding="utf-8",
    )
    icon, attachment = vault / "icon.svg", vault / "example.bin"
    icon.write_bytes(b"<svg>first</svg>")
    attachment.write_bytes(b"first attachment")
    reads = Counter()
    original_read = Path.read_bytes

    def read(path):
        if path in {icon, attachment}:
            reads[path.name] += 1
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", read)

    def authored_assets(data):
        class Elements(HTMLParser):
            def __init__(self, html):
                super().__init__()
                self.images = []
                self.links = []
                self.feed(html)

            def handle_starttag(self, tag, attrs):
                if tag == "img":
                    self.images.append(dict(attrs))
                elif tag == "a":
                    self.links.append(dict(attrs))

        note = next(note for note in data["notes"] if note["slug"] == "one")
        body = Elements(note["html"])
        fields = note["frontmatterHtml"]
        image, = Elements(fields["image"]).images
        attachment, = Elements(fields["attachment"]).links
        assert body.images == [image]
        assert body.links == [attachment]
        assert image.get("alt") == "Icon"
        assert attachment.get("download") == "example.bin"
        tokens = [image.get("src"), attachment.get("href")]
        assert all(token.startswith("obs-asset:") for token in tokens)
        keys = [token.removeprefix("obs-asset:") for token in tokens]
        assert len(set(keys)) == 2
        return {key: data["embeddedAssets"][key] for key in keys}

    output = tmp_path / "report.html"
    assert main(["--source", str(vault), "--output", str(output), "--embed-attachments"]) == 0
    assert reads == Counter({"icon.svg": 1, "example.bin": 1})
    first = decode_report_data(output.read_text(encoding="utf-8"))
    first_assets = authored_assets(first)
    assert set(first_assets.values()) == {
        "data:image/svg+xml;base64,PHN2Zz5maXJzdDwvc3ZnPg==",
        "data:application/octet-stream;base64,Zmlyc3QgYXR0YWNobWVudA==",
    }

    icon.write_bytes(b"<svg>next</svg>")
    attachment.write_bytes(b"next attachment")
    assert main(["--source", str(vault), "--output", str(output), "--embed-attachments"]) == 0
    assert reads == Counter({"icon.svg": 2, "example.bin": 2})
    second = decode_report_data(output.read_text(encoding="utf-8"))
    second_assets = authored_assets(second)
    assert set(second_assets.values()) == {
        "data:image/svg+xml;base64,PHN2Zz5uZXh0PC9zdmc+",
        "data:application/octet-stream;base64,bmV4dCBhdHRhY2htZW50",
    }
    assert not set(first_assets) & set(second["embeddedAssets"])
    assert {
        key: value for key, value in first["embeddedAssets"].items() if key not in first_assets
    } == {
        key: value for key, value in second["embeddedAssets"].items() if key not in second_assets
    }
