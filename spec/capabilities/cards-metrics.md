---
kind: capability
capability:
  id: cards-metrics
  summary: Author data-only cards and query-backed document metrics.
  authoring: Use a cards fence with bounded card and metric mappings.
  dependsOn: ["[[capabilities/markdown-frontmatter]]", "[[capabilities/queries]]"]
  source: "[[input-model#Document home and abstract]]"
---

## What it does

Author data-only cards and query-backed document metrics.

## Authoring example

````markdown
```cards
{"version": 1, "cards": [{"title": "Coverage", "body": "Current state."}]}
```
````

## Fields

`input.schema.json` (`$defs.cards`) owns each field's constraints; this list owns what each
field means. [[input-model#Document home and abstract]] owns how adapters present them,
[[input-model#Chapter content]] which notes a card includes.
Conditions are [[capabilities/queries#Conditions]]; a query reference names a vault note by
its path without `.md`.

- `version`: always `1`.
- `cards`: one to eight cards.
- `cards[].title`: the card's title, inline Markdown (see [Document node](#document-node)).
- `cards[].body`: Markdown, parsed like chapter content (see [Document node](#document-node)).
- `cards[].metricStyle`: `pills` or `lines`; how an adapter lays out the metrics.
- `cards[].obs`: the core's namespace for a card's fields.
- `cards[].obs.metricsFrom`: a metric series: one metric per entry of a list held in
  another note's frontmatter, instead of hand-written metrics.
- `cards[].obs.metricsFrom.sourceNote`: the note (query reference) that holds the list.
- `cards[].obs.metricsFrom.property`: the dotted path of the list in that note's
  frontmatter.
- `cards[].obs.metricsFrom.labelProperty`: the entry field that is the metric's label;
  labels are unique and nonblank.
- `cards[].obs.metricsFrom.distinctProperty`: the entry field that is the metric's
  `distinct` field.
- `cards[].obs.metricsFrom.where`: the conditions every series metric counts.
- `cards[].obs.metricsFrom.tone`: the tone of every series metric, as a metric's `tone`.
- `cards[].obs.metricsFrom.toneRules`: the tone rules of every series metric, as a
  metric's `toneRules`.
- `cards[].obs.metricsFrom.link`: routes each series metric to its drill-down; see
  [Drill-downs](#drill-downs).
- `cards[].obs.metricsFrom.link.note`: the note (query reference) whose table it opens.
- `cards[].obs.metricsFrom.link.groupProperty`: the property that holds an entry's label;
  each series metric then selects the records of `where` whose property equals its label.
- `cards[].metrics`: up to 64 metrics; a card without metrics is static.
- `cards[].metrics[].key`: an optional stable identifier for the metric.
- `cards[].metrics[].obs`: the core's namespace for a metric's fields.
- `cards[].metrics[].obs.projection`: the name of a trusted record projection the metric
  counts over instead of the canonical fields; lowercase, dots, underscores and hyphens.
- `cards[].metrics[].from`: the quantity note (query reference) whose query narrows the
  population, as a query's `from`.
- `cards[].metrics[].secondary`: another query-backed quantity note shown in parentheses
  after the value; requires `from`.
- `cards[].metrics[].toneRules`: up to eight first-match rules, each `value` (`primary`,
  `secondary` or `remaining`, the denominator minus the numerator), `when` (`zero` or
  `positive`) and `tone`; an empty denominator stays `neutral`.
- `cards[].metrics[].label`: the metric's label, inline Markdown (see [Document node](#document-node)).
- `cards[].metrics[].where`: the conditions of the counted records.
- `cards[].metrics[].denominator`: the conditions of the population; the value becomes a
  percentage, and an empty population shows `-`.
- `cards[].metrics[].distinct`: counts distinct values of this property instead of records.
- `cards[].metrics[].link`: an internal fragment (`#chapter` or `#chapter/heading`) naming
  the table the value drills down to. See [Drill-downs](#drill-downs).
- `cards[].metrics[].secondaryLink`: the same for the secondary value; requires `secondary`.
- `cards[].metrics[].tone`: `neutral`, `positive`, `warning` or `negative`; the tone when no
  rule matches.

## Drill-downs

A metric's drill-down shows exactly the rows its value counts, so it is derived, never
written: an adapter filters the linked table by the metric's conditions, those of its `from`
quantity's query chain followed by its `where`, and a `secondaryLink` by the `secondary`
quantity's query chain. A linked series metric's conditions are the series' `where` followed
by an `equals` condition of `link.groupProperty` on its label; its count and its drill-down
both select them. Each condition selects as [[capabilities/queries#Conditions]] says, so the
label is compared by the one case folding. A metric with `obs.projection` counts the records as
that projection shows them; its drill-down selects through the same projection, so while the
projection is active the table shows the rows the value counts, not those its canonical
fields would select.
The core refuses a `link` or `secondaryLink` that writes its own `?tableFilter=`, naming the
card and the field, because a hand-written filter can contradict the conditions it stands for.

## Document node

A `cards` fence is one `cards-metrics` node. Its `attrs` hold the authored `source` and the
validated `spec`; `document.schema.json` owns the node's shape.

Its `children` are one `document` node per card, in the order of `spec.cards`. Each holds that
card's `body` parsed like chapter content, and in its `attrs` the card's `title` and its
metrics' `labels` (one per metric of `metrics`, in their order) as inline nodes, parsed like a
paragraph's text: a wikilink in them carries the one link label
([[capabilities/wikilinks#Link text]]). An adapter renders titles and labels from these nodes
and parses no title or label text. A series metric's label is the frontmatter value it counts
by, and shows as that text.

Paragraphs, lists, links, wikilinks (with `attrs.chapter`), callouts and capability fences
(`base`, `cmd`, `figure`, `cards`, `property-editor`) arrive as the same node trees, and the
Document names every capability they use. A `cards` fence in a card body nests the same way.
