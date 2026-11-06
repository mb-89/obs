---
kind: capability
capability:
  id: property-editors
  summary: Opt one existing frontmatter string field of a note into plain-text editing.
  authoring: Write a property-editor fence with version 1, the field and a label.
  dependsOn: ["[[capabilities/markdown-frontmatter]]"]
  source: "[[input-model#Reviewed copy]]"
---

## What it does

Opt one existing top-level string field of the note into plain-text editing, with an optional
static projection of other fields for a blank or nonblank edit. The fence is data only; the
input model owns its contract and `input.schema.json` (`propertyEditor`) its shape.
Saving the edit is adapter behaviour, owned by [[capabilities/reviewed-copies]].

## Document node

A `property-editor` fence is one `property-editors` node: `attrs.source` holds the authored
fence and `attrs.spec` the validated mapping. A fence the schema refuses fails the build with
the note's path.

## Authoring example

````markdown
---
explanation: Original
---
```property-editor
version: 1
field: explanation
label: Review explanation
```
````

With a static projection: `blank` holds the fields to write when the edited text is blank,
`nonblank` the fields to write otherwise. Each names other fields of the note with a text,
number, true/false or empty value, or a list of them.

````markdown
---
explanation: Original
status: explained
---
```property-editor
version: 1
field: explanation
label: Review explanation
projection:
  blank: {status: finding}
  nonblank: {status: explained}
```
````
