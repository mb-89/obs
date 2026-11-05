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
`path` and its frontmatter as `fields`.

An adapter evaluates a Base filter on these records,
taking `file.*` properties from `path` and every other property from `fields`, without reading
the vault. The [[input-model#Base fences]] contract owns the filter grammar.

## Authoring example

````markdown
```base
filters: 'kind == "item"'
views:
  - type: table
    order: [file.name]
```
````
