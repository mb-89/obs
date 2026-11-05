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
  "panels": [],
  "provenance": {"command": ["generate-figure"]}
}
```
````
