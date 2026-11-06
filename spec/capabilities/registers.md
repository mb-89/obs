---
kind: capability
capability:
  id: registers
  summary: Reuse authored table views as named registers.
  authoring: Embed a named view from a .base file with a Base embed link.
  dependsOn: ["[[capabilities/bases]]"]
  source: "[[input-model#Registers]]"
---

## What it does

Reuse authored table views as named registers.

## Authoring example

```markdown
![[registers.base#Open points]]
```

The Base file the example embeds, `registers.base` next to the note:

```yaml registers.base
views:
  - type: table
    name: Open points
    filters: 'status == "open"'
    order: [file.name]
```

## Document node

A `registers` node carries everything an adapter needs to render the register, so the adapter
reads nothing from the vault. Its attributes are defined by `src/obs/document.schema.json`:

- `target` and `heading`: the embed as authored, `heading` empty when it names no view.
- `base`: the embedded Base definition (filters, properties, views, `obs` and any adapter namespace), validated
  like a `base` fence ([[generic-tables#Bases filter grammar]]).
- `view`: the index in `base.views` of the view `heading` names, or `null` when the embed names
  none and embeds all views with a selector ([[input-model#Registers]]).
- `rows`: one entry per view of `base.views`, in order: the ids of the records the view
  selects, in `records` order, or, where the view declares `obs.members`, in member order
  ([[generic-tables]]); a row without a note follows the members' rows. The core's one selection evaluator selects them by the
  rules of [[capabilities/bases#Comparisons]], the same that decide which notes the Document
  includes.

The view's `obs.records`, else the base's, names the record type its rows have: `note`,
`chapter`, `tag`, `glossary`, `documentMetadata` or `documentHistory`, `note` when neither
names one. `src/obs/document.schema.json` (`$defs/record`) defines each record type and its
fields; [[generic-tables#Bases filter grammar]] owns how a filter resolves them.

A register embed whose `.base` file does not exist, is not valid Base YAML, or whose heading
names no view of the file is an input error that names the embedding note and the remedy.
