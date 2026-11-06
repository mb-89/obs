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

A `wikilinks` node keeps the `target` and `heading` as authored, carries the `label` of
[[#Link text]] and adds `chapter`: the id of the included chapter the target resolves to, or
`null` when the note is outside the manifest. This holds wherever the node sits, in chapter content or in a field node of a note
record ([[capabilities/bases#Note records]]).

Adapters link by `chapter` and never derive it from `target`. The node's attributes are defined
by `src/obs/document.schema.json`.

A link names its own note by its heading alone: `[[#Heading]]` and `[[#^name]]` have an empty
`target`, and `chapter` is the chapter they sit in.

A block link (`[[#^name]]` within its note, `[[note#^name]]` across notes) targets a figure:
`figure` is the block id of the `figures` node in `chapter` that carries it
([[input-model#Figure captions and references]]).

A block id that no figure in the target note carries is a build error that names the note, the
link and this page; so is a block id two figures of one note carry. A link to a missing note stays the missing-note warning.

The Markdown form is the same block link and the same `wikilinks` node:
`[label](note.md#^name)` keeps `note.md` as its `target` and its link text as its `label`;
`[](note.md#^name)` is unaliased, labelled by [[#Link text]] as `[[note#^name]]` is; and
`[](#^name)` is `[[#^name]]`. For example, [the rendered figure](figures.md#^generic-figure)
links the figure of [[capabilities/figures#Rendered example]].

## Link text

A link's `label` is the text an adapter shows, as Obsidian shows it (decided 6 Nov 2026). The
core sets it by one rule, for a link in prose, in a field and inside a figure alike:

- A link with `|label` shows that label.
- An unaliased link to a heading or block of another note shows the note's title, ` > ` and the
  heading as written: `[[command-fences#Authorization]]` shows `Command Fences > Authorization`.
  The title is the note's chapter title, else its title as authored
  ([[input-model#Reference notes and link text]]); for a missing note, the target as written.
- An unaliased link to a heading or block of its own note (`[[#Authorization]]`, `[[#^name]]`)
  shows the heading alone: `Authorization`, `^name`.
- An unaliased link to a whole note keeps its target as written; the adapter shows it by the
  note's kind ([[input-model#Reference notes and link text]]).

An adapter that shows something other than the label for an unaliased link, such as a figure
number, tells it from an aliased one by comparing the label with this rule.

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
