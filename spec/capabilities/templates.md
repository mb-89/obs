---
kind: capability
capability:
  id: templates
  summary: Mark a manifest as a template filled many times, and a document as filled from one.
  authoring: Give a template manifest obs.template, each of its nodes obs.guidance and one {{slot}} paragraph, and a filled document derived_from.
  dependsOn: ["[[capabilities/manifest]]", "[[capabilities/markdown-frontmatter]]"]
  source: "[[input-model#Templates]]"
---

## What it does

Mark a manifest as a template, a document skeleton filled many times, whose nodes hold their
guidance apart from the text an author fills in, and mark a document as filled from a template,
so a template's new version finds the documents to review ([[input-model#Templates]]).

## Authoring example

A filled document names its template and the version it was filled from:

```markdown
derived_from: {template: requirements, version: "2"}
```

## Document node

A `templates` node carries each part of a template, by `attrs.part`, and a Document that holds one
names `templates` among its capabilities; `document.schema.json` owns the node's shapes.

- `template`: among a template manifest's frontmatter nodes, its `name`, `version` and, where
  given, `source`.
- `guidance`: right after a template node's frontmatter nodes, its `gate`. Its children are one
  `field` node per guidance text, in the order `contents`, `motivation`, `form`, `sources`, each
  with `attrs.name` its key and its text as inline nodes, as a frontmatter field's
  ([[capabilities/markdown-frontmatter#Document node]]).

  An adapter shows it as guidance, visibly apart from the slot and never as filled text.
- `slot`: in place of the node's `{{slot}}` paragraph, with no children: where an author fills
  the section in.
- `derived-from`: among the frontmatter nodes of a note that carries `derived_from`, its
  `template` and `version`, so an adapter names the template a filled document comes from.

A filled document holds no `guidance` and no `slot`: [[input-model#Templates]] refuses both, so
nothing of the template's guidance renders into it.

## Worked example

A template of three nodes, `requirements` at version 2, and one document filled from it. Each
folder is a vault of its own, built from its `manifest.md`; `test/test_templates.py` builds both
from this note.

```text template/manifest.md
---
title: Requirements
obs:
  template: {name: requirements, version: "2", source: an exported requirements template}
---

- [[purpose|Purpose]]
- [[scope|Scope]]
- [[risks|Risks]]

Fill one document per product from this template.
```

```text template/purpose.md
---
obs:
  guidance:
    contents: The problem the product solves, and for whom.
    motivation: Every later section is judged against it.
    form: One paragraph of at most five sentences.
    sources: The product brief.
    gate: mandatory
---

{{slot}}
```

```text template/scope.md
---
obs:
  guidance:
    contents: What the product does and what it leaves to others.
    form: Two lists, in scope and out of scope.
    gate: mandatory
---

{{slot}}
```

```text template/risks.md
---
obs:
  guidance:
    contents: The risks that could stop the product, each with its owner.
    motivation: A risk without an owner is not handled.
    gate: judgment
---

{{slot}}
```

The filled document keeps the template's order and none of its guidance:

```text document/manifest.md
---
title: Pump controller requirements
derived_from: {template: requirements, version: "2"}
---

- [[purpose|Purpose]]
- [[scope|Scope]]
- [[risks|Risks]]
```

```text document/purpose.md
The pump controller keeps the tank level between its limits for the plant operators.
```

```text document/scope.md
- In scope: the level loop and its alarms.
- Out of scope: the pump drives, which the drive supplier owns.
```

```text document/risks.md
The level sensor may drift; the instrument team owns its calibration.
```
