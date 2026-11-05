---
kind: capability
capability:
  id: queries
  summary: Define reusable, declarative selections and aggregates.
  authoring: Give a supported query mapping a stable name and reference that name.
  dependsOn: ["[[capabilities/markdown-frontmatter]]"]
  source: "[[input-model#Reusable query ownership]]"
---

## What it does

Define reusable, declarative selections and aggregates.

Queries select from the Document's note records, which [[capabilities/bases#Note records]]
describes.

## Authoring example

```markdown
query:
  where: [{field: status, equals: open}]
```
