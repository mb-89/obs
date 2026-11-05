---
kind: capability
capability:
  id: figure-descriptor
  summary: Describe neutral multi-panel figure data and provenance.
  authoring: Produce a schema-valid FigureDescriptor with panel geometry, axes, and provenance.
  dependsOn: []
  source: "[[input-model#Figure descriptor]]"
---

## What it does

Describes neutral figure data, panel geometry, axes, and reproducible provenance.

## Authoring example

````markdown
```json
{
  "schemaVersion": 1,
  "id": "comparison",
  "data": {},
  "panels": [{
    "id": "overview",
    "bounds": {"x": 0, "y": 0, "width": 720, "height": 320},
    "grid": {"row": 0, "column": 0, "rowSpan": 1, "columnSpan": 1},
    "axes": [{
      "id": "time",
      "scale": "linear",
      "limits": {"minimum": 0, "maximum": 2},
      "label": "Time"
    }]
  }],
  "provenance": {"command": ["generate-figure"]}
}
```
````
