"""The Document carries every referenced vault file's bytes; see architecture "Asset bytes"."""
import base64
import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

from obs.document import DocumentError, build_document, call_adapter, validate_document, write_document
from test_vault import capability_reference


ROOT = Path(__file__).parents[1]
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def asset_vault(tmp_path: Path, chapter: str) -> Path:
    vault = tmp_path / "vault"
    (vault / "part" / "media").mkdir(parents=True)
    (vault / "manifest.md").write_text("- [[part/chapter]]\n", encoding="utf-8")
    (vault / "part" / "chapter.md").write_text(chapter, encoding="utf-8")
    (vault / "part" / "media" / "pixel.png").write_bytes(PNG)
    (vault / "data.csv").write_bytes(b"value\r\n1\r\n")
    return vault


def test_an_adapter_obtains_an_image_s_bytes_from_the_document_without_the_vault(tmp_path) -> None:
    vault = asset_vault(tmp_path, "![Pixel](media/pixel.png)\n")
    reference = capability_reference()
    document_path = tmp_path / "document.json"
    write_document(build_document(vault / "manifest.md", reference), document_path, reference)
    shutil.rmtree(vault)
    reference_path = tmp_path / "capabilities.json"
    reference_path.write_text(json.dumps(reference), encoding="utf-8")
    (tmp_path / "adapter.json").write_text(json.dumps({
        "name": "assets", "command": ["node", str(ROOT / "test" / "fixtures" / "document-asset-adapter.js")],
        "contractVersion": 1, "capabilities": [item["id"] for item in reference["capabilities"]],
    }), encoding="utf-8")
    configuration = tmp_path / "adapters.json"
    configuration.write_text(json.dumps({"adapters": {"assets": "adapter.json"}}), encoding="utf-8")
    destination = tmp_path / "digests.json"

    call_adapter("assets", configuration, document_path, destination, reference_path)

    assert json.loads(destination.read_text(encoding="utf-8")) == {"pixel": hashlib.sha256(PNG).hexdigest()}


def test_each_referenced_vault_file_is_one_asset_with_its_path_and_bytes(tmp_path) -> None:
    vault = asset_vault(
        tmp_path,
        "![Pixel](media/pixel.png) ![Again](media/pixel.png) ![[PIXEL.png]] ![Source](../data.csv)\n\n"
        "![Remote](https://example.test/remote.png) [Unmarked](../data.csv)\n",
    )

    document = build_document(vault / "manifest.md", capability_reference())

    assert document["assets"] == [
        {"id": "pixel", "href": "media/pixel.png", "mediaType": "image/png",
         "path": "part/media/pixel.png", "data": base64.b64encode(PNG).decode("ascii")},
        {"id": "source", "href": "../data.csv", "mediaType": "text/csv",
         "path": "data.csv", "data": base64.b64encode(b"value\r\n1\r\n").decode("ascii")},
        {"id": "remote", "href": "https://example.test/remote.png", "mediaType": "image/png"},
    ]
    embed = next(
        node for node in document["chapters"][0]["content"][-2]["children"] if node["type"] == "embeds"
    )
    assert embed["attrs"] == {"target": "PIXEL.png", "chapter": None, "asset": "pixel"}


@pytest.mark.parametrize(("chapter", "message"), [
    ("![Missing](media/missing.png)\n",
     r"Asset does not exist in part/chapter\.md: !\[Missing\]\(media/missing\.png\); "
     r"add part/media/missing\.png to the vault or correct the path\."),
    ("![[missing.png]]\n",
     r"Asset does not exist in part/chapter\.md: !\[\[missing\.png\]\]; "
     r"add missing\.png to the vault or correct the embed\."),
    ("![Outside](../../outside.png)\n",
     r"Asset escapes the vault in part/chapter\.md: !\[Outside\]\(\.\./\.\./outside\.png\); "
     r"keep the file inside the vault\."),
])
def test_an_unreadable_asset_names_its_note_and_the_remedy(tmp_path, chapter, message) -> None:
    vault = asset_vault(tmp_path, chapter)

    with pytest.raises(DocumentError, match=message):
        build_document(vault / "manifest.md", capability_reference())


def test_an_ambiguous_embedded_file_name_names_its_matches(tmp_path) -> None:
    vault = asset_vault(tmp_path, "![[pixel.png]]\n")
    (vault / "other").mkdir()
    (vault / "other" / "pixel.png").write_bytes(PNG)

    with pytest.raises(DocumentError, match=(
        r"Ambiguous file name in part/chapter\.md: !\[\[pixel\.png\]\] matches "
        r"other/pixel\.png, part/media/pixel\.png; embed the vault path instead\."
    )):
        build_document(vault / "manifest.md", capability_reference())


SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'
BADGE = "https://img.shields.io/badge/Obsidian-7C3AED?style=for-the-badge"


