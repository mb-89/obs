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

## Document node

A `cards` fence is one `cards-metrics` node. Its `attrs` hold the authored `source` and the
validated `spec`; `document.schema.json` owns the node's shape.

Its `children` are one `document` node per card, in the order of `spec.cards`. Each holds that
card's `body` parsed like chapter content: paragraphs, lists, links, wikilinks (with
`attrs.chapter`), callouts and capability fences (`base`, `cmd`, `figure`, `cards`,
`property-editor`) arrive as the same node trees, and the Document names every capability
they use. A card body may hold a `cards` fence; its cards nest the same way.
