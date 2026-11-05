---
kind: capability
capability:
  id: references
  summary: Resolve reference notes, labels, and external source links.
  authoring: Use a reference note and supported link text rather than raw external prose links.
  dependsOn: ["[[capabilities/wikilinks]]", "[[capabilities/markdown-frontmatter]]"]
  inputModel: "[[input-model#Reference notes and link text]]"
---

## What it does

Resolve reference notes, labels, and external source links.

## Authoring example

```markdown
---
kind: glossary
term: Datum
definition: A reference.
---
```
