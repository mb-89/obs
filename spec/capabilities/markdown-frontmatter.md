---
kind: capability
capability:
  id: markdown-frontmatter
  summary: Add structured metadata to a Markdown note.
  authoring: Put one YAML frontmatter mapping at the beginning of a note.
  dependsOn: ["[[capabilities/markdown]]"]
  source: "[[input-model#Markdown body and frontmatter]]"
---

## What it does

Add structured metadata to a Markdown note.

## Ignored notes

The boolean field `ignored` (default `false`) marks a note as ignored, the way a leading
underscore marks a Python name as private: no automatic selection selects it, while explicit
references still reach it ([[input-model#Chapter content]]). Automatic selections are
[[capabilities/queries]] and the counts over them, and [[capabilities/bases]], including a
Base view's `obsHtml.members` list, which only narrows what the Base selects. Any other value than
`true` or `false` is an error that names the note. The note's record carries `ignored: true` ([[capabilities/bases#Note records]]).

## Document node

A note with frontmatter starts its content with one `markdown-frontmatter` node: `attrs.metadata`
holds the values as JSON. Its `children` hold every nonempty string value parsed as inline
Markdown, one `field` node each, in frontmatter order.

`attrs.name` is the value's dotted field
path, a list item by its index (`product.name`, `authors.0`). Marks, links, wikilinks, images
and TeX math in a value arrive as the same inline nodes as in
[[capabilities/markdown#Document nodes|chapter text]]; numbers, booleans and dates stay data only.

## Authoring example

```markdown
---
aliases: [Short name]
ignored: true
---
```
