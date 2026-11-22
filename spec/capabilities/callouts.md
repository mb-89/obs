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
> [!bluf]
> The limits hold at every load case.

> [!warning] Check the limits
```

The first callout is the note's bottom line ([[input-model#Bottom lines]]): read first, under the
page's title, its first paragraph going up one level.

## Document node

A callout is one `callouts` node, and a Document that holds one names `callouts` among its
capabilities. A callout is not an [[capabilities/extensions|extension]]: it adds no
`extensions` node.

The node's `attrs` hold the canonical type as `kind` and the title as `title`: the authored
title, or without one the default title [[input-model#Callouts]] names, so every adapter shows
the same title; `document.schema.json` owns the node's shape.

The title is inline nodes, parsed
like a paragraph's text: a wikilink in it carries the one link label
([[capabilities/wikilinks#Link text]]), so `> [!note] See [[command-fences#Authorization]]`
shows "Command Fences > Authorization". An adapter renders the title from these nodes and
parses no title text.

Its `children` are the callout body parsed like chapter content: paragraphs, lists, code,
links, wikilinks (with `attrs.chapter`), marks and nested callouts arrive as the same node
trees, and the Document names every capability they use.

A callout nested under a list item (`- > [!note]`, or a blockquote indented under the item) is a
`callouts` node among that `list-item`'s children, after the item's own paragraph: the
callout marks that item. A list item's children are block nodes parsed like chapter content.

A note's bottom line, its one `bluf` callout ([[input-model#Bottom lines]]), is named on its
chapter, or on the manifest for the abstract's, as `bottomLine`: `{"callout": <the callout's id>,
"lead": <the id of its first paragraph>}`. A chapter or a manifest without one carries no
`bottomLine`.
