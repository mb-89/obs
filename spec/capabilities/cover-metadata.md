---
kind: adapter-behavior
capability:
  id: cover-metadata
  summary: Supply constrained cover metadata and document history.
  authoring: Set supported manifest frontmatter properties.
  dependsOn: ["[[capabilities/manifest]]", "[[capabilities/markdown-frontmatter]]"]
  inputModel: "[[input-model#Cover metadata and history]]"
---

The register presents the owning metadata as the capability reference.
