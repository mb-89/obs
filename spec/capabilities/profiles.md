---
kind: capability
capability:
  id: profiles
  summary: Select constrained note and document presentation profiles.
  authoring: Declare the supported obsHtml profile mapping in frontmatter.
  dependsOn: ["[[capabilities/markdown-frontmatter]]"]
  inputModel: "[[input-model#Profiles]]"
---

## What it does

Select constrained note and document presentation profiles.

## Authoring example

```markdown
---
obsHtml: {document: false}
---
```
