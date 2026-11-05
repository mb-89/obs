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
Base's `obsHtml.members` list, which only narrows what the Base selects. Any other value than
`true` or `false` is an error that names the note. The note's record carries `ignored: true` ([[capabilities/bases#Note records]]).

## Authoring example

```markdown
---
aliases: [Short name]
ignored: true
---
```
