---
kind: capability
capability:
  id: profiles
  summary: Select constrained note and artifact presentation profiles.
  authoring: Declare the supported obsHtml profile mapping in frontmatter.
  dependsOn: ["[[capabilities/markdown-frontmatter]]"]
  source: "[[input-model#Profiles]]"
---

## What it does

Select constrained note and artifact presentation profiles.

## Authoring example

```markdown
---
obsHtml: {document: false}
---
```
