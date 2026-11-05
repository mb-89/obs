---
kind: capability
capability:
  id: callouts
  summary: Mark block content with typed, data-only callouts.
  authoring: Start a blockquote with an Obsidian callout marker such as [!warning].
  dependsOn: ["[[capabilities/markdown]]"]
  source: "[[input-model#Callouts]]"
---

## What it does

Mark block content with typed, data-only callouts.

## Authoring example

```markdown
> [!warning] Check the limits
```

## Document node

A callout is one `callouts` node, and a Document that holds one names `callouts` among its
capabilities. A callout is not an [[capabilities/extensions|extension]]: it adds no
`extensions` node.

The node's `attrs` hold the canonical type as `kind` and the authored title as `title` (empty
when none is authored); `document.schema.json` owns the node's shape.

Its `children` are the callout body parsed like chapter content: paragraphs, lists, code,
links, wikilinks (with `attrs.chapter`), marks and nested callouts arrive as the same node
trees, and the Document names every capability they use.
