---
kind: adapter-behavior
capability:
  id: source-archive
  summary: Include reproducible source material in an authored report.
  authoring: Request source embedding through the explicit build option and declared inputs.
  dependsOn: ["[[capabilities/manifest]]", "[[capabilities/attachments]]"]
  source: "[[input-model#Optional reproduction archive]]"
---

The register presents the owning metadata as the capability reference.
