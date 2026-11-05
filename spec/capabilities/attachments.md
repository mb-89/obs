---
kind: capability
capability:
  id: attachments
  summary: Link or embed vault-local source attachments.
  authoring: Use a relative Markdown link or a supported attachment embed.
  dependsOn: ["[[capabilities/markdown]]", "[[capabilities/embeds]]"]
  inputModel: "[[input-model#Document home and abstract]]"
---

## What it does

Link or embed vault-local source attachments.

## Authoring example

```markdown
![Source](input/data.csv)
```
