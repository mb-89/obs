---
bottom line: Python owns source semantics and emits one canonical report store; browser views derive from that store.
---

# Architecture

The global Filter owns one compiled query and its applied expression. Figure gestures and
facets use that same owner; invalid drafts do not replace it. The optional profile contract
is owned by [[input-model]] and constrained by the configuration schema. Canonical field
aliases follow the shared Bases reference/value adapters, not copied target metadata.

Chapter/paragraph totals derive from canonical chapter content; reader and print clones
are disposable views. One retained navigation sequence includes Home and supplies arrows,
breadcrumbs, sidebar and document contents; record scope leaves authored sections intact.

The system is a Python package managed and executed by `uv`.

## Flow

1. Load cross-project configuration, then the selected vault's optional project configuration,
   and resolve CLI runtime paths.
2. Resolve a source folder to its conventional manifest note, or accept an explicit note.
3. The core parses the selected manifest into a schema-valid JSON Document with document metadata, an ordered chapter tree, semantic Markdown nodes, links, and assets.
4. The core resolves every manifest link within the containing vault and validates frontmatter and supported input syntax.
5. Adapters project the Document into their output formats; HTML rendering remains in obs-html.
6. Resolve authorized derived-content providers, including command fences.
7. Resolve content links and assets within the vault boundary.
8. Render one self-contained HTML file with an embedded chapter navigator.

The manifest parser, vault resolver, Markdown parser, and renderer are separate ownership
boundaries.
Within one build, selected inputs are immutable: read each owning source once,
then reuse its decoded content and parsed representations through processing and
output. Keep these snapshots/indexes scoped to that invocation; a later build must
observe input edits.

Do not repeatedly reopen/reparse sources merely because several projections consume them.
Measure separate acquisition, parsing/validation, link
resolution, semantic projection, rendering, serialization/compression and packaging
costs rather than treating all conversion as one opaque phase.

## Core attachment metadata

The core already provides the neutral Document contract, vault and asset resolution,
capability-reference validation, adapter dispatch, and figure-descriptor validation.
Attachment metadata extraction extends that core boundary: it reads supported XML
metadata bytes without output-format or host dependencies and returns a display date.
It prefers a valid embedded exported or last-changed instant and otherwise uses the
caller-supplied modification instant. Unsupported input and invalid instants have no
date rather than a guessed value. Adapters decide where a resolved date appears.

## Document-adapter contract

The core-to-adapter vocabulary is the versioned JSON Document and its JSON Schema.
The Document carries the capability identifiers it uses and references the versioned
JSON capability reference for their definitions and dependencies. Its schema and the
adapter-manifest schema are the executable owners of the exchanged shape.

The boundary has no Python types, package entry points, application names, or
output-format terms. An implementation may change language without changing either
JSON contract.

## Input contracts

The core owns data-only input contracts for command fences, callouts, cards, editable
properties, and queries. Their JSON Schema definitions and parsing validation describe
source semantics only; execution and every presentation projection remain adapter
concerns.

Core configuration is restricted to source resolution and authorized command limits.
Report, browser, and style settings remain adapter configuration.

During the transition, `obs-html` retains its existing parsing and rendering code and
does not import the core package. The duplicated adapter validation remains the
compatibility owner until a later Document-rendering cutover removes it.

Document chapter content is a recursive node tree with `type`, `attrs`, `children`,
and optional `text`.

Its fixed structural types are `document`, `section`, `paragraph`, `text`, `list`,
`list-item`, and `code`. Every other type is a capability identifier.

The Document separately carries semantic resources so adapters can resolve their
identifiers without inferring them from presentation nodes.

An adapter is any executable that declares the capability identifiers it supports in a
JSON manifest. The declaration is data, not a runtime registration mechanism. The
[[capability-reference|capability reference]] owns the supported identifiers and their semantics; adapters use
that reference rather than duplicating capability definitions.

The core validates Document identifiers against a supplied capability reference and
requires an adapter to support each used capability's transitive dependencies before
starting its process.

