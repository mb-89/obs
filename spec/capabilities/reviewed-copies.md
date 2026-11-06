---
kind: adapter-behavior
capability:
  id: reviewed-copies
  summary: Preserve review comments and block decisions in a portable copy.
  authoring: Save review state through the supported reviewed-copy workflow.
  dependsOn: ["[[capabilities/marks]]", "[[capabilities/references]]"]
  source: "[[input-model#Reviewed copy]]"
---

The register presents the owning metadata as the capability reference.

## Core part

A reviewed copy edits canonical notes only through the property-editor contract the core
validates ([[capabilities/property-editors]], [[input-model#Reviewed copy]]). How an adapter saves
a reviewed copy, with its review comments, decisions and reader state, is that adapter's; its
specification is listed in [[appendix/references|References]].
