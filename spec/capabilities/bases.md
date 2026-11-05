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
`path` and its frontmatter as `fields`. The record of an ignored note also carries
`ignored: true`; a Base never selects it ([[capabilities/markdown-frontmatter#Ignored notes]]).

An adapter evaluates a Base filter on these records,
taking `file.*` properties from `path` and every other property from `fields`, without reading
the vault. The [[input-model#Base fences]] contract owns the filter grammar. The notes a
Base in an included note selects are included in the Document too
([[input-model#Chapter content]]).

## Comparisons

Obsidian's [[obsidian-bases-syntax|Bases syntax]] is the reference: `==`
and `!=` work on any value, text, numbers and booleans are distinct primitive types, and text
comparison is case-sensitive (a filter that wants another case calls
[[obsidian-bases-functions|lower()]], which this subset does not support).

Every evaluator, in the core and in the browser, follows these rules, and the shared
conformance fixture `test/fixtures/bases-filter-conformance.json` checks them:

- **Case:** text equals text only with the same characters in the same case; `"Open"` does not
  equal `"open"`.
- **Types:** text, numbers and booleans never equal each other: the number `1` does not equal
  the text `"1"`, nor `true` the text `"true"`. A whole number equals its decimal form (`1` and
  `1.0`). A list never equals a single literal.
- **Missing properties:** a missing property and `null` equal `null`; empty text and empty
  collections do not.

[[generic-tables#Bases filter grammar]] owns which comparisons a filter may write.
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