def subtitle_vault(tmp_path: Path, subtitle: str) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text(f"---\nsubtitle: '{subtitle}'\n---\n- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text("Body.\n", encoding="utf-8")
    return vault


def subtitle_nodes(document: dict[str, object]) -> list[dict[str, object]]:
    frontmatter = next(node for node in document["manifest"]["abstract"] if node["type"] == "markdown-frontmatter")
    field = next(node for node in frontmatter["children"] if node["attrs"]["name"] == "subtitle")
    return field["children"]


def test_a_remote_image_in_the_subtitle_becomes_an_asset_with_its_fetched_bytes(tmp_path, remote_images) -> None:
    served, fetched = remote_images
    served[BADGE] = (SVG, "image/svg+xml")
    vault = subtitle_vault(tmp_path, f"![Obsidian]({BADGE}) and ![Again]({BADGE})")

    document = build_document(vault / "manifest.md", capability_reference())

    assert document["assets"] == [{
        "id": "obsidian", "href": BADGE, "mediaType": "image/svg+xml",
        "data": base64.b64encode(SVG).decode("ascii"),
    }]
    images = [node for node in subtitle_nodes(document) if node["type"] == "attachments"]
    assert [node["attrs"] for node in images] == [
        {"asset": "obsidian", "label": "Obsidian"}, {"asset": "obsidian", "label": "Again"},
    ]
    assert fetched == [BADGE]
    assert document["diagnostics"] == []


def test_the_spec_s_subtitle_badges_arrive_as_image_nodes(tmp_path, remote_images) -> None:
    served, _ = remote_images
    manifest = (ROOT / "spec" / "manifest.md").read_text(encoding="utf-8")
    subtitle = yaml.safe_load(manifest.split("---\n")[1])["subtitle"]
    for href in re.findall(r"\]\((\S+)\)", subtitle):
        served[href] = (SVG, "image/svg+xml")
    vault = subtitle_vault(tmp_path, subtitle)

    document = build_document(vault / "manifest.md", capability_reference())

    nodes = subtitle_nodes(document)
    assert [node["type"] for node in nodes] == ["attachments", "text", "attachments"]
    assert [node["attrs"] for node in nodes[::2]] == [
        {"asset": "obsidian", "label": "Obsidian"}, {"asset": "html5", "label": "HTML5"},
    ]
    assert document["diagnostics"] == []


def test_a_remote_image_in_chapter_text_takes_its_media_type_from_the_url_without_one(tmp_path, remote_images) -> None:
    served, _ = remote_images
    served["https://example.test/remote.png"] = (PNG, None)
    vault = asset_vault(tmp_path, "![Remote](https://example.test/remote.png)\n")

    document = build_document(vault / "manifest.md", capability_reference())

    assert document["assets"] == [{
        "id": "remote", "href": "https://example.test/remote.png", "mediaType": "image/png",
        "data": base64.b64encode(PNG).decode("ascii"),
    }]


def test_an_unreachable_remote_image_is_one_warning_and_the_node_keeps_its_alt_text_and_url(
    tmp_path, remote_images,
) -> None:
    vault = subtitle_vault(tmp_path, f"![Obsidian]({BADGE}) ![Obsidian]({BADGE})")

    document = build_document(vault / "manifest.md", capability_reference())

    assert document["diagnostics"] == [{"level": "warning", "message": (
        f"manifest.md: subtitle: remote image {BADGE} cannot be fetched "
        f"(no network in tests for {BADGE}). "
        "Save the image into the vault and embed it locally: ![Obsidian](<vault path>)."
    )}]
    assert document["assets"] == [{"id": "obsidian", "href": BADGE, "mediaType": "application/octet-stream"}]
    assert subtitle_nodes(document)[0]["attrs"] == {"asset": "obsidian", "label": "Obsidian"}


def test_an_unreachable_remote_image_in_chapter_text_names_its_note(tmp_path) -> None:
    vault = asset_vault(tmp_path, "![Remote](https://example.test/remote.png)\n")

    document = build_document(vault / "manifest.md", capability_reference())

    assert [item["message"] for item in document["diagnostics"]] == [
        "part/chapter.md: remote image https://example.test/remote.png cannot be fetched "
        "(no network in tests for https://example.test/remote.png). "
        "Save the image into the vault and embed it locally: ![Remote](<vault path>)."
    ]


@pytest.mark.parametrize(("asset", "valid"), [
    ({"href": BADGE, "data": "AA=="}, True),
    ({"href": BADGE}, True),
    ({"href": "media/pixel.png", "data": "AA=="}, False),
    ({"href": "media/pixel.png", "path": "media/pixel.png"}, False),
])
def test_only_a_remote_image_carries_bytes_without_a_path(tmp_path, asset, valid) -> None:
    reference = capability_reference()
    document = build_document(asset_vault(tmp_path, "Text.\n") / "manifest.md", reference)
    document["assets"] = [{"id": "image", "mediaType": "image/png", **asset}]

    if valid:
        validate_document(document, reference)
    else:
        with pytest.raises(DocumentError, match="Invalid Document"):
            validate_document(document, reference)
