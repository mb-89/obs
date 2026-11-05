---
kind: capability
capability:
  id: manifest
  summary: Define document metadata, ordered chapters, and an optional abstract.
  authoring: Start a manifest note with frontmatter and one nested list of local note links.
  dependsOn: ["[[capabilities/markdown-frontmatter]]", "[[capabilities/wikilinks]]"]
  source: "[[input-model#Manifest contract]]"
---

## What it does

Define document metadata, ordered chapters, and an optional abstract.

The manifest is a note like any other: to keep queries and Bases from selecting it, it marks
itself ignored ([[capabilities/markdown-frontmatter#Ignored notes]]). Selection has no special
case for it.

## Authoring example

```markdown
- [[chapter]]
```
