---
name: obs-authoring
description: "Write and edit Markdown in obs's dialect: the manifest, notes and their frontmatter, wikilinks and embeds, callouts and marks, queries, Bases and registers, reference notes, quantities, and the fences obs reads (base, cards, cmd, figure, mermaid, plantuml, property-editor, pugh). Use when creating or changing notes of a vault that obs builds, or when checking which syntax obs reads and how to write it."
---

<!-- Generated from spec/capabilities by obs.authoring_skill; do not edit. Regenerate: uv run python -m obs.authoring_skill --notes spec/capabilities --coverage spec/capabilities/coverage.json --destination skills/obs-authoring -->

# Writing for obs

obs builds a document from a vault of Obsidian-compatible Markdown notes: a manifest note lists the chapters, and each note uses the capabilities below. Write only these constructs; obs refuses or ignores what it does not read.

Each capability's section in [references/capabilities.md](references/capabilities.md) holds its authoring line and its tested examples; read the sections of the capabilities a note needs before writing it.

| Capability | What it does | How to write it |
|---|---|---|
| [attachments](references/capabilities.md#attachments) | Link or embed vault-local source attachments. | Use a relative Markdown link or a supported attachment embed. |
| [bases](references/capabilities.md#bases) | Define declarative Base views over canonical note records. | Use a base fence or embed a YAML .base file in a note. |
| [callouts](references/capabilities.md#callouts) | Mark block content with typed, data-only callouts. | Start a blockquote with an Obsidian callout marker such as [!warning]. |
| [cards-metrics](references/capabilities.md#cards-metrics) | Author data-only cards and query-backed document metrics. | Use a cards fence with bounded card and metric mappings. |
| [chapter-inclusion](references/capabilities.md#chapter-inclusion) | Include and navigate source notes through manifest and query references. | Link notes from the manifest and from supported authored references. |
| [command-fences](references/capabilities.md#command-fences) | Request authorized command-derived document content. | Use a cmd fence and run it only through the explicit execution boundary. |
| [count-query](references/capabilities.md#count-query) | Compute one declared count from canonical records. | Declare a count query with its supported source and predicate fields. |
| [embeds](references/capabilities.md#embeds) | Embed supported note and Base content in authored Markdown. | Use a supported exclamation-prefixed wiki embed. |
| [equation-figures](references/capabilities.md#equation-figures) | Plot symbolic equations whose variables move live within their ranges, solved once by the core. | Write a figure fence of kind equations with SymPy equations, their variables (quantity notes or own defaults, ranges and units) and the initial plot. |
| [extensions](references/capabilities.md#extensions) | Add a bounded next Obsidian syntax extension. | Use only an extension with an explicit input-model contract. |
| [figure-descriptor](references/capabilities.md#figure-descriptor) | Describe neutral multi-panel figure data and provenance. | Produce a schema-valid FigureDescriptor with panel geometry, axes, and provenance, and show it as a figure of kind plot. |
| [figures](references/capabilities.md#figures) | Render every figure, whatever its kind, as one generic figure with a shared caption, block id and alternative text. | Write a figure fence with version 1, a kind, an optional caption and alt, and the kind's content inline under content or from a source file. |
| [manifest](references/capabilities.md#manifest) | Define document metadata, ordered chapters, and an optional abstract. | Start a manifest note with frontmatter and one nested list of local note links. |
| [markdown-frontmatter](references/capabilities.md#markdown-frontmatter) | Add structured metadata to a Markdown note. | Put one YAML frontmatter mapping at the beginning of a note. |
| [markdown](references/capabilities.md#markdown) | Render standard Markdown chapter content safely. | Write CommonMark-compatible text, headings, lists, and fenced code. |
| [marks](references/capabilities.md#marks) | Annotate authored content with stable semantic marks. | Add the supported mark syntax to the marked paragraph. |
| [mermaid](references/capabilities.md#mermaid) | Show a Mermaid diagram as a figure, drawn as SVG when the document is built. | Write a mermaid fence, as Obsidian renders it, or a figure fence of kind mermaid with a caption and the diagram inline under content or from a .mmd source file. |
| [plantuml](references/capabilities.md#plantuml) | Show a PlantUML diagram as a figure, drawn as SVG when the document is built, without a server. | Write a plantuml fence, or a figure fence of kind plantuml with a caption and the diagram inline under content or from a .puml source file. |
| [profiles](references/capabilities.md#profiles) | Select constrained note and artifact presentation profiles. | Declare the core obs profile mapping in frontmatter. |
| [property-editors](references/capabilities.md#property-editors) | Opt one existing frontmatter string field of a note into plain-text editing. | Write a property-editor fence with version 1, the field and a label. |
| [pugh-decisions](references/capabilities.md#pugh-decisions) | Decide between options as a Pugh matrix whose bottom line, matrix and weight sensitivity a reader sees as one figure. | Write a pugh fence holding one decision matrix in YAML, with an optional chosen option, each option's sentence, wins and losses, and a checklist. |
| [quantities](references/capabilities.md#quantities) | Express named numeric values and their canonical sources. | Author a quantity note with its supported numeric frontmatter. |
| [queries](references/capabilities.md#queries) | Define reusable, declarative selections and aggregates. | Give a supported query mapping a stable name and reference that name. |
| [references](references/capabilities.md#references) | Resolve reference notes, labels, and external source links. | Use a reference note and supported link text rather than raw external prose links. |
| [registers](references/capabilities.md#registers) | Reuse authored table views as named registers. | Embed a named view from a .base file with a Base embed link. |
| [wikilinks](references/capabilities.md#wikilinks) | Resolve local Markdown and Obsidian note links. | Link a vault note with a Markdown link or a double-bracket wikilink. |
