---
kind: capability
capability:
  id: pugh-decisions
  summary: Decide between options as a Pugh matrix whose bottom line, matrix and weight sensitivity a reader sees as one figure.
  authoring: Write a pugh fence holding one decision matrix in YAML, with an optional chosen option, each option's sentence, wins and losses, and a checklist.
  dependsOn: ["[[capabilities/figures]]"]
  source: "[[input-model#Pugh decision figures]]"
---

## What it does

A decision is written as a Pugh matrix: options marked against a datum on weighted criteria.
A ```` ```pugh ```` fence holds one matrix in YAML, or a figure fence of kind `pugh`
([[capabilities/figures]]) holds it under `content` or in a `source` file. The core checks it
and carries it as data; it decides nothing.

An adapter decides the matrix with ctrl's engine, `src/core/pugh.js` of github.com/mb-89/ctrl,
carried unchanged from ctrl's commit `2839d765ff04d5586f1f0199203bbebf2d03cd22`. The engine's
own note, ctrl's `design/output/pugh.md`, owns the matrix's shape ("The matrix file") and every
rule of the decision. [[input-model#Pugh decision figures]] owns what obs adds.

## Authoring example

````markdown
```pugh
title: Which message queue
chosen: managed
context: a team of three running its own servers
concern: the queue's upkeep
criteria:
  - {key: latency, label: p99 latency (ms), weight: 3, better: lower, tolerance: 0.2, floor: 1}
  - {key: ops, label: Ease of operation, weight: 2, better: higher, kind: judged}
candidates:
  - {key: current, label: Current queue, what: The queue we run today., values: {latency: 12},
     wins: Nothing to migrate.}
  - {key: managed, label: Managed queue, short: Managed, what: A hosted queue we rent., values: {latency: 14},
     marks: {ops: {mark: [2, 1, 2], because: the vendor runs it}}, wins: No servers to run., losses: A bill every month.,
     success: The on-call log shows no queue incident for a quarter.}
gates:
  - {criterion: latency, maxRatio: 2, why: fails the main job}
datum: {prefer: [current]}
checklist:
  - {item: "Can we leave it within a month?", answer: Not the managed one., pass: false, options: [B]}
```
````

The options are lettered A, B, … in the order `candidates` lists them; a checklist item names
the options it fails by letter. An option's `short` name, at most 5 words, follows its letter
where there is room ("B · Managed").

An option's `success` is its success criterion, one line on what marks it successful once done.

In a chapter whose main content is the decision, the adapter shows the figure under three
headings of its own, Potential solutions, Proposed winner and Details, after the note's text. Each `##` section
after the fence becomes one more tab under Details, named by its heading: `## The record` becomes
a tab "The record", and its text no longer runs under the one-pager.

## The rules

ctrl's engine decides by these rules, each owned by its row of "The rules, and why" in ctrl's
`design/output/pugh.md`, which says why; obs adds none and changes none. The adapter that carries
the engine runs ctrl's tests of these rules, from ctrl's `test/pugh.test.mjs`, under their names.

| Rule | What the engine does | Source in ctrl |
|---|---|---|
| The datum | the first option of `datum.prefer` that fits is the datum | pugh.md, The datum; Pugh's "set a good datum" (design input 48) |
| Measured marks | a value's ratio to the datum's, with the `floor` added to both, is S within the `tolerance`, ±1 up to the `strong` ratio (×2) and ±2 beyond; a missing value is "?" and counts 0 | pugh.md, Measured marks |
| Judged marks | a mark on the same scale against the datum; a list is several raters, its median the mark and its spread shown; a moved datum shifts them by its own mark | pugh.md, Judged marks |
| Hard gates | `max` or `min` on a measured value, before the datum is chosen; a missing value passes | pugh.md, Hard gates |
| Ratio gates | `maxRatio`: worse than that many times the datum's value does not fit; the datum is exempt; on a judged criterion a −− fails | pugh.md, Ratio gates (design input 55) |
| Vetoes, one per reason | `fits: false` (veto `given`), each failing gate (`gate0`, `gate1`, … by its place) and the person's own (`person`); every gate is evaluated, and each tool veto is lifted on its own | pugh.md, Vetoes, one per reason (design inputs 62, 64) |
| External fits | an option may arrive with `fits: false` and `whyNot` | pugh.md, External fits |
| Totals and ranking | the sum of weight × mark; fitting options by total, then `tieBreak` (lower first), then their order | pugh.md, Totals and ranking |
| The suggestion | the first fitting option whose `suggestable` is not false; a `keep` option reads "nothing beats it" | pugh.md, The suggestion (design input 48) |
| Sensitivity | among the fitting, suggestable options: one weight at a time, all weights together, and seeded draws of every weight within ±`step` and of one rater per multi-rater mark | pugh.md, Sensitivity (design input 55) |
| Reasonable; the choice holds | a change is reasonable within ±`step` of each weight and above 0; the choice holds where no reasonable single-weight change ties a runner-up and the winner takes at least `holdShare` of the draws, else it depends on the weights; a tie now depends | pugh.md, Reasonable; the choice holds (design input 55: "it can't be judgment") |
| Weak spots | for each criterion where the suggestion is worse than the datum, the fitting options better there | pugh.md, Weak spots |
| The person's changes | a weight, a mark nudged, an option vetoed, a tool veto lifted, another datum, each with a comment, decided again at once | pugh.md, The person's changes (design inputs 61–64) |

The engine is deterministic: no clock, and its draws come from the `seed` (`sensitivity.seed`, 1
by default), so the same fence gives the same verdict on every build and in every reader's page.

## Fence fields and the engine

The fence is ctrl's matrix file with obs's fields beside it ([[input-model#Pugh decision figures]]).
The adapter hands the engine:

- unchanged, every field of ctrl's matrix file the fence has: `title`, `kind`, `nouns`, `notes`,
  `criteria` (with `tolerance`, `floor` and `kind`), the options' `key`, `label`, `values`,
  `fits`, `whyNot`, `suggestable`, `keep`, `tieBreak` and `note`, `gates`, `datum`, `strong` and
  `sensitivity`;
- an option's mark given with its reason, `{mark, because}`, as the mark alone, a number or a
  rater list;
- the checklist's failed items that name options as one more judged criterion, `checklist`, of
  weight `checklistWeight`;
- the reader's changes as the engine's `overrides`.

`chosen`, `context`, `concern`, `supersededBy` and the options' `short`, `what`, `wins`, `losses`
and `success` are obs's and never reach the engine. Every fence written before the engine's
verdict was shown keeps its meaning: the engine decided it already, and its page now also says
what it computed.
