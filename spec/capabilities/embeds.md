---
kind: capability
capability:
  id: embeds
  summary: Embed supported note and Base content in authored Markdown.
  authoring: Use a supported exclamation-prefixed wiki embed.
  dependsOn: ["[[capabilities/wikilinks]]"]
  source: "[[input-model#Chapter content]]"
---

## What it does

Embed supported note and Base content in authored Markdown.

## Authoring example

```markdown
![[shared-note]]

![[vision#^statement]]

![[vision#Pitch]]
```

The first links to the note's chapter; the second shows the block that carries `^statement`; the
third shows the section under the heading Pitch.

## Document node

An `embeds` node keeps the `target` as authored and adds `chapter`: the id of the included
chapter the target resolves to, or `null` when the note is outside the manifest. The node's
attributes are defined by `src/obs/document.schema.json`.

An embedded vault file that is not a note (`![[figure.png]]`) also carries `asset`: the id of its
entry in the Document's `assets`, which holds the file's bytes ([[architecture#Asset bytes]]).

The file resolves next to the embedding note, then from the vault root, then by its case-insensitive file
name, which must be unique ([[input-model#Document home and abstract]]). A missing file or an
ambiguous name is an input error that names the embedding note and the remedy.

### Block and section embeds

An embed of a block (`![[note#^name]]`) or of a section (`![[note#Heading]]`) shows that block
or section in place, as Obsidian does, with a link to where it lives; the passage is written once
and reused by reference (the owner's request of 17 Nov 2026).

- **The node.** Its `embeds` node keeps `target` and `chapter`, and adds `heading`, the fragment
  as written (`^name` or `Heading`), as a `wikilinks` node does, and `block`, the id of the node
  it shows in `chapter`.

  A whole-note embed and a file embed keep only today's attributes, so their derived ids stay
  ([[input-model#Derived ids]]). A `.base` embed's `#View` names the register's view
  ([[capabilities/registers]]); it is no fragment.
- **A block.** `^name` names the block that carries it, as a block link does
  ([[input-model#Explicit ids]]): a paragraph, a list item, a list, a table, a quote, a callout,
  a code block or a figure. A `^name` on a heading names that heading's section.
- **A section.** A heading fragment names the heading the link `[[note#Heading]]` reaches: the
  note's first heading whose text, without a trailing `^name`, reads as the fragment does once
  each is lower-cased and every run of characters other than letters and digits is one dash.

  A section is its heading and the blocks after it, up to the next heading of the same or a higher
  level among its siblings.
- **Missing targets.** An embed of a block id no block of the target note carries, or of a
  heading the note lacks, is an input error in the core's one form,
  `<note path>: embed <the embed as written>: <what is wrong>. <remedy>`.

  The remedy lists the target note's block ids (each as `^name`) or its headings, in order and up
  to ten, or says the note has none and how to add one. An embed of a missing note stays the
  missing-note warning.
- **Cycles.** Embeds that show each other, directly or through other embeds, are an input error.
  It names each embed of the cycle as written, with its note, in the order they show each other,
  and says to link one of them instead.

  The build ends; nothing recurses. An embed inside a shown block that closes no cycle is shown
  too.
- **Where it resolves.** The core checks a block id where it checks block links, finds a heading
  among the target note's sections, sets `block` once block ids are assigned, then checks for
  cycles; `src/obs/embeds.py` holds that lookup and the cycle search as pure functions.

A whole-note embed stays a link to its chapter: a chapter shown inside another repeats it in the
document, and existing vaults do not change. An embed `![[#^name]]` within its own note stays
literal text, since it repeats a block on one page. Heading paths (`note#Part#Detail`) are not
read: nothing asks for them.
