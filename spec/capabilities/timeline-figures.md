---
kind: capability
capability:
  id: timeline-figures
  summary: Draw dated note records as a lane timeline, one column per lane and one row per day, with named bands such as Today.
  authoring: Write a figure fence of kind timeline whose content names the query that selects the records, their date and lane fields and today.
  dependsOn: ["[[capabilities/figures]]", "[[capabilities/queries]]"]
  source: "[[input-model#Timeline figures]]"
---

## What it does

A timeline figure draws dated notes as a lane timeline inside the figure frame
([[capabilities/figures]]): one column per lane, one row per day that has records, and named
bands, such as Today, between the past rows and the planned rows.

A query selects the records ([[capabilities/queries]]); the fields the content names place each
one. [[input-model#Timeline figures]] owns the content's fields, the row order and the input
errors.

A reader opens a row to list its records per lane, and opens a record to read its text and
follow a link to its note. The rows follow the reader's global filter, as a Sankey figure's
counts do.

A record's flags are chips in one of the tones every other part of a Document uses (neutral,
positive, warning, negative); lanes have no colour of their own. A query that selects nothing
shows one sentence that there are no records, never an empty grid.

## Authoring example

````markdown
```figure
version: 1
kind: timeline
caption: The work of two teams
alt: Records by day and team, with today's band
content:
  records: {where: [{field: kind, equals: work-item}]}
  date: when
  lane: team
  today: 2026-11-16
  lanes: [Build, Review]
  band: state
  bands:
    - {value: doing, label: Today, at: today}
    - {value: later, label: Later, at: end}
  anchor: today
  label: short
  text: summary
  flags: flags
  marker: release
```
^team-work
````

The records are notes such as this one, dated, in a lane and with a flag:

```text work/first-draft.md
---
kind: work-item
when: 2026-11-02
team: Build
short: First draft
summary: The first draft of the plan, written and shared.
flags: [{label: review, tone: warning}]
---
# First draft
```

A record whose `state` is `doing` sits in the Today band, whatever its day; a record whose
`release` is `true` is a labelled marker in its cell, not an item.

## The anchor

With `anchor`, the chapter that holds the figure opens with the anchor row centred in the
viewport, each time it opens at its top; `anchor: today` names the first row after the past
rows. A link to a heading or block of the chapter wins: the chapter opens there.

Without `anchor`, the chapter opens at its top like every other chapter. This is the one
exception to an adapter's rule that a chapter opens at its top.
