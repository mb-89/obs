---
kind: capability
capability:
  id: markdown-frontmatter
  summary: Add structured metadata to a Markdown note.
  authoring: Put one YAML frontmatter mapping at the beginning of a note.
  dependsOn: ["[[capabilities/markdown]]"]
  inputModel: "[[input-model#Markdown body and frontmatter]]"
---

## What it does

Add structured metadata to a Markdown note.

## Authoring example

```markdown
---
aliases: [Short name]
---
```
