---
kind: capability
capability:
  id: embeds
  summary: Embed supported note and Base content in authored Markdown.
  authoring: Use a supported exclamation-prefixed wiki embed.
  dependsOn: ["[[capabilities/wikilinks]]"]
  source: "[[input-model#Chapter content]]"
---

## What it does

Embed supported note and Base content in authored Markdown.

## Authoring example

```markdown
![[shared-note]]
```

## Document node

An `embeds` node keeps the `target` as authored and adds `chapter`: the id of the included
chapter the target resolves to, or `null` when the note is outside the manifest. The node's
attributes are defined by `src/obs/document.schema.json`.

An embedded vault file that is not a note (`![[figure.png]]`) also carries `asset`: the id of its
entry in the Document's `assets`, which holds the file's bytes ([[architecture#Asset bytes]]).

The file resolves next to the embedding note, then from the vault root, then by its case-insensitive file
name, which must be unique ([[input-model#Document home and abstract]]). A missing file or an
ambiguous name is an input error that names the embedding note and the remedy.
