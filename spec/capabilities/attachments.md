---
kind: capability
capability:
  id: attachments
  summary: Link or embed vault-local source attachments.
  authoring: Use a relative Markdown link or a supported attachment embed.
  dependsOn: ["[[capabilities/markdown]]", "[[capabilities/embeds]]"]
  source: "[[input-model#Document home and abstract]]"
---

## What it does

Link or embed vault-local source attachments.

## Authoring example

```markdown
![Source](input/data.csv)
```

```csv input/data.csv
value
1
```

## Document node

An `attachments` node is a Markdown image or marked attachment (`![label](file)`): `asset` is the
id of its entry in the Document's `assets` and `label` the authored label. A vault file's asset
carries its bytes ([[architecture#Asset bytes]]), so an adapter reads nothing from the vault. The
node's attributes and the asset's fields are defined by `src/obs/document.schema.json`.

The path resolves next to the referencing note and must stay inside the vault. A file that does
not exist, or a path that leaves the vault, is an input error that names the referencing note and
the remedy.
