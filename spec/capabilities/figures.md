---
kind: capability
capability:
  id: figures
  summary: Render declared figures from canonical records.
  authoring: Declare a supported figure mapping in Markdown frontmatter or a fenced block.
  dependsOn: ["[[capabilities/markdown-frontmatter]]", "[[capabilities/queries]]"]
  source: "[[input-model#Remaining chapter content]]"
---

## What it does

Render declared figures from canonical records.

## Authoring example

```markdown
```figure
source: records
```
```
