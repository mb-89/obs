---
kind: capability
capability:
  id: cards-metrics
  summary: Author data-only cards and query-backed document metrics.
  authoring: Use a cards fence with bounded card and metric mappings.
  dependsOn: ["[[capabilities/markdown-frontmatter]]", "[[capabilities/queries]]"]
  source: "[[input-model#Document home and abstract]]"
---

## What it does

Author data-only cards and query-backed document metrics.

## Authoring example

````markdown
```cards
{"version": 1, "cards": [{"title": "Coverage", "body": "Current state."}]}
```
````
