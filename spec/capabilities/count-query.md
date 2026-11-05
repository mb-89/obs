---
kind: capability
capability:
  id: count-query
  summary: Compute one declared count from canonical records.
  authoring: Declare a count query with its supported source and predicate fields.
  dependsOn: ["[[capabilities/queries]]"]
  source: "[[input-model#One count query]]"
---

## What it does

Compute one declared count from canonical records.

## Authoring example

```markdown
query:
  where: [{field: mark.open_point, exists: true}]
  distinct: mark.open_point
```
