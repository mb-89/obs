---
kind: capability
capability:
  id: chapter-inclusion
  summary: Include and navigate source notes through manifest and query references.
  authoring: Link notes from the manifest and from supported authored references.
  dependsOn: ["[[capabilities/manifest]]", "[[capabilities/wikilinks]]", "[[capabilities/queries]]"]
  source: "[[input-model#Chapter content]]"
---

## What it does

Include and navigate source notes through manifest and query references.

The manifest's notes, and every note their links, Bases and queries reach, recursively,
become chapters of the Document; [[input-model#Chapter content]] owns the rule and where
unlisted notes go.

## Authoring example

```markdown
- [[chapter]]
```
