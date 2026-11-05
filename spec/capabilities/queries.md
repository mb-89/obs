---
kind: capability
capability:
  id: queries
  summary: Define reusable, declarative selections and aggregates.
  authoring: Give a supported query mapping a stable name and reference that name.
  dependsOn: ["[[capabilities/markdown-frontmatter]]"]
  source: "[[input-model#Reusable query ownership]]"
---

## What it does

Define reusable, declarative selections and aggregates.

Queries select from the Document's note records, which [[capabilities/bases#Note records]]
describes; [[capabilities/markdown-frontmatter#Ignored notes]] says which notes a query never
selects. The notes a query in an included note selects are included in the Document too
([[input-model#Chapter content]]).

## Conditions

A query's `where` holds conditions that a note must all meet. A condition names a property
the way a Bases filter does and resolves it the same way
([[generic-tables#Bases filter grammar]]), then tests its text:

- `equals` holds text. It matches when the property's value, or an item of its list, has
  exactly that text. The value's text follows [[capabilities/bases#Comparisons]]: it is
  case-sensitive, a number's text is its shortest form (`1.0` is `1`), and a boolean's text is
  `true` or `false`. Unlike a Bases comparison, `equals: "1"` therefore matches the number `1`,
  because a condition always compares text.
- `exists: true` matches when the value, or an item of its list, has nonblank text.
- A missing property and `null` have no text: they match neither `equals` nor `exists`.

The core evaluates conditions to decide inclusion, the browser for counts, query populations
and figures; both run the `conditions` cases of the shared conformance fixture
`test/fixtures/bases-filter-conformance.json`.

## Authoring example

```markdown
query:
  where: [{field: status, equals: open}]
```
