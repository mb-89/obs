"""The Document carries every referenced vault file's bytes; see architecture "Asset bytes"."""
import base64
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from obs.document import DocumentError, build_document, call_adapter, write_document
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
