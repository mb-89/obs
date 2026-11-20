---
kind: capability
capability:
  id: profiles
  summary: Select constrained note and artifact presentation profiles.
  authoring: Declare the core obs profile mapping in frontmatter.
  dependsOn: ["[[capabilities/markdown-frontmatter]]"]
  source: "[[input-model#Profiles]]"
---

## What it does

Select constrained note and artifact presentation profiles.

## Authoring example

```markdown
---
obs: {document: false}
---
```

## Document node

A note whose frontmatter has `obs` gets a `profiles` node whose `profile` is that mapping as
authored; `note-profile.schema.json` validates it. An adapter's own namespace, such as a
presentation mapping in the manifest, is not in it: the adapter reads that from the
frontmatter itself ([[input-model#Core and adapter namespaces]]).

The manifest's `obs.style` declares the vault's style, a style module pinned to a commit; the
Document's `style` carries its identity ([[architecture#Declared style]]).
