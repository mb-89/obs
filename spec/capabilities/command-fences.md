---
kind: capability
capability:
  id: command-fences
  summary: Request authorized command-derived document content.
  authoring: Use a cmd fence and run it only through the explicit execution boundary.
  dependsOn: ["[[capabilities/markdown]]"]
  inputModel: "[[input-model#Command-derived content]]"
---

## What it does

Request authorized command-derived document content.

## Authoring example

```markdown
```cmd
Write-Output "Derived content"
```
```
