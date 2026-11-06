import json
import subprocess
import sys
from pathlib import Path

import pytest

from obs.figure import FigureDescriptorError, validate_figure_descriptor, write_figure_descriptor


ROOT = Path(__file__).parents[1]


def figure_descriptor() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "id": "comparison",
        "data": {"traces": [{"x": [0, 1, 2], "y": [2, 5, 3], "label": "observed"}]},
        "panels": [
            {
                "id": "overview",
                "bounds": {"x": 0, "y": 0, "width": 720, "height": 320},
                "grid": {"row": 0, "column": 0, "rowSpan": 1, "columnSpan": 2},
                "axes": [
                    {
                        "id": "time",
                        "scale": "linear",
                        "limits": {"minimum": 0, "maximum": 2},
                        "label": "Time",
                    },
                    {
                        "id": "count",
                        "scale": "linear",
                        "limits": {"minimum": 0, "maximum": 6},
                        "label": "Count",
                    },
                ],
            },
            {
                "id": "detail",
                "bounds": {"x": 0, "y": 320, "width": 720, "height": 320},
                "grid": {"row": 1, "column": 0, "rowSpan": 1, "columnSpan": 2},
                "axes": [
                    {
                        "id": "time",
                        "scale": "linear",
                        "limits": {"minimum": 0, "maximum": 2},
                        "label": "Time",
                    },
                    {
                        "id": "ratio",
                        "scale": "log",
                        "limits": {"minimum": 0.1, "maximum": 10},
                        "label": "Ratio",
                    },
                ],
            },
        ],
        "provenance": {
            "command": ["generate-figure", "--input", "measurements.json"],
            "inputs": [{"id": "measurements", "fingerprint": "sha256:0123456789abcdef"}],
        },
    }


def test_multi_panel_descriptor_is_schema_valid_and_preserves_provenance(tmp_path) -> None:
    descriptor = figure_descriptor()
    destination = tmp_path / "figure.json"

    write_figure_descriptor(descriptor, destination)

    assert json.loads(destination.read_text(encoding="utf-8"))["provenance"] == descriptor["provenance"]


def test_descriptor_rejects_non_positive_panel_bounds() -> None:
    descriptor = figure_descriptor()
    descriptor["panels"][0]["bounds"]["width"] = 0

    try:
        validate_figure_descriptor(descriptor)
    except ValueError as error:
        assert str(error) == (
            "FigureDescriptor: panels[0].bounds.width: must be more than 0, not 0. "
            "Write a number more than 0; see capabilities/figure-descriptor."
        )
    else:
        raise AssertionError("Expected an invalid descriptor to be rejected.")


TRACES = {"traces": [
    {"x": [0, 1, 2], "y": [2, 5, 3], "label": "observed", "panel": "overview", "mode": "lines+markers",
     "color": "#1f77b4"},
    {"x": [0, 2], "y": [0.5, 4], "panel": "detail"},
]}
SANKEY = {
    "sankey": {
        "version": 1,
        "nodes": [{"id": "open", "label": "Open", "stage": 0}, {"id": "done", "label": "Done", "stage": 1},
                  {"id": "dropped", "label": "Dropped", "stage": -1, "placement": "below"}],
        "links": [{"source": "open", "target": "done", "value": 8, "color": "#2ca02c"},
                  {"source": "open", "target": "dropped", "value": 2, "label": "two"}],
    },
    "countLabels": {"unit": "item"},
}


def _with_data(data: dict[str, object]) -> dict[str, object]:
    descriptor = figure_descriptor()
    descriptor["data"] = data
    return descriptor


@pytest.mark.parametrize("data", [TRACES, SANKEY], ids=["traces", "sankey"])
def test_each_data_shape_is_schema_valid(data: dict[str, object]) -> None:
    validate_figure_descriptor(_with_data(data))


@pytest.mark.parametrize(("data", "field"), [
    ({"traces": [{"x": [0, 1], "y": [1, 2], "mode": "bars"}]}, "data.traces[0].mode"),
    ({"traces": [{"x": [0, 1]}]}, "data.traces[0].y"),
    ({"traces": [{"x": ["a"], "y": [1]}]}, "data.traces[0].x[0]"),
    ({"traces": []}, "data.traces"),
    ({"sankey": {**SANKEY["sankey"], "nodes": SANKEY["sankey"]["nodes"][:1]}}, "data.sankey.nodes"),
    ({"sankey": {"version": 1, "nodes": SANKEY["sankey"]["nodes"],
                 "links": [{"source": "open", "target": "done", "value": 0}]}}, "data.sankey.links[0].value"),
    ({**SANKEY, "countLabels": {"total": "items"}}, "data.countLabels.total"),
    ({"countLabels": {"unit": "item"}, **TRACES}, "data.sankey"),
    ({}, "data"),
    ({**TRACES, **SANKEY}, "data"),
    ({"series": [{"id": "observed", "values": [2, 5, 3]}]}, "data.series"),
], ids=["trace-mode", "trace-without-y", "trace-text-value", "no-traces", "one-node", "zero-link",
        "unknown-count-label", "count-labels-without-sankey", "no-shape", "both-shapes", "unknown-shape"])
def test_a_malformed_data_shape_names_its_field_and_the_capability(data: dict[str, object], field: str) -> None:
    with pytest.raises(FigureDescriptorError) as failure:
        validate_figure_descriptor(_with_data(data))
    message = str(failure.value)
    assert message.startswith(f"FigureDescriptor: {field}: ")
    assert message.endswith("see capabilities/figure-descriptor.")


def test_figure_descriptor_core_has_no_rendering_or_browser_dependencies() -> None:
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; import obs.figure; "
         "print(','.join(name for name in sys.modules if name.split('.')[0] in {'obs_html', 'playwright'}))"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == ""
