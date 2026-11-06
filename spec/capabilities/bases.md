---
kind: capability
capability:
  id: bases
  summary: Define declarative Base views over canonical note records.
  authoring: Use a base fence or embed a YAML .base file in a note.
  dependsOn: ["[[capabilities/markdown-frontmatter]]", "[[capabilities/queries]]"]
  source: "[[input-model#Base fences]]"
---

## What it does

Define declarative Base views over canonical note records.

## Note records

The Document's `records` carry one record of type `note` per vault note outside hidden folders,
the manifest included. Each record holds an `id` derived from its path, its vault-relative
`path`, its frontmatter as `fields` and as parsed `fieldNodes`
([[capabilities/markdown-frontmatter#Document node]]). A row a note owns finds its parsed values
on that note's record: a glossary term on its `note`, the manifest's metadata and history rows
on the manifest's. The record of an ignored note also carries
`ignored: true`; a Base never selects it ([[capabilities/markdown-frontmatter#Ignored notes]]).

An adapter evaluates a Base filter on these records,
taking `file.*` properties from `path` and every other property from `fields`, without reading
the vault. The [[input-model#Base fences]] contract owns the filter grammar. The notes a
Base in an included note selects are included in the Document too
([[input-model#Chapter content]]).

## Comparisons

One rule set selects notes everywhere: Bases filters and query conditions, in the core and in
the browser, and the artifact's drill-downs and reader filter. The shared conformance fixture
`test/fixtures/bases-filter-conformance.json` checks every evaluator.

Obsidian's [[obsidian-bases-syntax|Bases syntax]] is the reference for `==` and `!=`. Where
this rule set differs, a good system comes before full compatibility, and the rule says so.

- **Case:** text equals text when the two differ at most in letter case: `"Open"` equals
  `"open"`. Each runtime's case-insensitive regular-expression matching pairs the letters.

  Obsidian compares text case-sensitively; this rule set does not, because a reader selects
  by meaning, not by spelling. A query condition asks for the exact case with its flag
  ([[capabilities/queries#Conditions]]); a Bases filter cannot, as Obsidian's syntax has no
  place for a flag.
- **Property names:** a name matches a frontmatter key that differs at most in letter case,
  at every dotted segment. A key spelled exactly the same wins, otherwise the note's first
  such key. The `note.` prefix and the `file.*` properties are written in lower case.

  Obsidian's reference does not say whether names ignore case; this rule set pairs names
  with values.
- **Types:** text, numbers and booleans never equal each other: the number `1` does not equal
  the text `"1"`, nor `true` the text `"true"`. A whole number equals its decimal form (`1` and
  `1.0`). A list never equals a single literal.
- **Missing properties:** a missing property and `null` equal `null`; empty text and empty
  collections do not.

[[input-model#Bases filter grammar]] owns which comparisons a filter may write.
[[capabilities/queries#Conditions]] applies the same rules to query conditions.

## Authoring example

````markdown
```base
filters: 'kind == "item"'
views:
  - type: table
    order: [file.name]
```
````
