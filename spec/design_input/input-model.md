# Input model

[[capability-reference|Capability reference]] owns the supported capability identifiers,
their dependencies, summaries, and authoring examples. This note owns the corresponding
input semantics.

HTML-style Markdown authoring comments (`<!-- ... -->`), including multiline comments,
are non-rendered source annotations. They contribute no visible prose, links, semantic
marks, table definitions, or paragraph diagnostics. Preserve the surrounding content and
source locations; comment-like text inside fenced or inline code remains literal code.

This applies to chapter bodies and the manifest abstract, not to review-comment data.

The source resolves to one manifest note inside an Obsidian-compatible vault. Source selection
is owned by [[cli]]; the core's runtime defaults by its configuration schema,
`src/obs/config.schema.json`.
[[manifest]] selects and orders that design vault.

## Manifest contract

- The manifest consists of optional document frontmatter, one nested bulleted TOC list of
  links, and optional abstract Markdown after that list. Numeric TOC markers and prose before
  the TOC are not permitted. Once the TOC ends, subsequent Markdown belongs to the abstract,
  including any lists in that content.
- A manifest that does not start with a bulleted list has no TOC (worker decision, 4 Nov 2026,
  for the one-pager): all its Markdown is the abstract and the artifact is Home alone, with no
  chapters and no previous/next steps. A leading numbered list is still a misplaced TOC and an
  error.
