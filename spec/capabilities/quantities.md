---
kind: capability
capability:
  id: quantities
  summary: Express named numeric values and their canonical sources.
  authoring: Author a quantity note with its supported numeric frontmatter.
  dependsOn: ["[[capabilities/queries]]", "[[capabilities/markdown-frontmatter]]"]
  inputModel: "[[input-model#Numeric-value notes]]"
---

## What it does

Express named numeric values and their canonical sources.

## Authoring example

```markdown
---
kind: quantity
value: 42
---
```
