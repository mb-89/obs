---
kind: adapter-behavior
capability:
  id: report-behavior
  summary: Declare portable report behavior without executable author code.
  authoring: Use the bounded input mappings described by the input model.
  dependsOn: ["[[capabilities/manifest]]", "[[capabilities/markdown-frontmatter]]"]
  inputModel: "[[input-model#Report behavior]]"
---

The register presents the owning metadata as the capability reference.
