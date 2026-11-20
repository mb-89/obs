---
kind: adapter-behavior
capability:
  id: cover-metadata
  summary: Supply constrained cover metadata and document history.
  authoring: Set supported manifest frontmatter properties.
  dependsOn: ["[[capabilities/manifest]]", "[[capabilities/markdown-frontmatter]]"]
  source: "[[input-model#Cover metadata and history]]"
---

The register presents the owning metadata as the capability reference.

## Core part

The core reads and validates the manifest's cover fields and `history`
([[input-model#Cover metadata and history]]) and emits them as records: a `documentMetadata`
row per field and a `documentHistory` row per history entry. How an adapter presents the cover
and History is that adapter's; its specification is listed in [[appendix/references|References]].
