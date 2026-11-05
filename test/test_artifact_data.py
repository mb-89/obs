import base64
import gzip
import os
from pathlib import Path

import pytest
from jsonschema import ValidationError

from obs_html.config import load_config
from obs_html.content import ContentError, parse_manifest
from obs_html.renderer import render_artifact
from obs_html.artifact_data import ARTIFACT_PATTERN, decode_artifact_data, encode_artifact_data


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("compression", ["gzip", "none"])
def test_transport_roundtrip_and_single_owner(compression: str) -> None:
    data = {"notes": [{"html": "<p>Unique current content.</p>" * 200}], "readerState": {"query": "µm"}}
    island = encode_artifact_data(data, compression)
    assert decode_artifact_data(island) == data
    assert island.count('id="artifact-data"') == 1
    if compression == "gzip":
        assert "Unique current content" not in island
        assert 'data-encoding="gzip"' in island
    else:
        assert 'type="application/json"' in island


def test_small_plain_fallback_and_invalid_transport() -> None:
    assert 'type="application/json"' in encode_artifact_data({"notes": []})
    for island in (
        "",
        '<script id="artifact-data" type="application/json">[]</script>',
        '<script id="artifact-data" type="application/octet-stream" data-encoding="br">abc</script>',
        '<script id="artifact-data" type="application/octet-stream" data-encoding="gzip">bad!</script>',
        '<script id="artifact-data" type="application/octet-stream" data-encoding="gzip">'
        + base64.b64encode(gzip.compress(b"not json")).decode() + "</script>",
    ):
        with pytest.raises(ContentError, match="artifact data.*regenerate the HTML with obs-html"):
            decode_artifact_data(island)
    with pytest.raises(ContentError, match=r"artifact.dataCompression 'br' is unsupported; use gzip or none"):
        encode_artifact_data({"notes": []}, "br")


def test_plain_json_cannot_close_the_island() -> None:
    data = {"notes": [{"html": "</script><script>throw new Error('authored')</script> & µm"}]}
    island = encode_artifact_data(data, "none")
    assert island.count("</script>") == 1
    assert decode_artifact_data(island) == data


def test_fallback_accounts_for_the_whole_transport_island() -> None:
    data = {"notes": ["x" * 50]}
    plain = encode_artifact_data(data, "none")
    candidate = encode_artifact_data(data, "gzip")
    assert len(candidate.encode()) <= len(plain.encode())


@pytest.mark.skipif(not os.environ.get("OBS_HTML_ARTIFACT_DATA_PROOF"),
                    reason="Set OBS_HTML_ARTIFACT_DATA_PROOF to the read-only accepted real artifact.")
def test_real_artifact_data_size_budget() -> None:
    artifact = Path(os.environ["OBS_HTML_ARTIFACT_DATA_PROOF"]).read_text(encoding="utf-8")
    assert len(ARTIFACT_PATTERN.search(artifact)[2].encode("utf-8")) == 9_329_454
    data = decode_artifact_data(artifact)
    encoded = encode_artifact_data(data)
    assert len(ARTIFACT_PATTERN.search(encoded)[2]) <= 1_030_000
    assert decode_artifact_data(encoded) == data


def test_default_config_and_explicit_transport(tmp_path: Path) -> None:
    config_path = ROOT / "src" / "obs_html" / "cfg.json"
    assert load_config(config_path).data_compression == "gzip"
    override = tmp_path / "cfg.json"
    override.write_text('{"artifact":{"dataCompression":"none"}}')
    assert load_config(config_path, override).data_compression == "none"
    override.write_text('{"artifact":{"dataCompression":"brotli"}}')
    with pytest.raises(ValidationError):
        load_config(config_path, override)


def test_renderer_transport_semantics_and_generic_script_boundary(tmp_path: Path) -> None:
    (tmp_path / "chapter.md").write_text("# Chapter\n\n" + "Content. " * 120)
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n")
    chapters = parse_manifest(manifest)
    compressed = render_artifact(manifest, chapters)
    plain = render_artifact(manifest, chapters, data_compression="none")
    a, b = decode_artifact_data(compressed), decode_artifact_data(plain)
    a["document"]["generation"].pop("timestamp")
    b["document"]["generation"].pop("timestamp")
    assert a == b
    assert 'data-encoding="gzip"' in compressed
    assert 'id="artifact-bootstrap-script"' in compressed
    assert 'id="artifact-script" type="application/x-obs-html-script"' in compressed
