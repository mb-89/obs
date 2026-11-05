---
kind: capability
capability:
  id: wikilinks
  summary: Resolve local Markdown and Obsidian note links.
  authoring: Link a vault note with a Markdown link or a double-bracket wikilink.
  dependsOn: ["[[capabilities/markdown]]"]
  inputModel: "[[input-model#Chapter content]]"
---

## What it does

Resolve local Markdown and Obsidian note links.

## Authoring example

```markdown
See [[chapter#Details]].
```
