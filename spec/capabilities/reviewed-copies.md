---
kind: adapter-behavior
capability:
  id: reviewed-copies
  summary: Preserve review comments and block decisions in a portable copy.
  authoring: Save review state through the supported reviewed-copy workflow.
  dependsOn: ["[[capabilities/marks]]", "[[capabilities/references]]"]
  inputModel: "[[input-model#Reviewed copy]]"
---

The register presents the owning metadata as the capability reference.
