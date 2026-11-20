---
kind: capability
capability:
  id: figure-descriptor
  summary: Describe neutral multi-panel figure data and provenance.
  authoring: Produce a schema-valid FigureDescriptor with panel geometry, axes, and provenance, and show it as a figure of kind plot.
  dependsOn: []
  source: "[[input-model#Figure descriptor]]"
---

## What it does

Describes neutral figure data, panel geometry, axes, and reproducible provenance. A figure fence
of kind `plot` ([[capabilities/figures]]) shows one, from its source JSON file or inline under
`content`.

## Data shapes

The descriptor's `data` holds exactly one of two shapes; [[input-model#Figure descriptor]] owns
their fields and rules, `src/obs/figure.schema.json` their schema:

- `traces`: numeric series, each drawn on one of the descriptor's panels, which has an x and a
  y axis.
- `sankey`: a Sankey graph, the same graph a `sankey` figure carries, with an optional
  `countLabels` beside it.

## Authoring example

One figure of each shape:

````markdown
```figure
version: 1
kind: plot
caption: Measured response over time.
content: {
  "schemaVersion": 1,
  "id": "response",
  "data": {"traces": [
    {"x": [0, 1, 2], "y": [0, 1, 4], "label": "measured", "mode": "lines+markers"},
    {"x": [0, 1, 2], "y": [0, 1.2, 3.8], "label": "model", "color": "#d62728"}
  ]},
  "panels": [{
    "id": "overview",
    "bounds": {"x": 0, "y": 0, "width": 720, "height": 320},
    "grid": {"row": 0, "column": 0, "rowSpan": 1, "columnSpan": 1},
    "axes": [
      {"id": "time", "scale": "linear", "limits": {"minimum": 0, "maximum": 2}, "label": "Time"},
      {"id": "response", "scale": "linear", "limits": {"minimum": 0, "maximum": 4}, "label": "Response"}
    ]
  }],
  "provenance": {"command": ["generate-figure"]}
}
```

```figure
version: 1
kind: plot
caption: How requests flow through review.
content: {
  "schemaVersion": 1,
  "id": "review-flow",
  "data": {
    "sankey": {
      "version": 1,
      "nodes": [
        {"id": "open", "label": "Open", "stage": 0},
        {"id": "done", "label": "Done", "stage": 1},
        {"id": "dropped", "label": "Dropped", "stage": 1}
      ],
      "links": [
        {"source": "open", "target": "done", "value": 8},
        {"source": "open", "target": "dropped", "value": 2}
      ]
    },
    "countLabels": {"unit": "requests"}
  },
  "panels": [{
    "id": "flow",
    "bounds": {"x": 0, "y": 0, "width": 720, "height": 320},
    "grid": {"row": 0, "column": 0, "rowSpan": 1, "columnSpan": 1},
    "axes": [{"id": "stage", "scale": "linear", "limits": {"minimum": 0, "maximum": 1}, "label": "Stage"}]
  }],
  "provenance": {"command": ["generate-figure"]}
}
```
````

## Rendered example

This figure is rendered, not quoted: a `traces` descriptor with one series.

```figure
version: 1
kind: plot
caption: The squares y = x² of x = 0 to 4, one series drawn as lines with markers.
alt: A curve rising from 0 at x = 0 to 16 at x = 4.
content: {
  "schemaVersion": 1,
  "id": "squares",
  "data": {"traces": [
    {"x": [0, 1, 2, 3, 4], "y": [0, 1, 4, 9, 16], "label": "y = x²", "mode": "lines+markers"}
  ]},
  "panels": [{
    "id": "squares",
    "bounds": {"x": 0, "y": 0, "width": 720, "height": 320},
    "grid": {"row": 0, "column": 0, "rowSpan": 1, "columnSpan": 1},
    "axes": [
      {"id": "x", "scale": "linear", "limits": {"minimum": 0, "maximum": 4}, "label": "x"},
      {"id": "y", "scale": "linear", "limits": {"minimum": 0, "maximum": 16}, "label": "y = x²"}
    ]
  }],
  "provenance": {"command": ["generate-figure"]}
}
```
^squares
