---
kind: adapter-behavior
capability:
  id: trusted-actions
  summary: Invoke declared trusted runtime actions against canonical source state.
  authoring: Register a trusted action bundle through the explicit runtime boundary.
  dependsOn: ["[[capabilities/markdown-frontmatter]]", "[[capabilities/canonical-references]]"]
  source: "[[input-model#Trusted runtime and canonical replacement]]"
---

The register presents the owning metadata as the capability reference.
