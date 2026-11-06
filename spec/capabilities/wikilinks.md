---
kind: capability
capability:
  id: wikilinks
  summary: Resolve local Markdown and Obsidian note links.
  authoring: Link a vault note with a Markdown link or a double-bracket wikilink.
  dependsOn: ["[[capabilities/markdown]]"]
  source: "[[input-model#Chapter content]]"
---

## What it does

Resolve local Markdown and Obsidian note links.

## Authoring example

```markdown
See [[chapter#Details]].
```

## Document node

A `wikilinks` node keeps the `target`, `heading` and `label` as authored and adds `chapter`: the
id of the included chapter the target resolves to, or `null` when the note is outside the
manifest. This holds wherever the node sits, in chapter content or in a field node of a note
record ([[capabilities/bases#Note records]]). Adapters link by `chapter` and never derive it from `target`. The node's attributes
are defined by `src/obs/document.schema.json`.

A block link (`[[#^name]]` within its note, `[[note#^name]]` across notes) targets a figure:
`[[#^name]]` has an empty `target` and, unaliased, the `label` `#^name`; `figure`
is the block id of the `figures` node in `chapter` that carries it
([[input-model#Figure captions and references]]). A block id that no figure in the target note
carries is a build error that names the note, the link and this page; so is a block id two
figures of one note carry. A link to a missing note stays the missing-note warning.
