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

The core emits an `extensions` node, and names `extensions` among a Document's capabilities,
only where the vault uses a syntax extension with an explicit input-model contract. None is
chosen yet ([[input-model#Next Obsidian extension]]), so no Document carries it today.
Obsidian syntax that has its own capability is that capability alone: a callout is
[[capabilities/callouts]], never an extension.

## Authoring example

None yet: the example arrives with the first extension's input-model contract. Until then the
example is a counter-example, Obsidian syntax that is not an extension:

```markdown
> [!note] A callout uses the callouts capability, not extensions.
```

## Trusted adapter extensions

An adapter's trusted runtime extensions are not Obsidian syntax extensions. Where an adapter
documents them and how it names their namespace is owned by
[[capabilities/trusted-actions#Adapter extensions|Trusted actions]]. Example:
obs-html's [[obs-html-attachment-replacement|attachment replacement]].
