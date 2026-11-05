import json

import pytest

from obs_html_interim.content import ContentError, parse_manifest
from obs_html_interim.renderer import render_artifact
from obs_html_interim.artifact_data import decode_artifact_data


def test_generic_filtered_cards_and_static_markdown(tmp_path):
    (tmp_path / "manifest.md").write_text(
        "- [[chapter]]\n\n```cards\n" + json.dumps({
            "version": 1, "cards": [
                {"title": "Service health", "body": "Ordinary **operations**.", "metrics": [
                    {"label": "Availability", "where": [{"field": "healthy", "equals": "yes"}],
                     "denominator": [{"field": "kind", "equals": "service"}]},
                    {"label": "Unique regions", "where": [{"field": "kind", "equals": "service"}],
                     "distinct": "region"},
                ]},
                {"title": "Evidence", "body": "Unfiltered [instructions](https://example.org)."},
            ],
        }) + "\n```\n", encoding="utf-8",
    )
    (tmp_path / "chapter.md").write_text("# Operations\n", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    html = render_artifact(manifest, parse_manifest(manifest))
    assert 'data-record-cards' in html
    assert 'id="cards-script"' in html
    data = decode_artifact_data(html)
    assert "Ordinary <strong>operations</strong>." in data["notes"][0]["html"]
    assert 'class="content-card' in data["notes"][0]["html"]
    assert "paired-service" not in html.lower()


def test_cards_declare_compact_metric_pills_without_changing_metric_links(tmp_path):
    (tmp_path / "manifest.md").write_text(
        "- [[chapter]]\n\n```cards\n" + json.dumps({
            "version": 1, "cards": [{
                "title": "Coverage", "body": "", "metricStyle": "pills",
                "metrics": [{"label": "Covered", "where": [], "link": "#chapter"}],
            }],
        }) + "\n```\n", encoding="utf-8",
    )
    (tmp_path / "chapter.md").write_text("# Results\n", encoding="utf-8")
    artifact = render_artifact(tmp_path / "manifest.md", parse_manifest(tmp_path / "manifest.md"))
    home = next(note for note in decode_artifact_data(artifact)["notes"] if note["slug"] == "home")
    assert 'class="record-metrics record-metrics--pills"' in home["html"]
    assert "#chapter" in home["html"]


def test_card_metric_links_and_base_fences_use_existing_artifact_owners(tmp_path):
    (tmp_path / "manifest.md").write_text(
        "- [[chapter]]\n\n```cards\n" + json.dumps({
            "version": 1, "cards": [{
                "title": "Evidence",
                "body": (
                    "```base\n"
                    "filters:\n"
                    "  and: ['kind == \"evidence\"']\n"
                    "obsHtml: {records: note}\n"
                    "views:\n"
                    "  - type: table\n"
                    "    name: Evidence\n"
                    "    order: [label]\n"
                    "```"
                ),
                "metrics": [{
                    "label": "Evidence notes",
                    "where": [{"field": "kind", "equals": "evidence"}],
                    "link": "#chapter",
                }],
            }],
        }) + "\n```\n", encoding="utf-8",
    )
    (tmp_path / "chapter.md").write_text("# Operations\n", encoding="utf-8")
    (tmp_path / "evidence.md").write_text(
        '---\nkind: evidence\nlabel: Canonical evidence\n---\nEvidence details.\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.md"
    data = decode_artifact_data(render_artifact(manifest, parse_manifest(manifest)))

    home = next(note for note in data["notes"] if note["slug"] == "home")
    assert home["tables"][0]["key"] == "home-base-1"
    assert home["tables"][0]["definition"]["views"][0]["name"] == "Evidence"
    assert "data-base-table=\"home-base-1\"" in home["html"]
    assert "```base" not in home["html"]
    assert any(note["slug"] == "evidence" for note in data["notes"])


@pytest.mark.parametrize("extra", [{"script": "alert(1)"}, {"metrics": [{"label": "Bad", "where": "eval"}]}])
def test_cards_reject_executable_or_invalid_contract(tmp_path, extra):
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "chapter.md").write_text("```cards\n" + json.dumps({
        "version": 1, "cards": [{"title": "Bounded", "body": "", **extra}],
    }) + "\n```\n", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    with pytest.raises(ContentError, match=r"Card|; see capabilities/cards-metrics\."):
        render_artifact(manifest, parse_manifest(manifest))


@pytest.mark.parametrize("link", ["https://example.org", "javascript:alert(1)"])
def test_cards_reject_non_internal_metric_links(tmp_path, link):
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "chapter.md").write_text("```cards\n" + json.dumps({
        "version": 1,
        "cards": [{
            "title": "Bounded",
            "body": "",
            "metrics": [{"label": "Count", "where": [], "link": link}],
        }],
    }) + "\n```\n", encoding="utf-8")
    manifest = tmp_path / "manifest.md"
    with pytest.raises(ContentError, match=r"Card|; see capabilities/cards-metrics\."):
        render_artifact(manifest, parse_manifest(manifest))


def test_card_compound_quantity_and_bounded_tone_declarations():
    from obs_html_interim.cards import parse_card_spec

    metric = {"label": "Findings (unexplained)", "from": "quantities/findings", "where": [],
              "secondary": "quantities/unexplained", "link": "#findings",
              "secondaryLink": "#findings?tableFilter=explained%3Afalse", "toneRules": [
                  {"value": "secondary", "when": "positive", "tone": "negative"},
                  {"value": "primary", "when": "positive", "tone": "warning"}]}
    spec = {"version": 1, "cards": [{"title": "Coverage", "body": "",
                                   "metricStyle": "lines", "metrics": [metric]}]}
    assert parse_card_spec(json.dumps(spec), "note.md")["cards"][0]["metrics"] == [metric]
    spec["cards"][0]["metrics"][0]["toneRules"][0]["when"] = "run-script"
    with pytest.raises(ValueError):
        parse_card_spec(json.dumps(spec), "note.md")
