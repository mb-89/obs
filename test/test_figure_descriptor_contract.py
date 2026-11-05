import json
import subprocess
import sys
from pathlib import Path

from obs.figure import validate_figure_descriptor, write_figure_descriptor


ROOT = Path(__file__).parents[1]


def figure_descriptor() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "id": "comparison",
        "data": {"series": [{"id": "observed", "values": [2, 5, 3]}]},
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


def test_figure_descriptor_core_has_no_rendering_or_browser_dependencies() -> None:
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; import obs.figure; "
         "print(','.join(name for name in sys.modules if name.startswith('obs_html_interim')))"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == ""