The capability-reference generator reads those notes, rejects missing input-model
coverage and dependency identifiers, and writes the schema-validated JSON document.

Domain adapters own their evidence parsing, calculations, and report content;
obs-html owns reusable rendering and interaction behavior. In evidence-driven
pipelines, the generated Obsidian vault is a disposable intermediate
representation, not a parallel authoring source.

Regeneration must derive it from the original evidence exports and explicitly
authored adapter inputs. Framework
defects are fixed here, not worked around through hand-edited intermediate notes.

An adapter's migrated report must provide its required interactions within the
obs-html edition, not redirect readers to a legacy interactive report. Missing
reusable capabilities belong in this framework; original evidence links and
downloads remain distinct from legacy-application navigation.

The renderer emits the nested table of contents and ordered chapter data once;
client-side navigation shows exactly one chapter and manages previous/next controls, URL
fragments, browser history, scroll reset, and docked-bar state.

One embedded central stylesheet owns the component rules described in [[report-ui]].
The [[semantic-assets]] index owns named presentation values and their inheritance;
stylesheet variables and DOM are derived views of that owner.

Success, failure, waiting, and annotation colors are semantic tokens; components never own
parallel literals for those meanings.

Icons, colors and stateful appearances share that typed semantic resource owner,
resolved for generated markup and browser controls. Consumers reference names,
not glyph/graphic/color literals. Obsidian action compatibility belongs to
[[input-model#Named icon resources]]; resource semantics belong to [[semantic-assets]].

One embedded data-table runtime owns table filtering, hierarchical rows, rendered cells, and column
order.

The Markdown parser adapts each `base` fence into a declarative table definition attached to
its ordinary chapter; the runtime has no Appendix or named-register knowledge.

The Markdown table-authoring contract is owned by [[input-model]]. Domain adapters
project records; authored Markdown owns queries and composition. Application runtimes
update canonical data without replacing the authored table selection. Framework default
content follows the same contract instead of constructing hidden table definitions.

The report embeds
those definitions and their queries, not precomputed result rows.

The browser evaluates a definition
lazily against canonical report records when its containing chapter is opened.

Platform wrappers contain only bootstrap logic and dispatch to the same CLI.

Trusted application registration and revision-checked canonical/archive transactions
follow [[input-model]]. The generic report owns action dispatch and atomic replacement;
domain adapters own parsing, shared semantic projection and their generated source
changes.

Figures resolve declared canonical graph owners from live records, not a second startup
graph. Cover, authored source links and Settings use one current-archive
download action; activation resolves bytes from the existing payload owner.

Dockable bars are extension modules discovered from the `obs_html.bars` package. Each
module exports one definition containing its key, label, icon, help text, and content
factory. The renderer derives both menu entries and parked bar markup from those
definitions; it never keeps a second list. See [[quality]].

A bar's optional browser runtime is the sibling `<module>.js` package resource;
discovery attaches it, and a definition carrying script text is rejected.

Browser runtime code lives only in package `.js` resources read through
`importlib.resources`, never in Python string literals, so the JavaScript syntax check
covers every runtime file. Values reach a runtime through data islands or attributes;
the pre-paint reader startup substitutes JSON values for its placeholders.

Review comments and per-reviewer block decisions live in one embedded JSON island separate
from the canonical report data.

The Comments bar is the only browser-side owner of that
island.

Review-item identifiers are deterministic derived views of rendered chapter blocks,
not a parallel copy of source content.

Saving a reviewed copy rewrites the island in the
standalone HTML; it never changes source Markdown or canonical chapter data.

CLI extraction
reads only this island and never executes report scripts or parses comments from rendered
prose.

Command execution is owned by a separate runner boundary. Markdown parsing supplies the
command and receives escaped output; it does not own process invocation, timeout policy,
or authorization.

## Report data ownership

- The generated HTML embeds one canonical note store with identifiers, normalized frontmatter,
	and rendered content; its separate ordered TOC contains note identifiers, not copied records.
	Manifest and link resolution semantics are owned by [[input-model]].
- Repeated embedded data-URI payloads are stored once in the canonical report data and referenced
  by opaque local tokens. Browser views resolve those tokens before presentation, keeping reports
  self-contained and preserving standalone/PDF access.
- The single-payload rule also applies across reader attachments and an embedded reproduction
  archive. Do not embed the same original evidence once for downloads and again in a separate
  source payload. References or a reconstructed archive may share the owning bytes; compression
  must preserve exact original downloads, standalone opening and source reproduction.
- With source embedding, the ordinary compressed ZIP is the byte owner. Reader asset
  descriptors name a ZIP member, its media type and SHA-256; local Blob URLs are disposable
  browser projections, never serialized owners. The browser validates the ZIP entry and
  original-byte digest before exposing it, and printing awaits pending asset hydration.

  Canonical notes remain the authority for model edits and exports. Evidence replacement
  must atomically rewrite the owning ZIP entry and its descriptors, removing superseded
  unreferenced bytes; appending a second asset store or retaining stale originals is not
  a valid replacement operation. This transport alone does not implement evidence upload.
- The reader, table of contents, filters, database views, and future render modes derive
	their state from that store. They do not receive copied chapter datasets or maintain
	parallel metadata.
- Only the active chapter is materialized in the reader. Screen pagination moves its live
	nodes so table state and review interactions survive view changes; static PDF projections
	render from the canonical store rather than hidden chapter documents.
- New views consume the generic store contract and keep only view-local state.
- Derived indexes may be built in memory at runtime but are not serialized as duplicate
	report data.
- Canonical report data has one transport codec shared by generation, source-archive
  handling, read-only extraction and reviewed saving. The default gzip/base64
  transport compresses that semantic JSON, not only its original attachments.

  Decoding is a bootstrap boundary; views initialize from the decoded canonical
  store in their normal order. Decoded data and DOM are disposable in-memory
  projections, not extra serialized owners. Reviewed saving encodes the current
  model and does not retain an inflated copy or stale startup payload alongside it.
- Python owns one parsed semantic chapter model containing normalized frontmatter, optional
	bottom-line content, paragraph semantic tags, diagnostics, and authored Markdown. Rendered chapters,
	generated projections, query records, and lint output consume that model; browser code does
	not rediscover source semantics from HTML.

- Table cells displaying note metadata use Markdown rendered by the same Python semantic
  renderer as chapter content. Derived HTML remains attached to the canonical note, keyed
  by flattened field path; raw values remain authoritative for filtering and sorting.
  Glossary projections retain their owning note's additional fields and ordering metadata.

## Safety boundaries

Figure support uses data-only Markdown contracts and a reusable generic presentation/runtime.
Plot equations, SVG composition, and graph/diagram data remain report-owned calculations;
generic figure infrastructure owns validation, confined inputs, presentation, interaction,
and optional projection of canonical report records through the existing report filter.

Dynamic figures reference canonical record fields and never serialize a second copy of the
record collection. No domain-specific geometry, collision model, named imperfection or trace
semantics belong in the generator. Subplot structure and axis relationships are explicit,
not rediscovered from screenshots. Existing engineering model inputs remain canonical.

The concrete contracts and execution boundaries are owned by [[input-model]].

- Source files are read-only.
- The generated file remains at the configured output path.
- Temporary output is replaced atomically only after a successful build.
- Every output writer leaves an existing file untouched when its content is unchanged;
  rewriting identical bytes would trigger another on-access antivirus scan.
- Invalid configuration fails before generation begins.
- Manifest and content links may not escape the containing vault.
- Command fences execute only when the build grants explicit authorization.
- Generated HTML never refers to source-machine local files.
- Comment text is rendered with DOM text APIs and serialized with script-closing characters
	escaped. A returned report is untrusted input to the read-only extractor.

See [[product]], [[configuration]], and [[input-model]].
