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

Every place that holds Markdown yields these nodes: chapter and abstract text, list items,
callout, quote and card bodies, table cells, and frontmatter values
([[capabilities/markdown-frontmatter#Document node]]). A list item holds any block, including a
callout.
