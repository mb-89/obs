import base64
import gzip
import os
from pathlib import Path

import pytest
from jsonschema import ValidationError

from obs_html.config import load_config
from obs_html.content import ContentError, parse_manifest
from obs_html.renderer import render_report
from obs_html.report_data import REPORT_PATTERN, decode_report_data, encode_report_data


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("compression", ["gzip", "none"])
def test_transport_roundtrip_and_single_owner(compression: str) -> None:
    data = {"notes": [{"html": "<p>Unique current content.</p>" * 200}], "readerState": {"query": "µm"}}
    island = encode_report_data(data, compression)
    assert decode_report_data(island) == data
    assert island.count('id="report-data"') == 1
    if compression == "gzip":
        assert "Unique current content" not in island
        assert 'data-encoding="gzip"' in island
    else:
        assert 'type="application/json"' in island


def test_small_plain_fallback_and_invalid_transport() -> None:
    assert 'type="application/json"' in encode_report_data({"notes": []})
    for island in (
        "",
        '<script id="report-data" type="application/json">[]</script>',
        '<script id="report-data" type="application/octet-stream" data-encoding="br">abc</script>',
        '<script id="report-data" type="application/octet-stream" data-encoding="gzip">bad!</script>',
        '<script id="report-data" type="application/octet-stream" data-encoding="gzip">'
        + base64.b64encode(gzip.compress(b"not json")).decode() + "</script>",
    ):
        with pytest.raises(ContentError, match="document data"):
            decode_report_data(island)


def test_plain_json_cannot_close_the_island() -> None:
    data = {"notes": [{"html": "</script><script>throw new Error('authored')</script> & µm"}]}
    island = encode_report_data(data, "none")
    assert island.count("</script>") == 1
    assert decode_report_data(island) == data


def test_fallback_accounts_for_the_whole_transport_island() -> None:
    data = {"notes": ["x" * 50]}
    plain = encode_report_data(data, "none")
    candidate = encode_report_data(data, "gzip")
    assert len(candidate.encode()) <= len(plain.encode())


@pytest.mark.skipif(not os.environ.get("OBS_HTML_REPORT_DATA_PROOF"),
                    reason="Set OBS_HTML_REPORT_DATA_PROOF to the read-only accepted real report.")
def test_real_report_data_size_budget() -> None:
    report = Path(os.environ["OBS_HTML_REPORT_DATA_PROOF"]).read_text(encoding="utf-8")
    assert len(REPORT_PATTERN.search(report)[2].encode("utf-8")) == 9_329_454
    data = decode_report_data(report)
    encoded = encode_report_data(data)
    assert len(REPORT_PATTERN.search(encoded)[2]) <= 1_030_000
    assert decode_report_data(encoded) == data


def test_default_config_and_explicit_transport(tmp_path: Path) -> None:
    config_path = ROOT / "src" / "obs_html" / "cfg.json"
    assert load_config(config_path).data_compression == "gzip"
    override = tmp_path / "cfg.json"
    override.write_text('{"report":{"dataCompression":"none"}}')
    assert load_config(config_path, override).data_compression == "none"
    override.write_text('{"report":{"dataCompression":"brotli"}}')
    with pytest.raises(ValidationError):
        load_config(config_path, override)


def test_renderer_transport_semantics_and_generic_script_boundary(tmp_path: Path) -> None:
    (tmp_path / "chapter.md").write_text("# Chapter\n\n" + "Content. " * 120)
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n")
    chapters = parse_manifest(manifest)
    compressed = render_report(manifest, chapters)
    plain = render_report(manifest, chapters, data_compression="none")
    a, b = decode_report_data(compressed), decode_report_data(plain)
    a["document"]["generation"].pop("timestamp")
    b["document"]["generation"].pop("timestamp")
    assert a == b
    assert 'data-encoding="gzip"' in compressed
    assert 'id="report-bootstrap-script"' in compressed
    assert 'id="report-script" type="application/x-obs-html-script"' in compressed
