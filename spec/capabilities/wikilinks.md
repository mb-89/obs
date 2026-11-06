---
kind: capability
capability:
  id: wikilinks
  summary: Resolve local Markdown and Obsidian note links.
  authoring: Link a vault note with a Markdown link or a double-bracket wikilink.
  dependsOn: ["[[capabilities/markdown]]"]
  source: "[[input-model#Chapter content]]"
---

## What it does

Resolve local Markdown and Obsidian note links.

## Authoring example

```markdown
See [[chapter#Details]].
```

## Document node

A `wikilinks` node keeps the `target`, `heading` and `label` as authored and adds `chapter`: the
id of the included chapter the target resolves to, or `null` when the note is outside the
manifest. This holds wherever the node sits, in chapter content or in a field node of a note
record ([[capabilities/bases#Note records]]). Adapters link by `chapter` and never derive it from `target`. The node's attributes
are defined by `src/obs/document.schema.json`.

## Links inside a figure

A link inside a figure is a link like any other. The core reads every link in a figure's SVG:
an `svg` figure, an SVG `image`, and the SVG it draws for a `mermaid` or `plantuml` figure.

It reads each `a` element's `href` or `xlink:href` that names no URL scheme and no fragment of
the drawing, and wikilink text (`[[note]]`, `[[note#heading]]`, `[[note|label]]`) within one
text run. Mermaid's `click <node> href "note"` and PlantUML's `[[note]]` draw such `a` elements;
Mermaid's strict security level keeps them.

Each link resolves by the prose rule ([[input-model#Remaining chapter content]]) and includes
the note it reaches. It warns or fails as a prose link does, naming the note, the figure (its
line and fence) and the target.

Each distinct link is one `wikilinks` node, a child of the figure's body node, in SVG order.
Its `svg` attribute holds the link exactly as the SVG does, the `href` value or the wikilink
text with its brackets, by which an adapter finds where it links in the drawing.
