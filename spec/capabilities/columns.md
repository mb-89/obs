---
kind: capability
capability:
  id: columns
  summary: Set two blocks of Markdown side by side as an explicit two-column block.
  authoring: Wrap two columns in three standalone ||| lines; the opening line may weight them, ||| 1:2.
  dependsOn: ["[[capabilities/markdown]]"]
  source: "[[input-model#Document home and abstract]]"
---

## What it does

Set two blocks of Markdown side by side as an explicit two-column block: a claim beside its
evidence, a card beside a table. [[input-model#Document home and abstract]] owns the `|||`
contract; this note owns what the core reads from it and the Document node it gives.

## Authoring example

```markdown
||| 1:2
**Claim.** The limits hold.
|||
| Limit | Measured |
| --- | --- |
| 20 µm | 12 µm |
|||
```

## Delimiters

A delimiter is a top-level line of `|||`, after at most three spaces, and on the opening line
only, after whitespace, two weights `a:b`. The core reads one only where the adapter's
capability reference names `columns`; without it the line is the text it was before.

- Each successive group of three delimiters of a note is one block: opening, separator, closing.
  Several blocks may follow one another, in a chapter and in the manifest's home alike.
- A delimiter ends a paragraph or a pipe table without a blank line, as a thematic break does.
- `|||` inside fenced or four-space indented code, or within a line of prose, is text.
- Delimiters are read in a note's own text: the body of a card is a single column already, so a
  `|||` line there is the text it is without the capability.

## Input errors

Each of these fails the build with the core's one message form, naming the note and the block by
its number in the note, `<note>: columns block <n>: <problem>. <remedy>.`:

- a block without its closing line, or without its separator;
- a nested block, which reads as a column without content or as an unclosed block;
- a column that holds no Markdown block once `%%` comments are removed;
- weights that are not two integers from 1 to 8;
- weights on the separator or the closing line;
- a delimiter inside a list item or a blockquote.

## Document node

A block is one `columns` node, and a Document that holds one names `columns` among its
capabilities. Its `attrs.weights` is the authored weight pair, `[1, 1]` where the opening line
names none; `document.schema.json` owns the node's shape.

Its `children` are exactly two `document` nodes, the first and the second column, each holding
its column's blocks parsed like chapter content, as a card's body is held
([[capabilities/cards-metrics#Document node]]).

Headings with their link targets, paragraphs, lists, tables, callouts, marks, `cards` fences and
`base` fences arrive as the same node trees, and the Document names every capability they use. A
`base` fence in a column is one table, as it is outside a block.

The block, each column and each block in a column carry block node ids
([[input-model#Block node ids]]); the block and its columns are containers, so editing a
column's text keeps their ids. An adapter shows the columns side by side in their weights' ratio
and stacks them, first above second, only where the reader is too narrow for both.
