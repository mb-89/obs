---
kind: capability
capability:
  id: figures
  summary: Render every figure, whatever its kind, as one generic figure with a shared caption, block id and alternative text.
  authoring: Write a figure fence with version 1, a kind, an optional caption and alt, and the kind's content inline under content or from a source file.
  dependsOn: ["[[capabilities/markdown-frontmatter]]", "[[capabilities/queries]]"]
  source: "[[input-model#Remaining chapter content]]"
---

## What it does

Every figure is one generic figure of a kind: `image`, `svg`, `sankey`, `plot` (a stored-data
FigureDescriptor, [[capabilities/figure-descriptor]]), `equations` (symbolic equations plotted
live, [[capabilities/equation-figures]]), `mermaid` ([[capabilities/mermaid]]) or `plantuml`
([[capabilities/plantuml]]). The fence carries what every kind shares,
`caption` and `alt`, and the kind's content: inline under `content`, or from `source`, a file
relative to the note inside the vault, exactly one of the two. A `^name` line directly after the
fence is the figure's block id. The core emits one `figures` node per fence; its one child is
the kind's body ([[input-model#Remaining chapter content]], Figure input direction).

## Authoring example

````markdown
```figure
version: 1
kind: sankey
caption: How requests flow through review.
source: review-flow.json
countLabels: {unit: requests}
```
^review-flow

```figure
version: 1
kind: image
caption: The inline variant of an image is SVG markup.
content: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"/></svg>'
```
````

The Sankey example's graph file:

```json review-flow.json
{"version": 1,
 "nodes": [{"id": "open", "label": "Open", "stage": 0}, {"id": "done", "label": "Done", "stage": 1}],
 "links": [{"source": "open", "target": "done", "value": 3}]}
```

## Rendered example

This figure is rendered, not quoted; [[capabilities/wikilinks]] links it by its block id.

```figure
version: 1
kind: image
caption: One generic figure of kind image, with its block id.
alt: A filled circle.
source: generic-figure.svg
```
^generic-figure
