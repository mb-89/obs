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

## Authoring example

```markdown
- [[chapter]]
```
