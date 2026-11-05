import json
import re
from xml.etree import ElementTree

import pytest

from obs_html.figures import FigureError, compile_plot, render_figure


def spec(**extra):
    return {
        "domain": [0.1, 1], "samples": 3,
        "equations": {"sigma": "x / 6", "p": "sf(c / sigma)", "count": "n * mean(p)"},
        "traces": [{"y": "count", "label": "Count", "axis": "y"}],
        "layout": {"yaxis": {"type": "log"}, "yaxis2": {"type": "linear"}},
        **extra,
    }


@pytest.mark.parametrize("kind", ["image", "svg", "plot", "sankey"])
def test_all_figure_kinds_share_explicit_caption_paragraphs(tmp_path, kind):
    import yaml
    from markdown_it import MarkdownIt
    (tmp_path / "figure.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"/>',
    )
    data = (
        {"version": 1, "nodes": [{"id": "a", "label": "A", "stage": 0},
                               {"id": "b", "label": "B", "stage": 1}],
         "links": [{"source": "a", "target": "b", "value": 1}]}
        if kind == "sankey" else {"version": 1, "panels": [
            {"id": "a", "title": "A", "box": [0, 0, 100, 50]},
        ]} if kind == "svg" else {"c": [0.01], "n": 120}
    )
    (tmp_path / "data.json").write_text(json.dumps(data))
    value = {"version": 1, "kind": kind, "source": "figure.svg" if kind == "image" else "data.json",
             "caption": ["*First caption.*", "Second [source](https://example.org)."]}
    if kind in {"plot", "svg"}:
        value["fallback"] = "figure.svg"
    if kind == "plot":
        value.update(spec())
    html = render_figure(yaml.safe_dump(value, sort_keys=False), tmp_path / "one.md", tmp_path,
                         render_caption=MarkdownIt("commonmark", {"html": False}).renderInline)
    caption = re.search(r"<figcaption>(.*?)</figcaption>", html, re.S)[1]
    assert caption == (
        '<p data-figure-caption-review><em>First caption.</em></p>'
        '<p data-figure-caption-review>Second <a href="https://example.org">source</a>.</p>'
    )


@pytest.mark.parametrize("caption", [[], [""], [1], {"paragraph": "text"}, True])
def test_explicit_caption_rejects_unsupported_shapes(tmp_path, caption):
    import yaml
    with pytest.raises(FigureError):
        render_figure(yaml.safe_dump({
            "version": 1, "kind": "image", "source": "image.png", "caption": caption,
        }), tmp_path / "one.md", tmp_path)


def test_sampler_broadcasts_arrays_and_safe_normal_survival():
    result = compile_plot(spec(), {"c": [0.01, 0.02], "n": 120})
    assert len(result["data"][0]["x"]) == 3
    assert result["data"][0]["y"][0] == pytest.approx(23.359367278306912)
    assert result["layout"]["yaxis"]["type"] == "log"


@pytest.mark.parametrize("expression", [
    "__import__('os')", "x.real", "c[0]", "[x for x in c]", "open(x)",
    "2 ** 999999", "1 / 0", "sqrt(-1)", "sf(x, x)", "sum(c, x)",
])
def test_sampler_rejects_executable_or_unbounded_values(expression):
    with pytest.raises(FigureError):
        compile_plot(spec(equations={"count": expression}), {"c": [1, 2], "n": 120})


@pytest.mark.parametrize("samples", [True, 1, 2001, 1.5])
def test_sampler_rejects_invalid_sample_count(samples):
    with pytest.raises(FigureError):
        compile_plot(spec(samples=samples), {"c": [1], "n": 120})


