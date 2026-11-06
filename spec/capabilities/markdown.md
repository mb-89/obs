---
kind: capability
capability:
  id: markdown
  summary: Render standard Markdown chapter content safely.
  authoring: Write CommonMark-compatible text, headings, lists, and fenced code.
  dependsOn: []
  source: "[[input-model#Remaining chapter content]]"
---

## What it does

Render standard Markdown chapter content safely.

## Authoring example

```markdown
# Chapter

Ordinary *emphasis*, **strong**, ~~struck~~, `code` and $x^2$ text.

| Column |
|---|
| A **cell** |

> A quotation.
```

## Document nodes

The Document keeps everything the author wrote, without its style. The supported dialect is
CommonMark with pipe tables, `~~strikethrough~~` and TeX math (`$x$`, `$$x$$`). Its constructs
arrive as structural nodes, which every adapter renders; `document.schema.json` lists them
(`structuralType`) and owns their shape:

- blocks: `section` (a heading), `paragraph`, `list` and `list-item`, `code` (fenced or
  indented, `attrs.language`), `quote` (a blockquote that is not a
  [[capabilities/callouts|callout]]), `table` with `table-row` and `table-cell`
  (`attrs.header`, and `attrs.align` where the delimiter row sets one), display `math`, and
  `rule` (a thematic break: `---`, `***` or `___` on its own line);
- inline: `text` (link text carries `attrs.link`), `emphasis`, `strong`, `strikethrough`
  (each holding the inline nodes it marks, so marks nest), inline `code` and `math`
  (the formula as `text`; `attrs.display` is false for `$x$` and true for `$$x$$` inside a
  line, which Obsidian shows as display math).

A block node is never a paragraph's child, always its sibling. Where one is written inside a
paragraph, the core splits the paragraph around it: the text before and the text after become
paragraphs of their own with their authored characters, and a paragraph left with only
whitespace is dropped, so an embed alone in its paragraph replaces it.

The block nodes are Markdown's blocks (`section`, `paragraph`, `list`, `list-item`, `quote`,
`table`, `table-row`, `table-cell`, `rule`), `registers`, a note's `embeds` (an embedded file,
which names an asset, stays inline), `figures`, `cards-metrics` and `callouts`.
`document.schema.json` holds the list (`blockNode`) and refuses a paragraph that holds one.

Display math on its own line arrives as a block `math` node; `$$x$$` inside a line stays inline.

A `list` says whether it is numbered (`attrs.ordered`) and whether it was authored tight
(`attrs.tight`): true where no blank line separates its items or their blocks, as CommonMark
defines a tight list, so an adapter renders a loose list's paragraphs as paragraphs.

Every place that holds Markdown yields these nodes: chapter and abstract text, list items,
callout, quote and card bodies, table cells, frontmatter values
([[capabilities/markdown-frontmatter#Document node]]), and as inline nodes callout titles
([[capabilities/callouts#Document node]]), card titles and metric labels
([[capabilities/cards-metrics#Document node]]) and figure captions.

An adapter renders them from the nodes and parses no source text. A list item holds any block, including a
callout.