- Every list item is exactly one local Markdown link or Obsidian wikilink to a note.
- Top-level items are chapters; nested items are subchapters of their parent.
- The sequence in which items appear in the source is authoritative at every nesting depth.
- A chapter is a non-hidden line of the manifest's TOC list, and nothing else is; a line is
  hidden when Markdown does not show it, for example inside an Obsidian `%%` comment
  ([Obsidian comments](#chapter-content)), and the list continues at the depth of the next
  visible line. The table
  of contents and previous/next walk exactly the chapters, in manifest order (depth first,
  after Home), so they always match.

  A note reached only through a link is not a chapter, gets
  no previous/next, and stays reachable through its link.
- Duplicate, unresolved, external, and non-Markdown manifest links are errors.
- The manifest owns document metadata, authored navigation, and abstract prose. It is not
  additionally rendered as an ordinary chapter.

## Core and adapter namespaces

Decided by the user, 5 Nov 2026: obs makes no statement about an adapter; it treats an adapter
like any other outside specification.

Every key the core reads lives in the core's namespace
`obs`, and the core validates every key there: a Base's and a view's `obs.records`, a view's
`obs.members` ([[#Base files and members]]), a card's `obs.metricsFrom` and a metric's `obs.projection`
([[capabilities/cards-metrics#Fields]]), a note's `obs.document`
([[capabilities/profiles]]) and a chapter's `obs.bless` ([[#Bless requests]]).

An adapter's options live in its own namespace, `obs` followed
by its name in camelCase ([[#Adapter extensions]]); the core
neither reads nor validates it, and keeps it out of document metadata rows. A key the core
used to read in an adapter's namespace is an input error naming the note, the old key and the
new key; there is no compatibility layer.

### Adapter extensions

An adapter documents each trusted extension it adds in a note of its own specification's
`spec/capabilities/` folder, in the format of the core's capability notes: `kind: adapter-behavior`
and the same `capability` frontmatter, with the extension's contract in the note body. The core's
notes do not list adapter extensions.

The extension's namespace is the adapter's own option namespace, the camelCase form of the
adapter's name, followed by a dot and the extension's area, for example `obsExample.attachments`
for an adapter named `example`.

## Document home and abstract

A `cards` fence is a version-1 data-only mapping with a bounded `cards` list. Each card
has a title and Markdown body and may declare metrics.
A card may request `metricStyle: pills` to compact the same metrics without
changing their links, predicates, or current filtered values.

The optional `metricStyle: lines` presents metrics in aligned label/value columns
with ordinary typography and no pill outlines. Labels are plain text; links belong
to the displayed values. A compound value can reuse named query-backed quantities,
including a primary count followed by a parenthesized secondary count.

Declarative conditional value colors use the current authoritative numeric results,
not label matching, copied counts or executable expressions. Empty percentage
denominators remain neutral. Record any new bounded input fields and their schema
constraints here before implementation. Neither style
changes metric/query ownership.

Metrics select canonical artifact records with the same exact-equality/presence predicates
as Sankey projections. A metric
counts selected records or distinct values of a declared field; an optional denominator
selects the population for a percentage. Empty denominators display `-`. All selectors
compose with the artifact-wide filter, never table-local filters.

An optional metric `link` is an internal fragment using the existing chapter/heading
route syntax; the adapter adds the drill-down filter derived from the metric's conditions
([[capabilities/cards-metrics#Drill-downs]]) and applies it to the table named by a table-group
anchor, or to the target chapter's first table when the link has no group anchor.

Table-group anchors use the table's generated key and grouped property/value path.

No authored script, expressions, callbacks or domain classifications are accepted. A card
without metrics is static. Body Markdown uses the ordinary safe parser and
reference/asset resolution. A `base` fence in a card body is the same declarative table
definition as a chapter-level `base` fence and joins the chapter's canonical query/table
pipeline; it does not embed a second result set.

A metric with `from` may declare `secondary`, the canonical path of another
query-backed quantity. Its value uses the ordinary quantity-link renderer for
`primary (secondary)`.

Both links default to their ordinary quantity destination; the existing bounded
internal-fragment `link` can route the primary and optional
`secondaryLink` can route the secondary through existing chapter/table-filter
navigation. `secondaryLink` requires `secondary`; neither changes count ownership.

`toneRules` is a bounded first-match list (at most eight) of data-only mappings:
`value` is `primary`, `secondary` or `remaining` (denominator minus numerator);
`when` is `zero` or `positive`; `tone` is an existing semantic tone. An empty
denominator is always neutral. No matching rule leaves the authored/default tone.

Imported human-facing rich text retains recognizable paragraphs, lists, emphasis,
links and table structure, including supported entity-escaped HTML. Use the existing
safe content-rendering boundary; never enable arbitrary source HTML or execute
scripts, event attributes or unsafe URLs. Preserve the canonical imported value.

Do not blindly percent-decode ordinary text or reinterpret ambiguous plain values
as HTML. Unsupported or malformed content remains safely readable without silently
discarding its text; document concrete format limitations.
In particular, imported test steps are rendered mechanically from their raw
structured fields or recognizable markup, including real table rows and cells.

No LLM judgment or guessed reconstruction from flattened prose is involved.
Links opening external HTTP(S) web pages, including protocol-relative addresses,
use a new tab with `noopener noreferrer`,
consistently across authored prose, imported rich text, metadata and tables.

Document links to external things go through
[reference notes](#reference-notes-and-link-text); the only direct external link is the one
the adapter shows with the reference note. A direct external link in authored prose is a lint warning and still
follows the new-tab rule above until migrated.

Internal artifact navigation and explicit download/save actions retain their
existing same-artifact or download behavior.
An external canonical subject reference remains a real source link: its click is
not intercepted as a detail-tab command. The row expander and explicit subject
tabs retain detail selection through the existing table owner.

An explicit two-column Markdown block uses three standalone `|||` lines: opening,
column separator, and closing. The opening may specify relative positive integer
weights from 1 through 8, for example `||| 1:2`; weights on other delimiters are
errors. The unweighted form retains the existing equal-width presentation.

The two intervening nonempty Markdown blocks retain
ordinary semantics, including cards and canonical `base` queries. Delimiters inside
fenced code are literal. An incomplete or nested column block is an input error,
not silently discarded prose. This is artifact layout syntax, not source-authored HTML
or CSS; its presentation is the adapter's.

Delimiters are top-level block boundaries (optional surrounding whitespace, at most
three leading spaces), not inline text, list items or blockquotes. Each successive
group of three delimiters forms one block; both columns must contain a Markdown
block after authoring comments are removed.

Several complete blocks may follow one another. Four-space indented and fenced code
keep delimiter text literal.
No card or metric schema option is needed for this layout: ordinary card groups
inside either column use their existing data-only contract.

Relative non-Markdown file links reference a vault-local source file. Resolve them and
reject missing files and vault escapes. By default the file is not embedded: the link
becomes provenance text, its label followed by the vault-relative path, with no broken
local hyperlink and no absolute machine path.

Input evidence can be far larger than the artifact, so embedding is decided twice
(user, 4 Nov 2026):

- Per link, with Obsidian's own syntax: `[[file.xlsx]]` and `[label](file.xlsx)` only link;
  `![[file.xlsx]]` and `![label](file.xlsx)` mark the file for embedding.
- Per build, with the CLI flag `--embed-attachments`: only then are marked files embedded as
  downloads, preserving the filename. Without the flag, a marked file renders like a link.

Unmarked links are never embedded. There is no manifest setting for this.

A wikilink target with a file extension other than `.md` is a vault file; a `.base` file, which
names a register, is one too. It resolves like a note name: next to the linking note, then from
the vault root, then by its case-insensitive file name, which must match exactly one non-hidden
vault file.

A bare name that matches several fails the build naming the linking note and the
candidates, as does an embedded `.base` name that matches none; the remedy is the vault path. A marked image
(`![[figure.png]]`, `![label](figure.png)`) is document content as above, not an attachment.

PDF uses its media type (and `artifact.embedPdfs: false` still links PDFs locally instead) and other
binary/source
files use octet-stream, never an executable HTML/script media type. This keeps supplied
evidence out of authored data URLs. Images are document content, not linked sources, and
are always embedded.

A remote image, one whose Markdown image target is an `http` or `https` URL in chapter text
or in a manifest field such as `subtitle`, is embedded too: the core fetches it once per
build and it becomes a Document asset with its bytes and media type, referenced by its node
like a local image, so the artifact shows it without the network (decided 5 Nov 2026).

A remote image the build cannot fetch is a warning that names the note, the field, the URL
and the remedy (save the image into the vault and embed it locally); its node keeps the
alt text and the URL, so an adapter shows a labelled placeholder.

Sankey links may represent individual canonical records rather than aggregated pairs.

An optional `series` identity associates adjacent segments, and `originColor` preserves a
second categorical meaning without changing their value. Node `records` predicates and
an optional `unique` field derive filtered record/distinct-value labels from canonical
records; they never execute artifact-owned algorithms in the converter.

- An autogenerated Home precedes all chapters. A missing `title` uses the manifest filename
  without its Markdown extension. A nonempty string supplies the plain-text visible title.

  An explicitly empty string suppresses only that visible heading; it does not remove the
  cover, subtitle, metadata, Home, or abstract. Browser, navigation, and canonical Home
  identity use the document identity from available document metadata before falling
  back to the filename. A technical manifest filename is not the document's display
  identity when a project/document name is supplied.

  Whitespace-only strings and non-string titles remain invalid.
  When such an authored cover is also present as an ordinary source note (for
  example, in a reproduction folder), its empty `title` property stays empty for
  Bases comparisons. Its canonical navigation label uses the filename; display
  fallback does not overwrite the authored property.
- The optional nonempty `subtitle` string is inline Markdown, including linked notes and images.
  It appears below the title, not in the abstract. The title remains plain text.
- Home tables exist only at authored `base` fences in the manifest abstract.
  The maintained manifest declares a Key / Value table over manifest metadata and
  generation fields.

  Generation fields are plain rows with no generated-origin markers:
  exactly `timestamp`, `generator`, and `target` (no `generation.` prefix, no
  `(generated)` suffix, and no separate generator-version row duplicating `generator`).
  `timestamp` is the time of the last change to the document's content.

  It starts as the build time; a rebuild whose content equals the existing output keeps
  that output and its timestamp. Each committed canonical change in the artifact (for example
  an evidence replacement or a description edit) sets it to the time of that change, and a saved
  artifact keeps that time.

  A change that returns the content to its state when opened or
  when last saved restores that state's timestamp, so reverting an edit is not a change.

  The adapter owns which edits are content changes.
  Structured values are human text, never JSON: one `key: value` pair per line with the
  values aligned in one column, for example:

  ```text
  name:    <adapter>
  version: v0.3-2-g1a2b3c4
  commit:  1a2b3c4
  ```

  Git commits are shown as the short hash (`git rev-parse --short HEAD`).

  Generation metadata does not expose local absolute paths or overwrite authored metadata.
  The manifest's `canonicalNotes` dependency catalog remains in canonical source
  metadata but is not a document-metadata table row.

  Structured values retain their complete content rather than being silently omitted.
- Home retains authored abstract order, including History and Metadata
  declarations. Removing or moving a fence removes or moves its view, including on Home;
  no renderer supplies missing tables or sections. Which front pages exist, their order,
  titles and rendering are the adapter's presentation options.

  The abstract is the manifest Markdown following the TOC.
- Home has a stable navigation identity and participates in previous/next navigation
  before authored chapters. Home is the home-icon root of the breadcrumb path; generated pages
  do not recursively enter the authored-chapter summary query.
  Home itself is not a Contents chapter entry; the Home button and previous/next
  sequence still reach it.

### Profiles

Direction decided by the user, 4 Nov 2026; details pending (`spec/backlog/profiles.md`).
A profile is a named way to present the same vault: which content it includes and how it
presents it. Default profiles:

- **Document**: shows everything.
- **One-pager**: reduces as much as possible and shows only content tagged for the one-pager.
- **Slides**: lists the slideshows; the reader picks one, and the content tagged for that
  slideshow is shown.

A manifest or vault can define further profiles. The presentation keys an adapter reads are
today's single, implicit profile. First one-pager pieces (4 Nov 2026): a manifest without a TOC
(Home alone) and an adapter's compact heading.

### Registers

Decided by the user, 4 Nov 2026 (`spec/backlog/review-macro-syntax.md`). Generated registers
are Obsidian Bases views in `.base` files of the vault ([[#Base files and members]] owns the embed),
embedded where they appear: glossary, references, numeric values, mark registers such as
open points and document metadata.

The spec vault's `registers.base` is the starter.

```markdown
<!-- open-points.md, listed in the manifest TOC like any chapter -->
Optional authored introduction.

![[registers.base#Open points]]
```

- A vault may keep all its registers as views of one `.base` file, so they are easy to find.
  `![[file.base#View]]` embeds one view; `![[file.base]]` embeds all views with a selector.
- Registers are a superset of Bases. Each view is valid Bases YAML that Obsidian renders as a
  plain table of notes. Keys under `obs:` and an adapter's namespace, which Obsidian ignores, make an
  adapter render the rich register, for example one row per marked paragraph instead of one per note.
- The view's own filter is the fallback and must select something sensible in Obsidian: notes
  with the mark tag, notes with `kind: glossary`, notes with a `url`, numeric-value notes.
- Filters, columns, titles and grouping are authored in the view. No adapter owns default
  columns or filters for registers; the spec vault's `.base` file is the documented starter.
- Rows that are not notes (marked paragraphs, glossary terms, chapters with a callout,
  document metadata) come from the shared record projections, selected by the view's
  `obs.records`; a base-level `obs.records` is the default for all its views.
  There is no second dataset.
- Open: the supported filter grammar has no `file.hasTag`, so a marks view filters its rows by
  `type` and its Obsidian fallback cannot yet select the notes carrying the mark tag.
- Performance: a `.base` file is parsed once per build and shared by all its embeds. Each view
  runs the same query an authored fence runs on the shared projections, so registers cost no
  more than the removed macros.
- A register chapter is an ordinary note: the manifest TOC owns whether, where and under which
  parent it appears. Removing it from the TOC removes the chapter.
- A document has one appendix. Its hand-written sections come first, then its register
  sections. Readers are not told which sections are generated.
- Rendering an adapter's keys inside Obsidian itself (a plugin) is a possible later step, not
  planned.

## Cover metadata and history

The manifest optionally supplies nonempty plain-text `document type`, `organization`, `template`,
`document number`, `copyright`, `confidentiality`, and `legal entity` fields.

The field names name no application or vendor. The removed `sap number` is an input error
naming the manifest, the old field and `document number`; there is no compatibility layer.

Optional `product` is a mapping containing
`name` and optionally `version`, both nonempty strings.

Optional `authors`, `reviewers`, and
`approvers` accept a nonempty string or list of nonempty strings.

Empty strings, nulls and empty lists/mappings are treated as unassigned and omitted.

Empty product
members are omitted as well.

They are not proof of approval or legal status.

How an adapter presents the cover and History is that adapter's; its specification is listed in
[[appendix/references|References]].

The core validates these fields and `history` against its `coverMetadata` schema
(`src/obs/cover-metadata.schema.json`) once unassigned values are omitted; a failure is an input
error naming the manifest, the field path and the remedy.

Unknown fields inside `product` and a `history` entry are input errors. The manifest's other
frontmatter (title, subtitle, `obs`, an adapter's namespace and any further field) is not cover
metadata: other contracts own it.

A further field stays a residual metadata row, open to queries (worker decision, 6 Nov 2026).

Optional manifest `history` is an ordered list, oldest first, of mappings with required nonempty
strings `version`, `author`, and `change`, and optional ISO `date` (YYYY-MM-DD), omitted when empty.

Quote revision
labels such as `"00"` so YAML preserves them.

A version ending in `*` denotes the working version
and may occur only in the last entry.

Dates are authored, not inferred; an undated entry has an
empty date cell.

No Git comparisons, tag lookup, version bumps or release inference occur.

Unknown history fields, duplicate version labels, malformed dates and misplaced working versions
are input errors.

History can be absent or empty, without placeholders.

The core emits each history entry as a `documentHistory` record with `version`, `date`, `author`
and `change`; a Base selects them with `obs.records: documentHistory`.

History is not repeated as raw JSON in metadata.

Generation time remains separate from document revision dates.

## Chapter content

- Obsidian comments are removed from every note body, the manifest's included, before anything
  reads it, so comment text never renders and a commented manifest line is no chapter. A `%%`
  outside code opens a comment and the next `%%` closes it, on the same line (inline) or a
  later one (a block, usually `%%` on its own line); a `%%` in a fenced code block or a code
  span is text.

  A line that held only comment text goes with it. A `%%` no `%%` closes is an
  error naming the note and the line it opens on, as an unclosed frontmatter is (worker
  decision, 5 Nov 2026; Obsidian hides the rest of the note instead).
- Every part of the core reads a note through one reader, `src/obs/note.py`, which also owns
  the one Markdown parser: producers, inclusion and conversion see the same body, so nothing
  in a comment runs or renders. The reader keeps each body line's source line, so every error
  that names a line names the line in the source file, frontmatter and removed comments
  counted.
- The manifest is the inclusion root.

  Its TOC targets, abstract and metadata links seed inclusion;
  links and table-query matches from included notes add their source notes recursively until
  no new notes are reached.

  Queries may inspect the vault's Markdown metadata index, but only
  matched/referenced notes enter the canonical artifact store.

  Unreferenced notes stay out, and only included notes are validated: a note's frontmatter
  contracts (a quantity, a note profile, a query) and its fences fail the build only when
  the Document includes the note (decided 5 Nov 2026). Reading the vault's metadata
  index still requires every note's frontmatter to parse as a YAML mapping.

  A contract failure names where it comes from and its remedy, in one form:
  `<note path>: <field path>: <what is wrong>. <remedy>`.

  The field path is the frontmatter
  field (`obs.document`, `query.where[0].field`), or the fence, numbered by kind within
  the note, followed by the field inside it (`cards fence 1, cards[0].title`); a file's own
  top level is `top level`. The remedy says what to write and names the note that owns the
  contract.

  One formatter in the core turns every schema validation failure, of
  frontmatter, fences, `.base` files and project configuration, into this message, so no
  JSON Schema library text reaches the person (the
  person's rule that every error names its origin and, where possible, a remedy; decided
  5 Nov 2026).

  Links are wikilinks and embeds in body text (not in code) and in frontmatter string
  values. A `base` fence (also inside a `cards` body) or an embedded `.base` file selects
  the notes whose record matches its `filters` and any view's `filters`.

  A frontmatter `query`, and a cards metric, selects the notes whose record has every
  `where` condition ([[capabilities/queries#Conditions]]), narrowed by its `from` owner's
  selection; the `from` and `secondary` owner notes
  are included too.

  A metric's `denominator` selects its population the same way, and a
  card's `obs.metricsFrom.where` the records its series counts. A card's
  `obs.metricsFrom.sourceNote` and `obs.metricsFrom.link.note`
  ([[capabilities/cards-metrics#Fields]]) are explicit references, included like links.
  Each note is included once, so cycles end.

  No automatic selection selects an ignored note
  ([[capabilities/markdown-frontmatter#Ignored notes]]), the manifest included when it marks
  itself ignored. Following the person's underscore analogy (not yet confirmed in detail), an
  explicit reference still reaches it: an ignored note in the manifest's TOC, or linked or
  embedded from an included note, is included and resolves normally.

  The Document's `chapters` hold the TOC tree first. Every other included note follows as
  a top-level chapter with `toc: false`, in the case-insensitive order of its vault path
  (worker decision, 5 Nov 2026), so the place does not depend on which link reached it
  first.

  Dot-prefixed directories/files are excluded.

  TOC membership is a separate ordered reference
  list.

  The manifest resolves to generated Home.

  Paths escaping the vault are errors.
- Queries run over this included store at runtime. An online query edit cannot import a note
  omitted at generation; generation resolves the authored queries to establish inclusion.
- Each source path has one stable note identity and one stored record, even with repeated links,
  aliases, cycles, or multiple table projections. Links stay references, not recursive copies.
- Optional note frontmatter `obs: {document: false}` declares a canonical record-only
  projection. `document` is boolean and defaults to true; the core's `obs` mapping is constrained
  by its `note-profile.schema.json`.

  Record-only notes remain queryable and available to figures and explicit canonical
  reference/detail tabs, but do not appear in generic Search, chapter activation or
  standalone technical note details. A link to one behaves like a link to a reference note
  ([[#Reference notes and link text]], decided 29 Oct 2026).

  A record-only manifest or authored TOC target is an input error, not a silently dropped
  chapter. Direct browser
  artifact fragments targeting a record-only note return to Home. Ordinary source attachment
  links and explicitly declared subject tabs retain their behavior. Producers opt into this
  distinction through data, never inferred note kinds or generator-specific filenames.

  An unlisted note is not a chapter; see the
  [[#Manifest contract|chapter sequence]].
- Standard Markdown is supported before optional Obsidian extensions.
- `[[wikilinks]]` resolve by source-relative path, vault-relative path, unique note name, and
  then alias. Relative Markdown note links use the same canonical targets. Nested note links
  and note-heading fragments are resolvable; ambiguous note references fail generation
  explicitly. Link examples inside code remain literal.

  A link's `attrs.chapter` names the chapter of its target; a link to the manifest names
  `home`, which no chapter identifier takes. Name lookup skips the manifest.

  `null` follows
  [[capabilities/wikilinks#Document node]]. For a target that does not exist the build warns,
  naming the source note, the target and the remedy (decided 5 Nov 2026), and for a link in a
  frontmatter value also its field, by the dotted path its field node names.
- Obsidian `aliases` frontmatter supplies alternative names for the same note.

  It accepts a
  nonempty string or a list of nonempty strings.

  Alias lookup is case-insensitive, follows
  exact-path and unique-note-name resolution, and resolves against all indexed source notes.

  Ambiguous aliases report an error rather than choosing a note arbitrarily.

  Explicit wikilink display labels remain authoritative.

  A build indexes aliases from the current selected note snapshot once and reuses
  that index for link resolution. Path and unique-name precedence, case-insensitive
  matching, and explicit ambiguity failures remain unchanged; indexes are scoped
  to one build and must not hide edits to inputs. Repeated case-insensitive aliases
  on one note identify that one note, not an ambiguous pair.
- Aliases identify notes and their canonical semantic records, not alternate frontmatter keys.
  A glossary concept has one definition even when several aliases reference it.

### Callouts

Decided by the user, 4 Nov 2026; implementation pending (`spec/backlog/callout-marks.md`):
callouts are the one system for marked content.

- Mark kinds (open point, risk, assumption, issue, decision, warning, question, idea) become
  callout types: `> [!open-point] Label`. The callout's content is the marked item; a callout
  nested under a list item marks that item. `#mark/...` tags are removed.
- Each type declares its presentation, which the adapter owns; nothing is inferred from content. In Markdown a callout is always a block.
- Registers, cards, an adapter's previews and profiles select callouts by type from the shared record
  projections. In Obsidian, Bases views of them fall back to note lists.

Obsidian is the reference syntax. A blockquote is a callout when the first line of its
first paragraph is `[!type]`, optionally followed directly by a fold marker `+` or `-`
and then by a space and an inline-Markdown title: `> [!warning]- Check the limits`.

The type is case-insensitive. Later lines of the blockquote, including nested blocks and
callouts, are the callout body. Presentation is the adapter's.

| Type | Obsidian aliases |
|---|---|
| `note` | |
| `abstract` | `summary`, `tldr` |
| `info` | |
| `todo` | |
| `tip` | `hint` |
| `success` | `check`, `done` |
| `question` | `help`, `faq` |
| `warning` | `caution`, `attention` |
| `failure` | `fail`, `missing` |
| `danger` | `error` |
| `bug` | |
| `example` | |
| `quote` | `cite` |
| `important` | |

- Without an authored title, the title is the authored type keyword with its first letter
  capitalized, as in Obsidian (`[!faq]` shows "Faq"). An authored title replaces it.
- `important` is its own type: an emphasis of key takeaways, not Obsidian's alias of `tip`. An authored title is still shown.
- Fold markers are accepted for Obsidian compatibility; the callout always renders
  expanded, so screen, search and PDF show its whole body. Interactive folding is not
  supported.
- Other types, a marker that is not on the first line, or text after `]` without a
  separating space are not callouts; the blockquote renders as an ordinary quotation that
  keeps its literal `[!...]` text visible rather than approximating an unknown type.
- Callout markers inside code remain literal code.

### Reusable query ownership

A selection query has one owning definition. Filters, calculated counts and
drill-down actions reference the query stored by its owning element rather than
maintaining equivalent predicate copies.

A name is a stable reference to that definition, not another query
implementation. Resolve references through the
existing canonical element/query machinery, using the same evaluator and current
filter/revision context for every consumer.

Queries compose over result sets: the active global filter selects items, a
referenced selection query narrows that result, and another selection or
count/distinct-count consumes the result without restarting from raw items.
For example, one Findings selection feeds both its total count and an Unexplained
subset selection/count.

Preserve item identity through the chain. Resolve and reuse each stage under the
same canonical/filter revision; upstream changes
invalidate dependent stages, while an unrelated detail-tab switch does not.
Only the aggregate's final result is a number; reusable selection stages remain
item sets.

User-entered queries may likewise have names; naming does not change their
meaning. Preserve valid applied definitions through the existing reader-state
save/reopen path. An invalid draft must not replace the last valid applied query.

Unresolved, ambiguous or cyclic references are explicit errors, never an
unfiltered result. Do not add a separate expression language or query-management
application to implement this ownership rule. Record the precise reference
syntax with its owning input contract before adding a new reference form.

A count query may add `from: <canonical-note-path-without-.md>` to consume the
item selection owned by that note's `query`; its own `where` narrows that set.
Only the final count or `distinct` aggregation produces a number.

Owners resolve by exact vault-relative canonical identity, rejecting
missing/non-query owners,
invalid paths and cycles. Card counts (including percentage denominators) and
quantity references consume the same selection/cache owner. A quantity query can
feed a downstream selection without replacing its item set with its display count.

### Numeric-value notes

An engineering quantity has one canonical Markdown note with `kind: quantity`, a finite
numeric `value`, its authored display `unit` when dimensional, and a short, descriptive
variable-style Obsidian alias. Distinct meanings remain distinct notes even when their
numbers are equal.

Source citations, drawing locations, assumptions and derivation
discussion belong to that note; frontmatter `source` links identify the supporting sources.
The note body explains qualifications and uncertainty without changing their strength.

Authors reference an unlabelled `[[alias]]` rather than copying the number or its unit
into prose. An adapter renders that link as the canonical value followed by its unit, retaining
normal note navigation, previews and details. Explicit display labels and ordinary
non-quantity links keep their existing behavior.

The alias is the author's stable variable name: changing the owning value or display unit
updates every implicit reference. Do not repeat the quantity's citation or derivation beside
each use merely to establish its provenance; readers follow the value link to its owner.

Values are data, never executable formulas.
Invalid quantity metadata fails validation rather than producing an empty or misleading label.

For a query-derived count, a quantity note may declare `query: {where, from?, distinct?}`
instead of `value`. `where` and optional `distinct` use the existing record-metric
conditions and distinct-count semantics; exactly one of `value` or `query` is
present. This is a data-only count definition, not an expression language.

Ordinary unlabelled quantity references render the calculated number inside
authored text, retaining the same note identity and navigation. The shared
record-query aggregate owner evaluates it against the current globally filtered
canonical population and refreshes references after filtering or canonical edits.

An empty matching set displays zero. Static quantities and explicit link labels
keep their existing behavior.

Use the same aggregate implementation for card counts and referenced counts,
not artifact-specific counters or a second canonical dataset. Calculated display
values are derived view state, not authored values, review edits or dirty-state
changes. Print, previews and reviewed-copy reopening resolve them from the
current query/filter state.

Merely switching an unrelated detail tab must not recompute every aggregate.
Implicit query references carry only `data-quantity-reference` naming the owning
canonical source path, not a copied query, count or canonical dataset. Materialized
references, previews and print clones reuse cached values until canonical/filter
changes invalidate them.

The note owns its display unit; every implicit reference uses that same unit. Use micrometres
for comparable flatness and small tolerance quantities, with exact conversion from
millimetres and no change to physical meaning. Other dimensions keep appropriate consistent
units. Do not merge unrelated quantities merely to normalize units.

A side-by-side migration of an existing artifact applies this ownership across its prose,
tables, callouts and captions. Preserve relations, ranges, signs, datums and engineering
qualifications; move value-specific provenance and discussion to the corresponding note.

Identifiers (drawing, reference, chapter, figure, open-point and model names), dates,
enumeration and algebraic constants are not engineering-quantity references. Static figure
pixels, source drawings, archived historical drafts and executable model inputs are not
rewritten or recalculated.

Existing model inputs remain authoritative for model-owned
quantities; derive their artifact notes from those inputs instead of hand-copying new defaults.

#### Numeric direction (decided 29 Oct 2026, not yet implemented)

Which numbers become notes is an author's judgment. A number with a meaning (an upper limit,
a requirement, a measured property) becomes a numeric-value note. A number that is obvious from
structure ("three points" above a three-item list) or that goes stale (one test run's duration)
is not written at all.

Range, tolerance and vector are numeric types, not separate concepts. Their parts are typed
frontmatter fields of the one note, and the unlabelled link renders all of them.

A derived value records its provenance in one of three ways: prose in the note, a stored
command that reproduces it, or a stored query over the document's own records.

Everything a query computes runs live in the artifact, so a reader's change updates it at once.
Values from external systems or heavy analysis are computed offline and stay plain data.
There is no hard border: analytic equations with numbers plugged in should run live, and
work that is too heavy for the browser runs offline.

Quantities carry a unit system. A quantity's `unit` is a physical unit: an SI or common
engineering unit, with prefixes and as products or quotients, which the core parses with one
pinned unit library. A quantity may carry a `range`, its domain, which holds its value.

In the Document every quantity carries its value, its display unit, its value in SI base units
and its dimension, so an adapter converts between units without a unit library of its own.

Values of one dimension convert between units and add or subtract across units; combining
different dimensions is an input error naming both notes. [[capabilities/quantities]] owns the
fields, the Document node and the arithmetic. Tolerance stack-up is a candidate to move live.

### Reference notes and link text

Decided 29 Oct 2026, implemented 4 Nov 2026 (`spec/backlog/reference-items.md`).

A note with a `url` field is the reference to that external thing, whatever its kind. It may
also hold internal content: a `description`, details and records. Each external thing has
exactly one such note, however often it is linked.

Every document link to something external targets that note, never the URL. Systems of record
are not exempt: a system of record and its items link to their internal record notes.

- A click goes to the note. A note with a place in the table of contents navigates as usual. A
  note without one opens where the adapter shows a note without a place, and the page stays put.
- A preview, where the adapter has one, shows the note's `description` and its external link.
- A bare URL in authored prose, and a table `linkProperty` to an external URL, are lint
  warnings.
- The references register is a query over notes with a `url`, not a maintained list.

Link text: the text written in the link wins. An unlabelled link renders by the target's kind:
a numeric-value note shows its value and unit (and range or tolerance once typed), and any other
note shows its title. There is no placeholder syntax such as `$value` in link text.

"Unlabelled" means a wikilink without `|label`: `[[alias]]` and `[[note-name]]` show the
target's title, not the alias or file name written; a Markdown link always has its own text.
An unlabelled heading or block link shows the note's title and the heading
([[capabilities/wikilinks#Link text]]).

The lint runs with the paragraph warnings on every build (stderr, never in the artifact): a
Markdown link, autolink or bare `http(s)` URL in a note body (code excluded), and a base
`linkProperty` whose path, or its last segment, holds an external URL (plain or as a Markdown
link) in any included note.

### Remaining chapter content

#### Figure input direction

Ordinary plots are authored as Markdown fences containing equations and plot details, not
custom generator code per artifact.

An artifact's complex geometry figures may remain
artifact-owned Python scripts
that provide figure data and subplot composition to generic infrastructure. Artifact-specific
equations, geometry and engineering logic stay outside the converter.

Every figure is one generic figure of a kind. A `figure` fence contains a YAML mapping with
`version: 1`, a `kind`, the attributes every kind shares (`caption` and `alt`, below) and the
kind's content: inline under `content`, or from `source`, a vault-relative file.

Exactly one of the two; a fence with neither or both is an input error that names the note, the fence and the
remedy. A kind's own options sit beside them in the fence. The kinds and their content:

- `image`: a raster image or an SVG image. `source` names the image file; inline `content` is
  SVG markup.
- `svg`: an exact SVG drawing, with optional `panels` for viewport inspection (below). `source`
  names the `.svg` file; inline `content` is SVG markup.
- `sankey`: the Sankey graph (below), with its option `countLabels`. `source` names the graph's
  JSON file; inline `content` is the same mapping.
- `plot`: a stored-data plot, a FigureDescriptor (below). `source` names the descriptor's JSON
  file; inline `content` is the same mapping.
- `mermaid` and `plantuml`: a diagram in that language ([[capabilities/mermaid]],
  [[capabilities/plantuml]]). `source` names its `.mmd` or `.puml` file; inline `content` is
  the diagram's text. A plain ```` ```mermaid ```` or ```` ```plantuml ```` fence, as Obsidian
  shows it, is a figure of that kind without caption, alt or block id, and its whole text is the
  content.
- `equations`: symbolic equations, their variables and an initial plot ([[#Equation figures]]).
  `source` names a YAML or JSON file; inline `content` is the same mapping.
- `pugh`: a Pugh decision matrix ([[#Pugh decision figures]]). `source` names a YAML or JSON
  file; inline `content` is the same mapping. A plain ```` ```pugh ```` fence is a figure of that
  kind without caption, alt or block id.

An optional `caption` supplies visible figure prose; omission renders no caption or placeholder.

The core emits every figure as one `figures` Document node, whatever its kind. Its attrs hold
what every kind shares: `kind`, `caption` (paragraph nodes, parsed like note content), `alt` and
`block` (the block id, below). Its one child holds the kind's content and is typed by the kind;
inline and external content give the same node, and no kind repeats a shared attribute.

A figure's number is not in the node: numbering is an adapter's presentation decision (below).
The kinds are one registry, `FIGURE_KINDS` in `src/obs/figure.py`: adding a kind is one entry
there (its parser) and one body schema in `src/obs/document.schema.json` (`$defs/figureBodies`).

A diagram becomes SVG when the core builds the Document, on the build machine and with no
network: the core runs the diagram's library (Mermaid, or PlantUML's JavaScript build) in a
local headless browser and refuses every request the library makes.

That browser is Playwright's headless shell, the one the adapter's browser tests use, where the
installed Playwright starts it, else an installed Chrome, Edge or Chromium: the shell draws the
same SVG for less CPU (`_launch` in `src/obs/diagram.py` names what was measured).

The libraries are pinned in `src/obs/diagrams/package-lock.json`. Every build
of the core's package unpacks the files it serves from the tarballs the lockfile pins (only
those packages' own, checked against the lockfile's integrity) and ships them as package data,
which the core reads only through `importlib.resources` (`hatch_build.py`).

A package build
without npm, whose `npm pack` fails or whose tarball is not the pinned one, fails naming the
lockfile and the remedy. Building a Document never fetches them.

The
figure's body holds the diagram's text as authored, for review, and the SVG, which every
adapter shows as the figure's picture, so none needs a diagram library and print shows the
same drawing. The same text gives the same SVG, whether inline or from a file.

A diagram its
library cannot read is an input error that names the note, the note's line the library names
(for a `source` file: the fence's line and the file's line) and the library's own message; a
build without a browser, a program the package cannot carry, is an input error that names the
note, the fence's line and the browser's install command. No diagram is ever an empty figure.

Paths are relative to the note, confined to the vault, and files are read-only
inputs. Rendering/checking never runs
producers.

Existing explicit command authorization remains unchanged. Authored SVG is
never executable: an output that shows a figure's SVG inline, so its links can be followed,
shows no script, event handler or other executable content of it. A link inside a figure's SVG
is a link like one in prose ([[capabilities/wikilinks#Links inside a figure]]).

At the core boundary, a generated figure is a versioned JSON FigureDescriptor. It
carries neutral data, an ordered panel list, and provenance; it does not carry rendered
markup, stylesheet values, or a browser payload.

Each panel has viewport bounds and grid placement. Its axes declare their scale, numeric
limits, and labels. Provenance records the producer command as ordered strings and may
record stable fingerprints for its input files. The descriptor schema is the
executable owner of this shape; adapters choose their own rendering from it.

#### Figure descriptor

The FigureDescriptor has `schemaVersion: 1`, a stable `id`, a `data` payload, one or more
panels, and provenance.

The `data` payload holds exactly one shape, and nothing else:

- `traces`: 1 to 64 series, each drawn on a panel. A series has numeric `x` and `y` lists, an
  optional `label` (shown in the legend), `panel` (a panel id; the first panel without it),
  `mode` (`lines`, the default, `markers` or `lines+markers`) and six-digit hex `color`. Its x
  and y lists have equal, nonzero length, and its panel has an x and a y axis.
- `sankey`: a Sankey graph, the same graph a `sankey` figure carries (see the Figure input
  direction), with an optional `countLabels` beside it.

`src/obs/figure.schema.json` owns both shapes; the rules a schema cannot state (equal lengths,
existing panels and nodes, advancing stages) are an adapter's check of what it draws, except that
the core refuses a Sankey link to a node its graph does not have (the Figure input direction).

A panel has a stable `id`, numeric
`bounds` (`x`, `y`, positive `width`, and positive `height`), and a non-negative
`grid` row/column with positive spans.

It has one or more axes. Every axis has a stable `id`, `linear` or `log` scale, numeric
`minimum` and `maximum` limits, and a text label. Provenance has a nonempty ordered
command array and can list input file IDs with stable fingerprints.

A `figure` fence may also use `kind: image`, with `source` naming a vault-local
raster image or SVG and optional `alt` providing image alternative text, not a
second visible caption.

Without `alt`, alternative text and accessible names use the plain text of the rendered caption (link labels such as `Figure 4.2`, no Markdown or wikilink
syntax). When supplied, all figure kinds share one explicit `caption` owner:
a nonempty inline Markdown string, or a nonempty array of inline Markdown
paragraphs for an authored multi-paragraph caption.

Links resolve as ordinary note content. Array entries retain independent document-order review paragraph
identities when migrating existing caption prose inside the figure; a string
remains part of the figure review unit. Caption membership is never inferred
from adjacent italics. Ordinary Markdown images remain valid without captions.

A figure's identity is an ordinary Obsidian block id: a `^name` line directly after the
closing fence (a blank line in between is allowed). The converter removes that line from the
visible text and gives the figure the anchor `<note-slug>--block-<name>`.

References use Obsidian block-link syntax, so they also navigate in Obsidian: `[[#^name]]`
within a note,
`[[note#^name]]` across notes, or the Markdown form `[label](note.md#^name)`. An unlabelled
reference (`[[#^name]]`, `[](note.md#^name)`) displays the referenced figure's current number,
for example `Figure 2.4`; it is a build error unless that figure is numbered.

A labelled reference keeps its label. Unresolved block references and duplicate block ids in
one note
are build errors. Numbering itself is an adapter's presentation decision.

#### Figure captions and references

Decided by the user, 4 Nov 2026 (`spec/backlog/review-figure-defaults.md`):

- Every figure has a caption inside the figure. A `figure` fence without `caption` is a lint
  warning. An image alone in its paragraph is a figure too; the warning suggests a
  `figure` fence with `kind: image` and a caption.
- Captions outside the figure go. A paragraph directly before or after a figure that acts as
  its caption (italic-only text, or text starting with the figure label and a number) is a
  lint warning: move its text into `caption` and delete the paragraph.
- Authors never type figure numbers; they do not know them. A reference is an Obsidian block
  link that Obsidian offers for selection (`[[#^` or `[[note#^`), so every figure carries a
  block id, preferably a descriptive one.
- Prose that names a figure by label and number (`Figure 3`, `Abb. 2.1`) is a lint warning
  that suggests the block link of the figure it most likely means.
- Adjacent unlabelled references merge into one plural reference: `[[#^a]] and [[#^b]]`
  renders `Figures 2.4 and 2.5`, and a run of three or more consecutive numbers renders
  `Figures 2.4–2.6`. Adjacent means separated only by whitespace, a comma or a conjunction
  from the packaged list; the adapter's figure options name the plural.

Implementation decisions, same date:

- The figure lint shares the paragraph-warning path: every build and `--check` print one
  source-located stderr warning per finding; none changes the artifact. An image alone in its
  paragraph gets only the image warning, not the caption or block-id one.
- Typed numbers are recognised after the manifest's `label` and `labelPlural` and after the
  packaged label list (`input.figureReferences.labels` in `cfg.json`), followed by a number
  such as `3` or `2.1`. Code spans and fence content other than captions are not prose.
- The suggested link is the figure that currently carries that number, otherwise the note's
  figure at the position given by the number's last component; a figure without a block id
  is suggested together with adding one.
- The conjunction list is `input.figureReferences.conjunctions` in `cfg.json`. Only
  unlabelled references to numbered figures merge; a labelled one ends the group. The
  author's order and separators stay: the plural label replaces the singular once, and each
  number keeps its link. A run of three or more numbers in the same chapter that increase by
  one renders as first–last, linking both ends.

Core and adapter, 6 Nov 2026:

- The core resolves a block link, written as a wikilink (`[[#^name]]`, `[[note#^name]]`) or in
  the Markdown form (`[](note.md#^name)`, `[label](note.md#^name)`), to the figure that carries
  the block id, as [[capabilities/wikilinks]] owns; an unknown block id and a block id two
  figures of one note carry are build errors that name the note and the link or figure.
- The core runs the figure lint on every build: a figure fence without caption, a figure fence
  without block id (its remedy names the `^name` line, so a reference can be offered), an image file
  alone in its paragraph (`![...]` of another file is an attachment), a caption outside the
  figure and a typed figure number, each a Document diagnostic with its note line.

  It knows no numbers and reads no adapter's options: typed numbers are recognised after the labels of the
  core configuration (`input.figureReferences.labels`, whose default
  `src/obs/config.schema.json` owns), and the suggested link is the note's figure at the
  position the number's last component gives.
- The adapter numbers the figures, shows the number, renders a reference as the figure's label
  and number and merges adjacent references; the error for an unlabelled reference to an
  unnumbered figure is the adapter's, since only it knows numbers.
- A hard line break (the Document's `break` node) ends a group of adjacent references, as
  it did in the interim adapter; a soft line break is whitespace.

Confirmed defaults, same date:

- Numbering stays off unless the manifest sets it (documents opt in, nodes sets `chapter`):
  a document without numbering renders unchanged, and numbers belong to documents whose
  figures are all captioned and referenced by block links.
- The Sankey option keeps the name `countLabels`: it says what it configures, the words shown
  with record counts, and renaming would only move every author's fence without new meaning.

For `svg`, the fence's optional `panels` list (the interim adapter read it from a source JSON
with `version: 1`) declares per panel `id`, `title`,
and `box: [x, y, width, height]` in SVG viewBox coordinates.

Optional grid/span/aspect/axis
metadata documents the producer's composition. The complete exact SVG remains the default
and print view; an inspector selects a panel for independent uniform vector viewport
zoom, pan and reset.

This is viewport inspection, not data reflow or recalculation. Producers retain responsibility
for engineering geometry, subplot placement, annotation,
hatching and provenance. Interaction and visual parity are the adapter's.

Python-generated figures follow one producer convention: the artifact-owned script writes the
exact `<name>.svg` and its `<name>.figure.json` panel sidecar side by side.

The author places, captions, numbers and references the figure only through the Markdown fence;
the
generator and project adapters add nothing. Panel boxes are in SVG viewBox units.

For `sankey`, the graph (its source JSON or inline `content`) has `version: 1`, `nodes`, and `links`.

The core checks every graph at build time, a `sankey` figure's and a `plot` descriptor's
`data.sankey`, static or a dynamic projection: against `figure.schema.json` `$defs/sankeyGraph`,
which the Document's `sankey` figure body references, and then, in code, that each link's `source`
and `target` names a node of the graph, a cross-reference no schema states.

An adapter checks the other rules below as it draws. Each node has a unique
nonempty `id`, display `label`, and integer `stage` from 0 through 15; each link names existing
`source` and `target` node ids and a finite positive `value`.

Optional node/link `color` values are six-digit hex colors; a link may also carry a display `label`.
Ordinary flow
links must move to a strictly later stage. At least two nodes and one link are required. Unknown fields,
duplicate ids, missing endpoints, nonfinite or nonpositive values, and graphs above 256
nodes, 1024 links, or 4 MiB of source JSON are errors.

An optional `data` mapping makes a Sankey a dynamic projection of canonical artifact records.

It has a nonempty `where` list; every condition names a canonical record field and has either
`exists: true` or an exact string `equals` value. A dynamic link has its own nonempty `where`
list with the same condition shape. Each canonical record matching `data.where`, the current
artifact-wide filter, and a link's conditions contributes one unit to that link.

The authored positive `value` is the portable unfiltered and print default. Generic browser
infrastructure
recomputes link weights and layout from the same canonical records when the artifact filter
changes. The query-table filter remains table-local and does not alter the diagram.

Dynamic Sankey projections omit zero-population nodes, their inactive links and labels
without deleting the authored alternatives from the canonical figure definition.
Declarative placement can put intermediate sinks above or below the main flow;
the artifact owner supplies placement, not domain-specific inference in the converter.

An explicit above/below sink may occupy an earlier or the same stage as an incoming
source, including stage -1 before the first flow stage. A shared sink can receive links
from different flow stages; its authored horizontal position does not constrain those
incoming links.

Such a sink has no outgoing links. A one-stage graph with a placed sink has finite,
centered coordinates in both static and browser rendering. Ordinary flow
nodes remain nonnegative and flow links still advance; the exception does not permit
cycles or backward ordinary flow.

Node `placement` is `flow` (default), `above`, or `below`. The latter two retain their
authored stage but occupy compact horizontal sink bars above/below the vertical flow
nodes, not a forced middle slot. Placement does not change record membership.

Node and strand activation select their exact canonical record membership by adding
a valid expression through the ordinary global Filter owner. There is no separate
hidden selection predicate. The resulting query is visible, editable, saveable and
clearable like a typed expression.

An optional graph `branchLayout: split` selects the legacy balanced-branch layout.
In this mode `above`/`below` retain the configured backward/forward branch direction;
the physical upper/lower rails are packed independently by the legacy interval,
descending bar-width, two-lane load-balancing algorithm. They are not synonymous
with branch direction.

Optional node `branchSource` identifies the flow-node anchor for a shared sink; optional
safe-integer node/link `order` supplies stable node/trace
ordering. Optional node `branchOrder` carries a producer's lexical tie order,
independently of vertical node order; otherwise ties use UTF-16 id order in both
runtimes. This avoids depending on the converter host's collation locale.

The renderer carries an incoming strand's connection height through its
flow node and reverses the horizontal sink attachment order in the appropriate
quadrants, preserving the legacy untwisting rule. This mode is opt-in; omitted
metadata preserves existing fixed above/below placement.

Static and interactive renderers implement the same figure-owned layout, including finite
single-stage
and disconnected-stage projections.
Authored stage bounds, rather than longest-path depth alone, bound the column grid:
optional/disconnected levels must not clamp a later flow node onto its predecessor.

Label footprints reserve their full normal-font width and multiline height,
including displayed record/unique counts. Expand horizontal intervals, vertical
node separation and rail clearances as needed rather than squeezing glyphs,
reducing label fonts, truncating or clipping text to fit.

In particular, SVG textLength/lengthAdjust compression is not an acceptable collision fix.
Labels
must not overlap other labels or bars in inline or expanded viewing. Preserve
the complete text in accessible names and SVG titles as well.

Use the available figure width for the plot, apart from the clearances required by
its complete labels and controls. Avoid an artificially narrow centered drawing
with large unused horizontal margins; filling the width must not compress glyphs
or reintroduce label/bar collisions.

Node membership is the union of incident links' conditions, restricted by `data.where`
and, for a counted node, by its own `records.where`; a strand uses its own conditions
restricted by that population.

Equality clauses are anchored exact values, not substring
matches; existence requires a nonempty value. A dynamic node's count and its drill-down
are one selection over its visible incident links: the label counts what that expression
matches, and the drill-down selects it.

An optional link `unique` names a canonical field containing its distinct target-item
identities.
A shared sink unions those values only from matching active incoming contributions,
so hiding a contributing level cannot retain that level's item counts. Without
incoming contribution fields, the node's existing `unique` field remains the default.

A counted node shows two lines below its label: `<n> <unit>` and `<n> <unique>`. The first
counts the node's selected rows, the rows its drill-down shows; the second counts the distinct
`unique` items over those same rows, so a row holding several items can make it the larger.

The fence's optional `countLabels: {unit: <noun>, unique: <word>}` names them; the neutral defaults are
`records` and `unique`. Domain vocabulary is authored in the
fence, never built into the converter.

Accessible names fall back to `alt`, the rendered caption text, `source` and finally `Figure`.
Producers must declare link predicates at canonical path granularity, not broaden a
strand to all paths sharing an originating item. A selected expression replaces the
global Filter expression and opens that input; there is no second selection state.

The converter renders the bounded declarative graph as a self-contained SVG; it does not
infer domain meaning, execute code, fetch assets, or copy source records into the graph.

The artifact owner defines node labels, stages, record predicates and the unfiltered value
derived from its canonical model. Rendering, record selection, artifact-filter integration
and SVG layout are generic. Conditions are data-only field checks, not query strings or
executable expressions. Diagram interaction and print behavior are the adapter's.

#### Equation figures

Decided by the user, 5 Nov 2026 (work issue `feature/equation-figures-core-20261105`):
equations are written as SymPy writes them, every variable has a default value and a range it
can move in, and the author says which value goes on which axis.

The domains, the equations and the initial plot are fixed in the Document; the plotting
happens live in the artifact. There are no 3D plots of equations.

An equation figure is a `figure` fence of `kind: equations`. Its content, inline under
`content` or from a YAML or JSON `source` file, is a mapping:

- `equations`: one equation or a list, in SymPy syntax: `lhs = rhs`, `Eq(lhs, rhs)`, or an
  expression that equals zero. A derivative is `Derivative(y(t), t)`, `y(t).diff(t)` or `y'`.
- `variables`: every symbol the equations use, by name. Each is a quantity note's `[[alias]]`
  (its value is the default; its unit and range come from the note), a mapping with that
  `quantity` and a `range` of its own, or its own `default`, optional `range` and `unit`.
- A function, `y` in `y(t)`, names its variable in `of`. Its `initial` lists its value and
  its derivatives below the equation's order at the start of that variable's range.
- `unknowns`, optional: the variables the equations determine, one per equation. Without it,
  they are the plotted `y` entries that are variables of an equation.
- `plot`: `x`, a variable or an expression of one movable variable, swept over its range (a
  differential system sweeps its independent variable); `y`, one or more expressions, each a
  string or `{expression, axis: secondary}`.
- `plot.family`, optional: one curve per value of a third variable, `{variable, values}`, or
  `{variable, steps}` for that many values spread evenly over its range.
- `plot.parallelCoordinates: true`, optional: the figure shows its parallel-coordinates plot
  from the start; without it, the reader opens the plot from the figure's menu. Each line of
  the plot is one combination of the grid variables' values, and the curves below are the
  combinations the reader selects ([[capabilities/equation-figures]]).
- The grid: every movable variable that is neither an unknown, a function nor the x sweep is an
  axis, in the order of `variables`; a fixed variable is not. `plot.grid`, optional, gives a
  variable `{values}` (in its unit, inside its range) or `{steps}` spread evenly over its range;
  any other grid variable gets 5 steps.
- `plot.computed`, optional: computed axes after the grid's, each with an optional `name` (its
  label; else its expression or `summary(of)`). `{expression}` is an expression of the
  variables without the x sweep, its unknowns or functions.

  `{summary, of}` summarizes the curve of the expression `of` over the full x range:

  - `maximum`, `minimum`, `xAtMaximum`, `xAtMinimum`;
  - `final` (its last value);
  - `area` (under the curve, over x), `absoluteArea` (under its absolute value);
  - `valueAt` with `at` (an x in x's unit, inside its range);
  - `settlingTime` with `tolerance` (a fraction between 0 and 1): the first x after which the
    curve stays within `tolerance` times its change, |final − first value|, of its final value.

Range rule: a variable's range is where it can move. A quantity note's `range` and the fence's
`range` intersect; with one of them, that one is the range; with neither, the variable is fixed
at its default and cannot move. An empty intersection, or a default outside the range, is an
input error that names the note, the fence and the remedy.

The core resolves the symbolics once, with SymPy (`src/obs/equations.py`):

- It parses every equation and refuses an unknown symbol, an undefined function and a function
  the expression tree has no operator for, naming the note, the equation and its line.
- It checks dimensions with the quantities' units ([[capabilities/quantities]]): the terms of a
  sum, both sides of an equation, `Min` and `Max`, and the dimensionless arguments of `exp`,
  `log` and the trigonometric functions. A mismatch names both quantities.
- It solves the unknowns where SymPy can: `solve` for algebraic equations, `dsolve` with the
  initial conditions for differential ones; each solution is one branch. A solution SymPy gives
  piecewise stays piecewise.
- Where a denominator of a solution vanishes at a value inside a variable's range (the
  oscillator's critical damping, ζ = 1, where its general solution is 0/0), the branch is
  piecewise: at that value it is SymPy's limit there, elsewhere the general solution; at a pole
  there is no point.

  Where SymPy finds no limit, or the tree cannot carry it, and the variable is
  not the x sweep, the solution marks the value and carries the numeric system below as well,
  and a curve at a marked value is solved numerically. No curve inside a range is empty.
- Where it cannot, the Document carries the system for numeric solving: algebraic equations as
  residuals, with each unknown's `default` as its starting guess.
- A differential system goes in state form: its independent variable and start, its state
  (each function and its derivatives below the highest), each state's derivative and the
  initial state.

The Document carries every equation, solution and plotted expression as a JSON expression tree
of numbers, variables, derivatives and operators, never a string to execute. Numbers in a tree
are dimensionless; every variable carries its quantity with SI values (`$defs/quantity`), so a
tree evaluated with SI values yields SI values.

A tree evaluates in complex arithmetic with principal branches. A result is a point of the
plot where its imaginary part vanishes, so an exact solution with complex intermediates (an
underdamped oscillator) plots for every parameter.

A piecewise tree's value is that of its first
case whose condition holds; an equality holds within the shared vectors' relative tolerance, so
a value that a unit conversion rounds still meets its case. `src/obs/document.schema.json` owns the tree
(`$defs/expression`) and the figure's body (`$defs/figureBodies/equations`).

The Document's `plot.parallelCoordinates` carries `shown` and the axes: a grid variable's
values in its unit and in SI, a computed expression's tree, and a summary's kind, the `of`
expression's tree, `at` in SI and `tolerance`, each with its dimension.

The core computes the grid; the adapter evaluates the curves, so it computes every computed axis's values, applies
its own cap on the number of combinations and draws the plot.

The shared test vectors, `test/fixtures/expression-vectors.json`, hold expression trees,
variable values and expected results. The core checks them against SymPy; an adapter's live
evaluator checks itself against the same file.

#### Pugh decision figures

Decided by the user, 6 Nov 2026 (work issue `feature/pugh-decision-figure-20261106`): decisions
are Pugh matrices, written in Markdown and rendered by an adapter as one figure, a one-pager.
obs provides the form; the design is the adapter's.

A decision figure is a figure of kind `pugh`. A plain ```` ```pugh ```` fence, as Obsidian shows
it, is one without caption, alt or block id, and its whole text is the matrix in YAML. A `figure`
fence of `kind: pugh` holds the same matrix under `content`, or in a YAML or JSON `source` file.

The matrix has the shape of the matrix file of ctrl's Pugh engine: ctrl's
`design/output/pugh.md` (github.com/mb-89/ctrl), "The matrix file", owns it. Every option has a
letter, A, B, C and on, in the order `candidates` lists them, at most 26 options. obs adds:

- `chosen`, optional: the key of the option the author chose, which the figure checks.
- On each option, optional: `what`, one sentence on what it is; `wins` and `losses`, short texts
  of its own gains and losses, which add nothing to the totals.
- On each option, optional: `short`, its short name, at most 5 words, ideally one, which an
  adapter shows after the letter where there is room (decided by the user, 6 Nov 2026, work
  issue `feature/decision-figure-on-phones-20261106`). Without it, the label serves where it has
  at most 5 words; otherwise the letter stands alone. The core resolves this once, into the
  body's `shortNames`, below.
- `checklist`, optional: items, each with `item` (the question), `answer` (one line), `pass`
  (true or false) and, optional, `options`, the letters of the options the item fails.
- `checklistWeight`, optional: the weight of the row the failed items make, 3 by default.

Decided by the user, 6 Nov 2026 (work issue `feat/decision-solutions-and-details-20261106`): a
decision takes up the ADR's shape where it helps the reader, as optional fields, with no status,
date or decision-maker fields:

- A mark with its reason: on an option's `marks`, a criterion's mark is a mark (a number, or a
  rater list), as before, or `{mark: <mark>, because: <text>}`, the mark and the reason for it.
  An adapter shows the reason as an argument for or against the option; the mark alone is what
  ctrl's engine decides, so an adapter hands the engine the mark without the reason.
- `context` and `concern`, optional: one phrase each, the situation and the concern the decision
  answers, for the decision's one-sentence summary (a Y-statement).
- `supersededBy`, optional: the decision that replaces this one, as the text that names it (a
  note's title or a decision's number); an adapter says so at the chapter's top.

Decided by the user, 6 Nov 2026 (work issue `feat/decision-success-and-winner-box-20261106`):
every option says what success means for it, so the decision-level `confirmation` is gone, with
no alias:

- On each option, optional: `success`, one line on what marks that option successful once done,
  its success criterion. An adapter shows it with the option and with the proposed winner; the
  engine never sees it.

An option's `figures` and the matrix's `overrides` are refused as unknown fields: a figure is
the adapter's drawing, and the reader's changes are the adapter's reader state.

The core checks the matrix against `$defs/pughMatrix` of `src/obs/document.schema.json`, then
what no schema states: unique keys; every criterion a value, a mark or a gate names; values for
measured criteria, marks for judged ones; and a hard gate on a measured criterion.

It also checks the options `datum.prefer` and `chosen` name, the letters a checklist item names,
that no criterion is keyed `checklist`, the key of the row the failed items make, and that no
`short` has more than 5 words.

A matrix it refuses is an input error in the one form: the note, the fence, the field path
within it (`content.criteria[1].better`, `source.chosen`) and the remedy, naming
[[capabilities/pugh-decisions]].

The figure's body carries the checked matrix as data (`matrix`). The core decides nothing: an
adapter runs ctrl's engine on it, in the reader's page, so a reader's change is decided again
there.

Beside it, the body carries `shortNames`: each option's short name, in the order `candidates`
lists them, as the core resolved it from `short` and the label, or null where the letter stands
alone. Decided by the dispatcher, 6 Nov 2026 (work issue
`fix/decision-figure-follow-ups-20261106`): an adapter shows these and keeps no rule of its own.

A chapter's `##` sections after its decision figure stay where the core puts every section: in
the chapter's content, after the figure, in order. The core adds nothing to the figure for them.

An adapter that shows them as the figure's tabs gathers them when it renders the chapter.
Decided by the worker, 6 Nov 2026: the Document already carries the sections, so its schema
does not change.

### Markdown body and frontmatter

- Relative Markdown links and local images must stay within the source vault.
- The Markdown body is the complete source of rendered prose content.
- The Markdown dialect the body is written in, and the Document nodes each construct
  becomes, are [[capabilities/markdown#Document nodes]].
- Converter paragraph diagnostics measure authored prose with the supported Markdown dialect,
  before render-time decoration, and retain its source location. Home diagnostics measure only
  the authored abstract, not generated content or metadata. Reusing a parsed body must not let
  rendering mutate the tokens consumed by diagnostics or subsequent renders.
- Optional YAML frontmatter must be a mapping with string keys. Its values are normalized
  to JSON-compatible scalars, lists, and mappings for the canonical artifact store.
- Frontmatter is never rendered verbatim as body text and cannot inject styles.

  Obsidian's `cssclasses` (one class name or a list of them) is the note's styling hook: the
  names are validated CSS class identifiers and are projected onto that note's rendered
  container, as the adapter places it. Styles come only from the CSS snippets the adapter's
  presentation options list; no adapter gives the classes a meaning of its own.

- Every frontmatter field is available to the shared query language. Nested mapping fields
  use dotted names, quoted field names address spaces,
  and bare queries search both field names and values. Within quoted query values, `\"`
  and `\\` escape a literal quote and backslash.
- The reader may expose frontmatter as derived metadata outside the Markdown body.

#### Long paragraphs

The core warns about a paragraph too long to read in one pass, on every build and `--check`, as
a Document diagnostic with its note line (`<note>:<line>: long paragraph (...)`). Like the figure
lint, it never changes the Document, and no adapter writes it into an artifact.

- The estimate is the interim adapter's, unchanged: the paragraph's text and inline code pieces,
  joined by spaces and wrapped at `lineCharacters` with Python's `textwrap`, warn above
  `warningLines` lines.
- A wikilink counts as what it shows: its label, else the linked note's title, then ` > ` and
  the heading. Images, math, a Markdown link's target and tables are not prose; neither are a
  callout's `[!type]` marker and a piece starting with `#mark/`.
- The home measures only the authored abstract, not the title, subtitle or other metadata. A
  card body is not a note's own text and is not measured.
- The numbers are the core configuration's `input.longParagraphs.warningLines` and
  `input.longParagraphs.lineCharacters`, which `src/obs/config.schema.json` owns. They keep the
  interim's `artifact.reading` defaults and limits, and belong to the core, which owns the lint.

### Mark tags

Replaced by callout types (user, 4 Nov 2026; see [Callouts](#callouts)); this section describes
the current implementation until that migration lands.

Mark tags classify a paragraph as an open point, risk, warning, decision or another fixed kind.
This section owns their syntax and records. Their presentation is the adapter's, and
the per-kind register is the `marks` [register](#registers).

- A paragraph may contain one or more whitespace-delimited Obsidian-compatible semantic tags of the
  form `#mark/<kind>/<underscore_label>` at any position.

  Supported kinds are `open_point`, `risk`,
  `assumption`, `issue`, `decision`, `warning`, `question`, and `idea`.

  The paragraph remains the sole
  source of all its prose; tags are omitted from rendered text without removing surrounding prose.
- Tag kinds are composable facets rather than exclusive states, so the same paragraph may, for
  example, be both an open point and a decision. Each tag produces a canonical record that shares
  the paragraph prose and source anchor. Tag labels are non-empty lowercase words separated by
  underscores. Unknown kinds, malformed tags, and duplicate tag identities are lint diagnostics.
- References to marked open points use their existing stable mark identity, never a
  position-derived number or a copied question as the reference label. Preserve existing
  source anchors and resolve the identity to the same canonical marked record.

  Mark identities and heading slugs share a note's fragment namespace: a fragment resolves to
  a mark only when that mark exists, otherwise to the heading, so a heading such as
  "Mark tags" stays reachable at generation and at runtime.

  The marked paragraph alone carries the mark identity as its element id. Tag-table rows
  and other projections are addressed by their table row key, never by a second element id.
  Backlinks are derived from resolved references in included note bodies and frontmatter,
  retaining their source locations.

  The owning marked paragraph is also a source location; generated table cells, previews
  and other projections do not introduce extra backlinks.
  A source location is the owning paragraph, a referring body block, or a referring
  frontmatter field; repeated links within that same location yield one backlink.
- An artifact uses these marked paragraphs in their owning authored chapters instead of
  a separately maintained numbered open-point register or synthetic open-point notes. Preserve
  the question, decision impact, actions, existing answers, evidence and unresolved
  qualifications together in the owning marked paragraph so all appear in its generated
  overview row.

  Concision must not separate substantive content from the point; an answer alone does not
  imply closure. Replace legacy register links with links to the owning marked
  paragraphs. Counts and overview tables query the canonical marks, never a parallel dataset.

### Base fences

- A fenced block with info string `base` is declarative table content embedded in an ordinary note.

  This is the general authoring contract for artifact data tables, not a Node-only adapter.
  The owning Markdown declares each table's query, placement, columns and view options;
  supported card bodies and the manifest abstract use the same fenced syntax.
  Removing, moving or changing a fence removes, moves or changes that table.

  Neither a chapter name nor application code may silently append or reinstate an artifact
  table.
  Adapters may project canonical records, but do not own a parallel hidden query.
  Framework-supplied content must likewise expose its table declaration as Markdown,
  rather than maintaining an equivalent private definition in renderer code.

  Obsidian Bases is the reference language, not merely a visual model for tables.
  The reference owners are Obsidian's [[obsidian-bases-syntax|Bases syntax]],
  [[obsidian-bases-views|view/filter semantics]],
  [[obsidian-bases-functions|functions]] and
  [[obsidian-bases-table-view|table view]]. This bridge implements
  the bounded subset below, not complete Bases parity.
  Content-aware query, formula, selection, grouping and composition rules belong in
  Obsidian-compatible Markdown declarations.

  The bridge translates those declarations; it does not invent artifact semantics. Supported
  standard syntax retains its Obsidian
  meaning. Unsupported syntax fails explicitly, never falling back to an application-specific
  interpretation. Artifact-only extensions must not redefine standard Bases fields.

  Home has no implicit tables. Its tables are ordinary fences in the manifest
  abstract (the maintained `spec/manifest.md` is an example). History and residual
  metadata headings are authored too. This intentionally replaces the former
  invisible Home defaults: migrating an existing manifest is an additive source
  change, never a renderer fallback.

  A Base normally evaluates canonical note rows once, as native Bases does.
  `obs.records` explicitly selects an artifact-only row projection: `note`, `chapter`,
  `tag`, `glossary`, `documentHistory` or `documentMetadata`. A `note` projection adds
  the artifact's own note fields to the canonical note rows.

  A filter comparison on a bare `recordType` is rejected with a migration message naming
  `obs.records`. View filters intersect global Base filters during discovery and rendering.

  Filter syntax and comparison semantics are owned by the
  [[#Bases filter grammar]].

  An adapter's notion of an assigned
  value is not a redefinition of standard Base equality.
  Standard views have at most one `groupBy` property; multi-property sorting is
  supported, but multi-property grouping is not reinterpreted as native syntax.
  Native note columns and predicates read actual frontmatter and supported `file`
  properties, not artifact-synthesized chapter/title/discriminator fields.

  Data-dependent columns are opt-in presentation, not a domain query compiler.

  An adapter's `expandProperties` option maps an ordered property to
  `{sourceNote, property, keyProperty, labelProperties?, separator?}`. The named
  canonical note's property is an ordered list of objects; each unique nonempty
  key expands `field` into `field.<key>`, inheriting its authored property
  presentation. Optional label properties are joined with the authored separator.

  The ordinary `field` column remains the native view when the extension is not
  interpreted. This changes presentation only, never selection or grouping.
  Invalid/missing sources, duplicate keys and collisions are errors.
  Reference metadata paths may contain a `*` array segment; it expands against
  each referenced note's current array, preserving index-specific rich metadata.

  Cards retain the existing bounded count contract, not an Obsidian formula
  claim. A card may declare `obs.metricsFrom` with `sourceNote`, `property`,
  `labelProperty`, `distinctProperty` and an ordinary count `where`. Each object
  in that canonical data list supplies a label and the field whose distinct
  values are counted.

  The declaration, not the data producer, owns this query and whether/where
  these metrics exist. Optional `link: {note, groupProperty}`
  routes each label to its drill-down in that authored note's table
  ([[capabilities/cards-metrics#Drill-downs]]); `tone`/`toneRules` use the
  existing metric contracts.

  This is a typed presentation projection, not string interpolation, arbitrary
  template syntax, a new predicate evaluator or a numeric/formula engine.

  An authored metric's `obs.projection` selects an opaque trusted
  application-provided field projection. A Base's adapter option `viewProjection`
  similarly opts into an application presentation; optional `fallbackColumns`
  declares its all-hidden column view. These declarations do not grant trust.

  Applications may only narrow the authored result rows or project its columns,
  never replace or resurrect its query/composition. Removed opt-ins receive no
  application presentation. Generated table ordinals are not application APIs.

  Authored artifact tables use these queries, never pipe-delimited Markdown tables.
  Each row is a canonical note; columns project its frontmatter or canonical semantic fields.
  Row-specific explanation and evidence belong in that note's body and remain accessible
  through the shared table's existing detail expansion.

  Preserve meaningful row order, relationships, units and qualifications during migration,
  including chapter-two and
  chapter-three tables. Reuse existing quantity, glossary, reference and marked-paragraph
  owners rather than copying their data into parallel row records.

  Its body is valid YAML using Obsidian's standard `filters`, `properties`, and `views` shape.

  The
  initial adapter supports table views, ordered properties, and the filters defined by
  the [[#Bases filter grammar]].
  Reader and static projections evaluate canonical typed values, not display text.

  Unsupported standard
  syntax fails generation clearly rather than being reinterpreted.
  Supported file properties are `file.name`, `file.path`, `file.folder` and
  `file.ext`. Other file properties, formula properties, and `this` context
  expressions are currently unsupported and rejected, not treated as missing
  frontmatter.

  Formula declarations and other view types remain unsupported. Frontmatter
  names colliding with the `file.*` namespace are not supported by
  this bounded reader, including `note.file.name` and `note["file.name"]`;
  they are rejected rather than evaluated as file metadata.

  Artifact-only additions live under
  a top-level mapping in the adapter's namespace so normal Bases syntax remains portable and can expand independently;
  what the core reads lives under `obs` ([[#Core and adapter namespaces]]).

  For a view whose membership or order cannot be expressed by canonical note properties,
  `obs.members` is an ordered list of `{path, label?}` entries.

  `path` is a unique, vault-relative Markdown filename; `label` is optional view-local display text, exposed only
  as a derived cell. The list belongs to the view's `obs`; a Base-level
  `obs.members` fails the build, naming the note, with the remedy to move it into the view.

  The list never writes membership, rank, or labels into a note. It intersects the standard
  Base filter and initializes row order, in which the core emits the rows; interactive filters
  and sorting remain table-local. Every path must resolve to a file inside the vault, or
  `--check` fails. Notes matching a Base query are included even without prose backlinks.

- Notes containing base fences remain ordinary manifest chapters: authored prose before and after a
  fence renders normally, and manifest position alone determines chapter hierarchy and navigation.

#### Base files and members

- An embedded `base` fence or an embedded `.base` file is the input adapter. Standard Obsidian keys
  retain their meaning; what the core reads is permitted only under `obs`, artifact-specific
  behavior only under the adapter's namespace ([[#Core and adapter namespaces]]).

  A line `![[name.base]]` or `![[path/name.base#View]]` embeds a reusable `.base` file as in
  Obsidian. A target with a folder is vault-relative; a bare name must match exactly one
  non-hidden file in the vault. A bare name that matches none or several fails the build, naming
  the embedding note and the candidates; the remedy is to embed the file's vault path.

  The file holds the same YAML as a fence and passes the same validation once per build.
  `![[file.base]]` embeds all views with the selector; `#View` embeds only that view. Every
  embed is its own table instance with its own key and state, so two notes embedding one
  file render it twice from one definition. Registers use this mechanism ([[#Registers]]).
- A view may declare ordered `obs.members` entries containing a vault-relative note `path`
  and optional view-local `label`. This set intersects the ordinary Base query; its order is the
  initial row order, in which the core emits the view's rows, and its labels are projected as a derived cell without modifying canonical
  note records.

  Missing, duplicate, absolute, or vault-escaping member paths, and paths that are
  not Markdown notes, are input errors naming the note, the view, the entry
  (`views[<view>].obs.members[<entry>].path`) and the remedy.
  Members belong to their view: each view selects its own members, and a Base-level
  `obs.members` is an input error naming the note; the remedy is to move it into the view.

#### Bases filter grammar

This subsection owns the supported subset of Obsidian
[[obsidian-bases-views|Bases filters]]. It applies to Base `filters`,
view `filters`. Anything outside it is unsupported.

- A filter is one comparison string or a mapping with exactly one key, `and`, `or` or
  `not`. That key holds one filter or a nonempty list of filters, nested to any depth.
  `and` needs all operands, `or` needs one, and `not` means none of them is true.
- A comparison is `property == literal` or `property != literal`, with optional spaces
  or tabs around the operator. The `comparison` pattern in `base.schema.json` owns the
  exact characters, so both runtimes read the same syntax.
- A property is `name`, `note.name` or `note["any name"]`. A bare `name` uses ASCII
  letters, digits, `_` and `.` and starts with a letter. Both prefixes read the same
  frontmatter property. `file.name`, `file.path`, `file.folder` and `file.ext` read the
  note's vault-relative path, not frontmatter.
- A literal is `null`, `true`, `false`, a JSON-style number, or text in double or
  single quotes. Quoted text is taken verbatim; it contains no backslash, line break
  or its own quote character.
- A property resolves to a whole frontmatter key first, its name matched by
  [[capabilities/bases#Comparisons]]. Otherwise its dots walk nested mappings. A numeric segment selects a list item; other segments collect the values of
  every list item. Segments never read text or list members such as Bases' `.length`.
- Equality follows [[capabilities/bases#Comparisons]] (case, types, missing properties).
- Functions, methods, other operators, `formula.*`, `this.*`, other `file.*`
  properties and frontmatter names starting with `file.` are unsupported.

Python evaluators decide at generation time which notes a Base includes, because the
generator runs without a JavaScript engine: the core's `src/obs/selection.py` for the
Document. An adapter whose readers can edit Base definitions or canonical values evaluates
again.

Every evaluator runs the shared conformance fixture
`test/fixtures/bases-filter-conformance.json`, which lists records, filters, expected
record ids and unsupported filters. A grammar change updates this subsection, the schema
pattern and that fixture together.

Generation fails on an unsupported filter. The error names the source file, the base
fence, the field (`filters` or `views[<view>].filters`), the filter text and this
subsection; it never treats the filter as matching nothing.

A view's `obs.records` evaluates projected rows of one kind instead of canonical notes;
the base's `obs.records` is the default for its views. A comparison on a bare
`recordType` is rejected with a migration message naming `obs.records`. Both
evaluators resolve a projected row's properties in the same way.

A row's own fields resolve first: `sourcePath`, plus `chapter`, `title`,
`slug` and `depth` on note and chapter rows, `term`, `definition` and `aliases` on
glossary rows, and `type`, `label`, `text` and `source` on tag rows.

Any other property of a note, chapter or glossary row resolves on its note's frontmatter
and path as above. A tag row has no other properties. Displayed cells, such as flattened
frontmatter text or tag backlinks, are never filter values.

Document metadata rows (`recordType` `documentMetadata`: `key`, `value`) and history rows
(`documentHistory`: `version`, `date`, `author`, `change`) never include a note; all their
fields are own fields.

[[#Cover metadata and history]] owns their content. The core emits a manifest metadata
row per frontmatter key other than `history`, `obs` and an adapter's namespace
([[#Core and adapter namespaces]]), with its value as authored; the
adapter adds the rows of its own generation provenance.

The core emits every projection as records of its type in the Document's `records`, a
tag row for each mark of a marked paragraph; `src/obs/document.schema.json` (`$defs/record`)
defines each record type and its fields.

Inclusion, table rows and tag navigation to the table holding a row use the grammar above.
Counts are not Bases filters: they use the record-metric conditions owned by
[[#Document home and abstract|cards]].

### Glossary

- Glossary tables consume canonical glossary records rather than inferring definitions from rendered
  prose. Each concept has one canonical glossary record regardless of its aliases.

  Glossary-note discovery supplies these records rather than maintaining hardcoded definitions.
- Glossary notes declare `kind: glossary`, a nonempty `term`, and a nonempty inline
  Markdown `definition` in frontmatter. Their definitions and aliases feed the canonical record,
  and glossary tables link terms to their source note.

## Bless requests

Decided by the user, 6 Nov 2026 (work issue `feature/bless-verdicts-20261106`): a chapter can ask
its reader to bless it, and a manifest of such chapters is a deck the reader walks, giving a
verdict on each. A decision reaches the person this way, as an artifact obs builds.

A chapter note's property `obs.bless: pending` asks for a bless. Without it the chapter is a
record and asks nothing. `pending` is the one value; `note-profile.schema.json` refuses another
with the field path `obs.bless`.

The Document's chapter carries the request as `bless`, with the chapter's `version`: the
SHA-256, in hex, of the note's source and of every vault file it embeds (an embedded note, image
or Base, a figure's `source` file). Each counts as its vault path, its length and its bytes, the
note first, then the rest by vault path.

An edited chapter, or one whose embed changed, asks again; a remote image is no vault file and
does not count.

`spec/examples/bless-deck` is the example: a deck of two decision chapters, which the suite builds
and walks (the html adapter's `test/test_bless_browser.py`).

### Answers

A reader's verdicts come back as one answers file, a JSON object whose `verdicts` list holds one
verdict per chapter. `src/obs/answers.schema.json` owns its fields, once, for the adapter that
writes it and the core that reads it:

- `chapter` and `version`: the chapter's id and the version it was answered at.
- `verdict`: `bless`, `decline`, `ask` or `pick` (another option than the decision's winner).
- `comment`: the reader's comment, which `decline`, `ask` and `pick` need.
- `pick`: with `pick`, the decision figure's anchor (`figure`) and the picked option's letter,
  or `none` where the reader picked none of the options (`option`).
- `figures`: by figure anchor, the reader's changes to a decision figure, as its reader state
  holds them (weights, marks, rulings with their tripwires), and the `winner` they give.

`obs-document --answers <file>` builds the Document with the answers in it, so the answered
artifact is the decision record ([[cli#Answers]]). A verdict whose version is the chapter's is its
`answer`: the chapter shows it read-only and asks nothing. A verdict at another version is
`outdated`: the chapter asks again and shows the old answer as outdated.

A verdict for a chapter that does not ask, a second verdict for one chapter, or a file the schema
refuses is an input error naming the answers file and the field path (`verdicts[0].chapter`).

## Command-derived content

- A fenced block with the info string `cmd` is derived content rather than prose.
- When command execution is authorized for a build, the fence body runs from the vault
  root and its captured output replaces the source fence in the artifact.
- A `cmd silent` fence is a producer: on an authorized build, all producers run from
  the vault root in path and source order before the vault is read for conversion.
  It renders no command output. Its files are ordinary vault inputs, so an unauthorized
  build and `--check` use only files already on disk.
- Command output is escaped for the artifact's format and rendered as preformatted content; it
  cannot inject artifact markup or styles.
- A timeout or nonzero exit fails generation so stale or partial reference output is not
  published.
- Builds never execute command fences without explicit authorization because a vault may
  contain arbitrary commands.
- The CLI note uses this extension to embed help from the executable that owns it.

## Block node ids

Decided by the owner, 9 Nov 2026 (work issue `feat/stable-block-node-ids-20261109`): every block
node carries a stable id, so a comment ([[#Comments and reviews]]) or a sync record can target any
block. One id scheme in the core serves every adapter.

The core gives an `id` to every block node of a chapter's content and of the manifest abstract
whose type `document.schema.json` lists as identified (`$defs/identifiedType`): headings,
paragraphs, lists and list items, quotes and callouts, tables and table rows, code, display math,
rules, command fences, figures, cards and the blocks of a card's body, and the other fenced blocks.

Inline nodes, a table's cells and the capability markers carry none. An id is unique within its
chapter, or within the abstract. `src/obs/node_ids.py` assigns the ids after the note reader, for
every adapter alike.

### Explicit ids

An Obsidian block reference is the block's id, unchanged, and is not shown:

- `^name` at the end of a paragraph names that paragraph, and in a list item's first paragraph
  names the list item.
- A paragraph that is only `^name`, after a block, names that block: a table, a list, a quote, a
  code block. A figure's `^name` line is its block id ([[#Figure captions and references]]), and
  so its node id.
- `name` is letters, digits and hyphens. Two blocks of one chapter with the same name are an input
  error naming the chapter's note.

### Derived ids

A block without an explicit id gets `<type>-<hash>`: its node type and the first eight hex
digits of the SHA-256 of its normalized text.

The normalized text is the block's own authored content with whitespace runs collapsed: the text of its inline nodes, its formula or code, the
authored attributes of its nodes (a link's target, a figure's kind and caption, a fence's source)
and, for a table row, its cells in order. What a build computes, a command's output and a
register's rows, is not part of it.

So the id is the same in every build of the same source, and inserting, removing or editing
another block leaves it unchanged. Blocks of one chapter with the same type and normalized text
are numbered among themselves, in document order: the first keeps `<type>-<hash>`, the next ones
get `-2`, `-3`, and so on. A derived id that equals an explicit id of the chapter takes the next
number too.

The trade-off: a block's id changes when its own text changes, and a container's (a list's, a
table's, a quote's) when any text inside it changes. A comment on such a block becomes an unmapped
target, a warning and no error ([[#Comments and reviews]]). An author keeps the target across edits by
pinning the block with `^name`. An identical block inserted before a block takes its number.

### Keyed rows

A row of a register or of a Base view is a record, not a node, and its key is the record's id: its
id is `<table id>:<record id>`, the table's node id and the Document record's id
([[#Registers]]).

A register's rows are the records the core selected; a Base fence's rows are selected by the
adapter, so any record of the Document is a row of it. A Markdown table has no key column; its
rows are table-row nodes with derived ids.

## Reviewed copy

Explicitly enabled property editors modify a canonical note's designated frontmatter
field in the artifact's in-memory model, not a second finding/explanation data store.
Source vault files remain unchanged. Only fields explicitly declared editable by the
authored artifact contract may be changed; imported evidence, identifiers and derived
results are not implicitly editable.

A `property-editor` fence contains `version: 1`, `field`, and `label`, plus an optional
positive `maxLength` (default and bound owned by its schema).

An optional static `projection` mapping declares `blank` and `nonblank` maps of top-level frontmatter
fields to safe primitive values. Which fields it may write is owned by
[[capabilities/property-editors#Projection rules]].

After validating the entire mapping, a committed edit selects `blank` for trimmed empty text
and `nonblank` otherwise, then atomically commits the text and selected values. The mapping is
data only: no callback, expression, formula, domain switch or authored script runs in the
artifact. The source-owned model precomputes both outcomes.

A property editor opts one existing top-level string property of that canonical note into
plain-text editing, including empty strings.

Generated Home and presentation-semantic properties are not editable, whether directly or
through a derived projection. [[capabilities/property-editors#Projection rules]] owns that
constraint for the edited field and a projection; at the runtime transaction boundary the adapter
writes only the fields the editor's node declares ([[capabilities/property-editors#Document node]]).

A reviewed copy's comments and review decisions have the core's format and meaning
([[#Comments and reviews]]). How an adapter saves a reviewed copy, with its reader state, and how
its runtime commits an edit, is that adapter's; its specification is listed in
[[appendix/references|References]].

## Comments and reviews

Decided by the owner, 9 Nov 2026 (work issue `feat/core-comment-review-format-20261109`):
comments are how information flows back from any output to the vault, so their format and the
meaning of a review are the core's, once, and every adapter maps onto them.

### Overlay files

A principal's comments and review decisions live in one overlay file next to the manifest:
`<manifest stem>.comments.<principal>.json` (for `manifest.md` and the principal `alice`,
`manifest.comments.alice.json`). A principal is lower-case letters, digits and hyphens, starting
with a letter or digit.

The core discovers every overlay file of the manifest when it builds the Document; a file whose
name matches the pattern but names no valid principal is an input error. A principal writes only
its own file: a reply goes into the responder's file, not the file of the comment it answers.

`src/obs/comments.schema.json` owns the file's fields, once, for the adapters that write it and
the core that reads it (version 1):

- `version`: `1`. `principal`: the file name's principal.
- `comments`: comments, threads and annotations. Each has an immutable `id` (any text without
  whitespace, unique across all overlay files of the manifest), an `author`, its `created` time and
  an optional `modified` time (RFC 3339), a `body` (`mediaType` `text/plain` or `text/markdown`,
  and its `text`) and a `state`, `open` or `resolved`.

  A thread's root names its `target`; a reply names the comment it answers, in any file, as
  `inReplyTo` and has no target of its own (it is its root's). An annotation is a comment whose
  target marks text: an exact `quote` with optional `prefix` and `suffix`, and optional `start`
  and `end` positions in the target's text.

  A root may carry a `batch`: the `scope` of a decision made on many items at once (`section`,
  `chapter` or `document`) and the `items` (targets) it was made on.
- `decisions`: review decisions. Each has an immutable `id`, a `reviewer`, its `created` time, a
  `target` and a `state`, `accepted` or `rejected`.

A target is the document (`{}`), a chapter (`chapter`, its Document id) or a node (`chapter`
and `node`). A node is a block node's id or a keyed row's ([[#Block node ids]]).

### Review semantics

- An item, a node or a chapter, is waiting for a reviewer while the reviewer has no decision on
  it; a reviewer has at most one decision per target. Changing a decision changes the reviewer's
  own decision; withdrawing it removes the decision, so the item waits again.
- Decisions belong to their reviewer: one reviewer's decision never changes another's.
- An item's aggregate state is rejected if any reviewer rejected it, otherwise accepted if any
  reviewer accepted it, otherwise waiting.
- A batch decision is one decision per item it covers, made only on items still waiting for that
  reviewer; its comment keeps the batch's scope and items.

`src/obs/comments.py` (`review_state`) owns this computation for every adapter.

### Union and resolution

The core reads the overlay files in file-name order and forms their union by id:

- An id in several files with the same payload is one entry. An id with different payloads is an
  input error naming both files and the field path of each (`comments[0]`).
- Two decisions of one reviewer on one target, in one file or two, are an input error naming both.
- A reply's `inReplyTo` resolves across files; one naming no comment, or a chain of replies that
  reaches no root, is an input error naming the file and the field path (`comments[1].inReplyTo`).
- A target resolves through the Document: its chapter must be one of the Document's chapters and
  its node an id in that chapter.
- A target that does not resolve is no error, since comments outlive the text they were made on.
  The Document carries a warning that names the overlay file, the field path
  (`comments[0].target.node`), the comment or decision id, the missing target and this section.

The union is the Document's `comments`: the `version`, the overlay `files` by name, and the
`comments` and `decisions`, each ordered by `created` time, then id. A Document built without
overlay files has none. A file the schema refuses is an input error naming the file and the
field path.

### Adapter contract

Every adapter receives the same resolved model, the Document's `comments`, and keeps no private
interchange format. An adapter contributes only a thin mapping:

- **Export:** it renders the Document's `comments` in its own output, as its native comments and
  review controls, with the review semantics above.
- **Import:** it turns the native comments and decisions a reader returns into the overlay file
  of that reader's principal, which `obs.comments.validate_overlay` checks before it is written.

Each adapter's specification documents its mapping and links here for the format and the meaning.

## One count query

- A document counts records one way: the record-metric `where` conditions with optional
  `distinct` and `denominator` (see [Document home and abstract](#document-home-and-abstract)).
  A cards metric evaluates it directly; a quantity note's `query` uses the same form and is
  referenced from prose or by a metric's `from`/`secondary`. Both share one evaluator.
- A count on Home is a `cards` fence in the manifest abstract. Its metric `link` names the
  table that lists the counted items; the drill-down filter derives from the metric's
  conditions ([[capabilities/cards-metrics#Drill-downs]]).
- Manifest `summaries` (Bases-filter counts over projected table rows) were removed
  (4 Nov 2026). The manifest rejects the key with a migration message; there is no fallback.
  For example, the spec counts open points with `where: [{field: mark.open_point, exists: true}]`
  and `distinct: mark.open_point`; marker identities are unique, so this equals the open-point
  rows of the Tags table.

## Next Obsidian extension

Evaluate native Bases summaries/formulas, note embeds, and diagrams against
a side-by-side migration of an existing artifact before choosing the next extension. The source is
the original artifact folder; preserve its original artifact and calculation scripts.

Authorized editorial changes belong in the canonical Markdown, not hardcoded adapter summaries.
The side-by-side migration preserves engineering statements and values without rerunning models.

Open points and glossary entries become canonical notes queried by ordinary tables, with stable
links to the same records. Existing answers do not imply closure: no status is inferred.
Compare source/query semantics, counts, drill-down links, figures and PDF before choosing full
native Bases/formula parity.

Inline/display TeX and standard pipe tables are presentation inputs;
they do not execute calculations. Local image assets are embedded rather than left as paths.
Image paths must remain inside the vault and identify PNG, JPEG, GIF, WebP or SVG files;
missing or unsupported local images fail validation.

Base64 PDF/plain-text/JSON/binary
attachment links are allowed; this does not enable raw HTML or HTML/script data URLs.

Math is rendered as static MathML without remote scripts. Display math written inside a paragraph
(`Text $$a^2$$ text`) stays inside that paragraph, as in Obsidian.

Ordinary Markdown citations such
as `[[1]](references.md#ref-1)` are links with bracketed labels, not nested wikilinks.

Keep the parity decision open rather than approximating unsupported syntax silently.

Authored Important callouts identify key takeaways and linked subtitle figures orient readers;
their presentation is the adapter's. Build-comparison provenance remains outside the artifact.

The side-by-side edition keeps the original's open points, glossary entries, references and
referenced figures, using shared query tables and a linked count.

Linked local source files follow the attachment rule (the side-by-side edition builds
without `--embed-attachments` and keeps provenance text); source directories are explicit
snapshots, and links that resolve only on the author's machine remain provenance text.

Figure numbers and cross-references
use block ids with chapter numbering; expanded images zoom and pan. Compare native PDF appearance separately;
DOM tests establish behavior, not visual parity. These findings belong to this remaining
extension decision, not additional open-point markers.

Choose the next Obsidian extension after comparing native Bases formulas/summaries, note
embeds and diagrams against the side-by-side artifact (embedded `.base` files are owned by
[[#Base files and members]]). Preserve unsupported syntax
as an explicit limitation rather than silently approximating it.
#mark/open_point/next_obsidian_extension

See [[product]], [[architecture]], and [[cli]].
