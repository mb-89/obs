---
kind: capability
capability:
  id: extensions
  summary: Add a bounded next Obsidian syntax extension.
  authoring: Use only an extension with an explicit input-model contract.
  dependsOn: ["[[capabilities/markdown]]"]
  source: "[[input-model#Next Obsidian extension]]"
---

## What it does

Add a bounded next Obsidian syntax extension.

## Authoring example

```markdown
> [!note] An explicitly supported extension.
```

## Trusted adapter extensions

An adapter's trusted runtime extensions are not Obsidian syntax extensions. Where an adapter
documents them and how it names their namespace is owned by
[[capabilities/trusted-actions#Adapter extensions|Trusted actions]].