def test_source_and_fallback_are_confined_and_svg_is_not_inline(tmp_path):
    (tmp_path / "scene.json").write_text(json.dumps({
        "version": 1, "panels": [{"id": "a", "title": "A", "box": [0, 0, 100, 50]}],
    }))
    (tmp_path / "figure.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"/>')
    fence = "version: 1\nkind: svg\nsource: scene.json\nfallback: figure.svg\ncaption: Exact"
    result = render_figure(fence, tmp_path / "note.md", tmp_path)
    assert 'data-engineering-figure' in result
    assert 'data:image/svg+xml;base64,' in result
    assert "<svg" not in result
    with pytest.raises(FigureError, match="vault"):
        render_figure(fence.replace("scene.json", "../scene.json"), tmp_path / "note.md", tmp_path)


def test_declarative_plot_fence_has_data_and_default_print_image(tmp_path):
    (tmp_path / "values.json").write_text('{"c":[0.01,0.02],"n":120}')
    (tmp_path / "default.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"/>')
    import yaml
    fence = yaml.safe_dump({"version": 1, "kind": "plot", "source": "values.json",
                           "fallback": "default.svg", "caption": "Sweep", **spec()}, sort_keys=False)
    html = render_figure(fence, tmp_path / "note.md", tmp_path)
    assert 'data-figure-spec=' in html
    assert 'figure-default' in html
    assert 'figure-live' in html


def test_sankey_fence_renders_weighted_links_and_escaped_labels(tmp_path):
    graph = {
        "version": 1,
        "nodes": [
            {"id": "a", "label": "Input <A>", "stage": 0},
            {"id": "b", "label": "Input B", "stage": 0},
            {"id": "c", "label": "Output C", "stage": 1},
            {"id": "d", "label": "Output D", "stage": 1},
        ],
        "links": [
            {"source": "a", "target": "c", "value": 3, "label": "three paths"},
            {"source": "b", "target": "d", "value": 1},
        ],
    }
    (tmp_path / "flow.json").write_text(json.dumps(graph), encoding="utf-8")
    html = render_figure(
        "version: 1\nkind: sankey\nsource: flow.json\nsourceNote: reference-graph\ncaption: Trace flow",
        tmp_path / "note.md", tmp_path,
    )
    svg = ElementTree.fromstring(re.search(r"<svg\b.*?</svg>", html, re.S).group())
    ns = {"svg": "http://www.w3.org/2000/svg"}
    links = svg.findall(".//svg:path[@data-flow-value]", ns)
    widths = [float(link.attrib["stroke-width"]) for link in links]
    assert len(links) == 2
    assert max(widths) / min(widths) == pytest.approx(3)
    assert links[0].find("svg:title", ns).text == "Input <A> → Output C: three paths (3)"
    assert svg.find(".//svg:g[@class='sankey-node']/svg:text", ns).text == "Input <A>"
    assert "figure-sankey" in html
    assert "sourceNote" in html and "reference-graph" in html
    assert "data:image" not in html


def test_sankey_allows_explicit_upward_outcome_before_its_source_stage(tmp_path):
    graph = {
        "version": 1,
        "nodes": [
            {"id": "outcome", "label": "Exported upward", "stage": -1, "placement": "above"},
            {"id": "source", "label": "Source role", "stage": 0},
        ],
        "links": [{"source": "source", "target": "outcome", "value": 1}],
    }
    (tmp_path / "flow.json").write_text(json.dumps(graph), encoding="utf-8")
    html = render_figure(
        "version: 1\nkind: sankey\nsource: flow.json\ncaption: Upward export",
        tmp_path / "note.md", tmp_path,
    )
    assert "data-engineering-figure" in html


@pytest.mark.parametrize("placement", ["above", "below"])
@pytest.mark.parametrize("source_stages", [(0,), (0, 1)])
def test_sankey_placed_sink_accepts_same_stage_and_shared_sources(tmp_path, placement, source_stages):
    graph = {
        "version": 1,
        "nodes": [
            {"id": f"source-{stage}", "label": f"Source {stage}", "stage": stage}
            for stage in source_stages
        ] + [{"id": "sink", "label": "Shared outcome", "stage": source_stages[-1],
              "placement": placement}],
        "links": [
            {"source": f"source-{stage}", "target": "sink", "value": 1}
            for stage in source_stages
        ],
    }
    (tmp_path / "flow.json").write_text(json.dumps(graph), encoding="utf-8")
    html = render_figure(
        "version: 1\nkind: sankey\nsource: flow.json",
        tmp_path / "note.md", tmp_path,
    )
    svg = ElementTree.fromstring(re.search(r"<svg\b.*?</svg>", html, re.S).group())
    ns = {"svg": "http://www.w3.org/2000/svg"}
    assert len(svg.findall(".//svg:path[@data-flow-value]", ns)) == len(source_stages)
    assert not re.search(r"\b(?:nan|inf(?:inity)?)\b", ElementTree.tostring(svg).decode(), re.I)
    sink = svg.find(".//svg:g[@data-node-id='sink']/svg:rect", ns)
    source = svg.find(".//svg:g[@data-node-id='source-0']/svg:rect", ns)
    assert (float(sink.attrib["y"]) < float(source.attrib["y"])) == (placement == "above")


def test_sankey_source_note_is_included_as_an_exact_canonical_dependency(tmp_path):
    from obs_html.content import ContentError, parse_manifest
    from obs_html.renderer import render_artifact
    from obs_html.artifact_data import ARTIFACT_PATTERN, decode_artifact_data

    graph = {
        "version": 1,
        "nodes": [{"id": "source", "label": "Source", "stage": 0},
                  {"id": "target", "label": "Target", "stage": 1}],
        "links": [{
            "source": "source", "target": "target", "value": 1,
            "where": [{"field": "kind", "equals": "reference-path"}],
        }],
        "data": {"where": [{"field": "kind", "equals": "reference-path"}]},
    }
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "flow.json").write_text(json.dumps(graph), encoding="utf-8")
    (tmp_path / "chapter.md").write_text(
        "# Results\n\n```figure\nversion: 1\nkind: sankey\nsource: flow.json\n"
        "sourceNote: graph-source\ncaption: Trace flow\n```\n",
        encoding="utf-8",
    )
    (tmp_path / "graph-source.md").write_text(
        "---\n" + json.dumps({"kind": "reference-graph", "graph": graph}) + "\n---\n",
        encoding="utf-8",
    )
    artifact = render_artifact(manifest, parse_manifest(manifest))
    data = decode_artifact_data(ARTIFACT_PATTERN.search(artifact)[0])
    source = next(note for note in data["notes"] if note["sourcePath"] == "graph-source.md")
    assert source["frontmatter"]["graph"] == graph
    assert source["slug"] not in data["toc"]

    (tmp_path / "graph-source.md").unlink()
    with pytest.raises(ContentError, match="Dynamic Sankey source note does not resolve"):
        render_artifact(manifest, parse_manifest(manifest))


def test_manifest_canonical_notes_include_unlinked_runtime_records(tmp_path):
    from obs_html.content import ContentError, parse_manifest
    from obs_html.renderer import render_artifact
    from obs_html.artifact_data import ARTIFACT_PATTERN, decode_artifact_data

    manifest = tmp_path / "manifest.md"
    manifest.write_text(
        '---\ncanonicalNotes: ["configuration"]\n---\n- [[chapter]]\n',
        encoding="utf-8",
    )
    (tmp_path / "chapter.md").write_text("# Results\n\nNo configuration link.")
    (tmp_path / "configuration.md").write_text(
        '---\n{"kind":"reference-configuration","schemaVersion":1}\n---\n'
    )
    artifact = render_artifact(manifest, parse_manifest(manifest))
    data = decode_artifact_data(ARTIFACT_PATTERN.search(artifact)[0])
    assert any(note["sourcePath"] == "configuration.md" for note in data["notes"])
    assert all(note["slug"] not in data["toc"] for note in data["notes"]
               if note["sourcePath"] == "configuration.md")

    manifest.write_text('---\ncanonicalNotes: ["missing"]\n---\n- [[chapter]]\n', encoding="utf-8")
    with pytest.raises(ContentError, match="Canonical note dependency does not resolve"):
        render_artifact(manifest, parse_manifest(manifest))


@pytest.mark.parametrize("canonical_notes", ['"configuration"', '["../outside"]', '["configuration", "configuration"]'])
def test_manifest_canonical_notes_reject_invalid_dependencies(tmp_path, canonical_notes):
    from obs_html.content import ContentError, parse_manifest
    from obs_html.renderer import render_artifact

    manifest = tmp_path / "manifest.md"
    manifest.write_text(f"---\ncanonicalNotes: {canonical_notes}\n---\n- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "chapter.md").write_text("# Results\n")
    (tmp_path / "configuration.md").write_text("---\nkind: reference-configuration\n---\n")
    with pytest.raises(ContentError, match="Canonical note dependency|canonicalNotes"):
        render_artifact(manifest, parse_manifest(manifest))


@pytest.mark.parametrize("graph", [
    {"version": 1, "nodes": [{"id": "a", "label": "A", "stage": 0},
                             {"id": "b", "label": "B", "stage": 1, "placement": "below"},
                             {"id": "c", "label": "C", "stage": 2}],
     "links": [{"source": "a", "target": "b", "value": 1},
               {"source": "b", "target": "c", "value": 1}]},
    {"version": 1, "nodes": [{"id": "a", "label": "A", "stage": -1},
                             {"id": "b", "label": "B", "stage": 1}],
     "links": [{"source": "a", "target": "b", "value": 1}]},
    {"version": 1, "nodes": [{"id": "a", "label": "A", "stage": 0},
                             {"id": "b", "label": "B", "stage": -1, "placement": "above"},
                             {"id": "c", "label": "C", "stage": 1}],
     "links": [{"source": "a", "target": "b", "value": 1},
               {"source": "b", "target": "c", "value": 1}]},
    {"version": 1, "nodes": [{"id": "a", "label": "A", "stage": 0},
                             {"id": "b", "label": "B", "stage": 1}],
     "links": [{"source": "a", "target": "missing", "value": 1}]},
    {"version": 1, "nodes": [{"id": "a", "label": "A", "stage": 1},
                             {"id": "b", "label": "B", "stage": 1}],
     "links": [{"source": "a", "target": "b", "value": 1}]},
    {"version": 1, "nodes": [{"id": "a", "label": "A", "stage": 1},
                             {"id": "b", "label": "B", "stage": 0}],
     "links": [{"source": "a", "target": "b", "value": 1}]},
    {"version": 1, "nodes": [{"id": "a", "label": "A", "stage": 0},
                             {"id": "b", "label": "B", "stage": 1}],
     "links": [{"source": "a", "target": "b", "value": 0}]},
    {"version": 1, "nodes": [{"id": "a", "label": "A", "stage": 0},
                             {"id": "a", "label": "Duplicate", "stage": 1}],
     "links": [{"source": "a", "target": "a", "value": 1}]},
    {"version": 1, "nodes": [{"id": "a", "label": "A", "stage": 0},
                             {"id": "b", "label": "B", "stage": 1}],
     "links": [{"source": "a", "target": "b", "value": 1, "script": "alert(1)"}]},
])
def test_sankey_rejects_invalid_graphs(tmp_path, graph):
    (tmp_path / "flow.json").write_text(json.dumps(graph), encoding="utf-8")
    fence = "version: 1\nkind: sankey\nsource: flow.json\ncaption: Invalid"
    with pytest.raises(FigureError):
        render_figure(fence, tmp_path / "note.md", tmp_path)


@pytest.mark.parametrize("data,link", [
    ({"where": [{"field": "kind", "equals": "flow"}]}, None),
    ({"where": [{"field": "kind", "equals": "flow"}]}, {"where": []}),
    ({"where": [{"field": "kind", "contains": "flow"}]}, {"where": [{"field": "from", "exists": True}]}),
    ({"where": [{"field": "kind", "exists": False}]}, {"where": [{"field": "from", "exists": True}]}),
    ({"where": [{"field": "kind", "equals": "flow", "exists": True}]}, {"where": [{"field": "from", "exists": True}]}),
])
def test_dynamic_sankey_requires_bounded_field_predicates(tmp_path, data, link):
    graph = {
        "version": 1,
        "nodes": [{"id": "a", "label": "A", "stage": 0}, {"id": "b", "label": "B", "stage": 1}],
        "links": [{"source": "a", "target": "b", "value": 1, **(link or {})}],
        "data": data,
    }
    (tmp_path / "flow.json").write_text(json.dumps(graph), encoding="utf-8")
    with pytest.raises(FigureError):
        render_figure(
            "version: 1\nkind: sankey\nsource: flow.json\ncaption: Invalid dynamic flow",
            tmp_path / "note.md", tmp_path,
        )


def test_sankey_asset_is_confined_and_graph_is_bounded(tmp_path):
    (tmp_path / "outside.json").write_text("{}", encoding="utf-8")
    fence = "version: 1\nkind: sankey\nsource: ../outside.json\ncaption: Escape"
    with pytest.raises(FigureError, match="vault"):
        render_figure(fence, tmp_path / "note.md", tmp_path)
    graph = {
        "version": 1,
        "nodes": [{"id": f"n{index}", "label": f"Node {index}", "stage": 0} for index in range(256)]
        + [{"id": "last", "label": "Last", "stage": 1}],
        "links": [{"source": "n0", "target": "last", "value": 1}],
    }
    (tmp_path / "flow.json").write_text(json.dumps(graph), encoding="utf-8")
    with pytest.raises(FigureError, match="nodes: has more than 256 items") as result:
        render_figure(
            "version: 1\nkind: sankey\nsource: flow.json\ncaption: Too large",
            tmp_path / "note.md", tmp_path,
        )
    assert len(str(result.value)) < 100


@pytest.mark.parametrize("parameters", [
    [1, 2],
    {"c": [float("nan")], "n": 120},
    {"c": [[1]], "n": 120},
    {"c": [1], "n": True},
    {"c": [1], "x": 4},
])
def test_sampler_rejects_invalid_parameter_bindings(parameters):
    with pytest.raises(FigureError):
        compile_plot(spec(), parameters)


def test_renderer_has_no_figure_cost_for_plain_artifacts(tmp_path):
    from obs_html.content import parse_manifest
    from obs_html.renderer import render_artifact
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n")
    (tmp_path / "chapter.md").write_text("# Plain chapter\n\nNo figures.")
    result = render_artifact(manifest, parse_manifest(manifest))
    assert 'id="plotly-script"' not in result
    assert 'id="figure-script"' not in result


def test_plotly_cdn_is_pinned_integrity_checked_without_duplicate_fallback(tmp_path):
    from obs_html.content import parse_manifest
    from obs_html.renderer import render_artifact
    from obs_html.config import load_config
    from importlib.resources import files
    from obs_html.artifact_data import decode_artifact_data
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n")
    (tmp_path / "default.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"/>')
    (tmp_path / "values.json").write_text("{}")
    (tmp_path / "chapter.md").write_text(
        "# Plot\n\n```figure\nversion: 1\nkind: plot\nsource: values.json\n"
        "fallback: default.svg\ncaption: Test\ndomain: [0, 1]\nsamples: 3\n"
        "equations: {a: x}\ntraces: [{y: a, label: A}]\n```\n"
    )
    override = tmp_path / "cfg.json"
    override.write_text('{"schemaVersion":1,"artifact":{"figures":{"plotlyDelivery":"cdn"}}}')
    config = load_config(files("obs_html").joinpath("cfg.json"), override)
    result = render_artifact(manifest, parse_manifest(manifest), figures=config.figures)
    assert 'src="https://cdn.plot.ly/plotly-basic-2.35.3.min.js"' in result
    assert 'integrity="sha384-' in result
    assert 'crossorigin="anonymous"' in result
    assert re.search(r'<script\b[^>]*id="plotly-script"[^>]*\bdata-optional-runtime\b', result)
    assert "data:image/svg+xml" not in result
    plotly_scripts = re.findall(r'<script\b[^>]*id="plotly-script"[^>]*>(.*?)</script>',
                               result, re.S)
    assert plotly_scripts == [""]
    assert files("obs_html").joinpath("vendor", "plotly-basic.min.js").read_text(
        encoding="utf-8") not in result
    model = decode_artifact_data(result)
    chapter = next(note for note in model["notes"] if note["slug"] == "chapter")
    assert 'data-figure-kind="plot"' in chapter["html"]
    assert "<img" not in chapter["html"]
    assert not any("image/svg+xml" in str(asset) for asset in model.get("assets", {}).values())


@pytest.mark.parametrize("override", [
    "version: 2", "kind: html", "samples: 2001", "unexpected: true",
    "layout: {images: [{source: 'https://example.invalid/image.png'}]}",
])
def test_fence_schema_rejects_unsupported_contract_values(tmp_path, override):
    text = (
        "version: 1\nkind: plot\nsource: values.json\nfallback: default.svg\ncaption: Test\n"
        "domain: [0, 1]\nsamples: 3\nequations: {a: x}\ntraces: [{y: a, label: A}]\n"
        + override
    )
    with pytest.raises(FigureError):
        render_figure(text, tmp_path / "note.md", tmp_path)


def test_cli_checks_figure_assets_without_executing_or_writing(tmp_path, capsys):
    from obs_html.cli import main
    (tmp_path / "manifest.md").write_text("- [[figure]]\n")
    (tmp_path / "scene.json").write_text(
        '{"version":1,"panels":[{"id":"a","title":"A","box":[0,0,100,50]}]}'
    )
    (tmp_path / "default.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"/>'
    )
    (tmp_path / "figure.md").write_text(
        "# Figure\n\n```figure\nversion: 1\nkind: svg\nsource: scene.json\n"
        "fallback: default.svg\ncaption: Exact composition\n```\n"
    )
    before = set(tmp_path.iterdir())
    assert main(["--source", str(tmp_path), "--check"]) == 0
    assert set(tmp_path.iterdir()) == before
    assert "no commands executed" in capsys.readouterr().out


def test_cli_check_reports_invalid_sankey_graph_without_writing(tmp_path, capsys):
    from obs_html.cli import main
    (tmp_path / "manifest.md").write_text("- [[flow]]\n", encoding="utf-8")
    (tmp_path / "flow.json").write_text(json.dumps({
        "version": 1,
        "nodes": [
            {"id": "a", "label": "A", "stage": 1},
            {"id": "b", "label": "B", "stage": 1},
        ],
        "links": [{"source": "a", "target": "b", "value": 1}],
    }), encoding="utf-8")
    (tmp_path / "flow.md").write_text(
        "# Flow\n\n```figure\nversion: 1\nkind: sankey\n"
        "source: flow.json\ncaption: Invalid\n```\n",
        encoding="utf-8",
    )
    before = set(tmp_path.iterdir())
    with pytest.raises(SystemExit) as result:
        main(["--source", str(tmp_path), "--check"])
    assert result.value.code == 2
    assert set(tmp_path.iterdir()) == before
    assert "later stage" in capsys.readouterr().err
