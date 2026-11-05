---
kind: capability
capability:
  id: bases
  summary: Define declarative Base views over canonical note records.
  authoring: Use a base fence or embed a YAML .base file in a note.
  dependsOn: ["[[capabilities/markdown-frontmatter]]", "[[capabilities/queries]]"]
  inputModel: "[[input-model#Base fences]]"
---

## What it does

Define declarative Base views over canonical note records.

## Authoring example

```markdown
```base
filters: 'kind == "item"'
views:
  - type: table
    order: [file.name]
```
```
