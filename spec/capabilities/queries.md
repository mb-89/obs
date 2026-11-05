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
the way a Bases filter does and resolves it by the same rules
([[generic-tables#Bases filter grammar]], [[capabilities/bases#Comparisons]]), then tests its
text:

- `equals` holds text. It matches when the property's value, or an item of its list, has
  that text, ignoring case as [[capabilities/bases#Comparisons]] does. A number's text is its
  shortest form (`1.0` is `1`), and a boolean's text is `true` or `false`. Unlike a Bases
  comparison, `equals: "1"` therefore matches the number `1`, because a condition always
  compares text.
- `matchCase: true` is the flag that makes one `equals` condition case-sensitive, like a
  regular expression's flag: `{field: status, equals: Open, matchCase: true}` does not match
  `open`.
- `exists: true` matches when the value, or an item of its list, has nonblank text.
- A missing property and `null` have no text: they match neither `equals` nor `exists`.
- `mark` and `mark.<category>` name the note's marks when its frontmatter has no property of
  that name: `mark` holds the categories of its marks, `mark.<category>` the identifiers of
  that category ([[capabilities/marks]]). Obsidian has no such property; marks are content a
  query needs to count.

  No other derived field is a property: a title, a slug, the text or a reader alias
  ([[artifact-ui]]) selects nothing in a condition. A `distinct` count and a Sankey node's
  `unique` read their property the same way.

The core evaluates conditions to decide inclusion, the browser for counts, query populations,
figures and drill-downs; both run the `conditions` cases of the shared conformance fixture
`test/fixtures/bases-filter-conformance.json`.

## Authoring example

```markdown
query:
  where: [{field: status, equals: open}]
```
