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
