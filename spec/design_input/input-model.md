# Input model

[[capability-reference|Capability reference]] owns the supported capability identifiers,
their dependencies, summaries, and authoring examples. This note owns the corresponding
input semantics.

## Trusted presentation projections

Trusted application runtimes may save a named selection through
`obsReport.setViewSelection(key, selected, choices)` and read it through
`viewSelection(key)`.

Values are unique strings from the supplied finite choices; they live in
`readerState.views`, not canonical notes, filter expressions or record
stores. Unknown/stale saved choices are rejected by the application against its
current catalog.

`obsFigures.setProjection(sourceNote, graph)` supplies a transient graph through the
same dynamic Sankey renderer and canonical record predicates as the authored
`sourceNote`.

`obsCards.setProjection(key, fieldsBySourcePath)` supplies transient field
predicates for a declared metric key, not precomputed numeric values. Its
counts still use the shared aggregate evaluator over filtered canonical records.
Neither API commits canonical data; removing a projection restores canonical fields.

A trusted runtime may likewise project a table's visible columns from its saved view
selection by dispatching `obs-table-set-columns` on the table host. That projection is
derived view state: it becomes the table's current default and is not itself saved table
presentation or a changed-HTML state.

Only explicit reader column or width changes that differ from the current projection are
retained as reader state, so reopening and
re-projecting a saved selection starts unchanged.

HTML-style Markdown authoring comments (`<!-- ... -->`), including multiline comments,
are non-rendered source annotations. They contribute no visible prose, links, semantic
marks, table definitions, or paragraph diagnostics. Preserve the surrounding content and
source locations; comment-like text inside fenced or inline code remains literal code.

This applies to chapter bodies and the manifest abstract, not to review-comment data.

The source resolves to one manifest note inside an Obsidian-compatible vault. Source selection
and runtime defaults are owned by [[cli]] and [[configuration]], respectively.
[[manifest]] selects and orders that design vault.

## Manifest contract

- The manifest consists of optional document frontmatter, one nested bulleted TOC list of
  links, and optional abstract Markdown after that list. Numeric TOC markers and prose before
  the TOC are not permitted. Once the TOC ends, subsequent Markdown belongs to the abstract,
  including any lists in that content.
- A manifest that does not start with a bulleted list has no TOC (worker decision, 4 Nov 2026,
  for the one-pager): all its Markdown is the abstract and the document is Home alone, with no
  chapters and no previous/next steps. A leading numbered list is still a misplaced TOC and an
  error.
- Every list item is exactly one local Markdown link or Obsidian wikilink to a note.
- Top-level items are chapters; nested items are subchapters of their parent.
- The sequence in which items appear in the source is authoritative at every nesting depth.
  Previous and next navigation follows that sequence in depth-first order.
- Only notes listed in the manifest become authored report chapters. Links in chapter content
  or the abstract do not implicitly add chapters to the TOC.
- Duplicate, unresolved, external, and non-Markdown manifest links are errors.
- The manifest owns document metadata, authored navigation, and abstract prose. It is not
  additionally rendered as an ordinary chapter.

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

Metrics select canonical report records with the same exact-equality/presence predicates
as Sankey projections. A metric
counts selected records or distinct values of a declared field; an optional denominator
selects the population for a percentage. Empty denominators display `-`. All selectors
compose with the report-wide filter, never table-local filters.

An optional metric `link` is an internal fragment using the existing chapter/heading
route syntax; a
`tableFilter` query value applies the existing filter to the table named by a table-group
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
inside the hover card. A direct external link in authored prose is a lint warning and still
follows the new-tab rule above until migrated.

Internal report navigation and explicit download/save actions retain their
existing same-report or download behavior.
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
not silently discarded prose. This is report layout syntax, not source-authored HTML
or CSS; its paged/mobile presentation is owned by [[report-ui]].

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

Input evidence can be far larger than the document, so embedding is decided twice
(user, 4 Nov 2026):

- Per link, with Obsidian's own syntax: `[[file.xlsx]]` and `[label](file.xlsx)` only link;
  `![[file.xlsx]]` and `![label](file.xlsx)` mark the file for embedding.
- Per build, with the CLI flag `--embed-attachments`: only then are marked files embedded as
  downloads, preserving the filename. Without the flag, a marked file renders like a link.

Unmarked links are never embedded. There is no manifest setting for this.

A wikilink target with a file extension other than `.md` (and `.base`, which names a register)
is a vault file. It resolves like a note name: next to the linking note, then from the vault
root, then by its case-insensitive file name, which must be unique in the vault. A marked image
(`![[figure.png]]`, `![label](figure.png)`) is document content as above, not an attachment.

PDF uses its media type (and `report.embedPdfs: false` still links PDFs locally instead) and other
binary/source
files use octet-stream, never an executable HTML/script media type. This keeps supplied
evidence out of authored data URLs. Images are document content, not linked sources, and
are always embedded.

Sankey links may represent individual canonical records rather than aggregated pairs.

An optional `series` identity associates adjacent segments, and `originColor` preserves a
second categorical meaning without changing their value. Node `records` predicates and
an optional `unique` field derive filtered record/distinct-value labels from canonical
records; they never execute report-owned algorithms in the converter.

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
  that output and its timestamp. Each committed canonical change in the HTML (for example
  an evidence replacement or a description edit) sets it to the time of that change, and a saved
  HTML keeps that time. A change that returns the content to its state when opened or
  when last saved restores that state's timestamp, so reverting an edit is not a change.

  Reader state (filters, view selections, columns) and review
  comments are not content changes and leave it unchanged.
  Structured values are human text, never JSON: one `key: value` pair per line with the
  values aligned in one column, for example:

  ```text
  name:    obs-html
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
  no renderer supplies missing tables or sections. Which front pages exist, their order and
  titles are declared by the document presentation profile below; their paged rendering and
  Contents are owned by [[report-ui]].

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

A manifest or vault can define further profiles. The presentation keys below are today's
single, implicit profile. First one-pager pieces (4 Nov 2026): a manifest without a TOC (Home
alone) and `heading: compact` in the presentation profile below.

### Document presentation profile

Author presentation decisions live in the manifest frontmatter's reserved `obsHtml`
mapping, the same namespace that notes and Bases fences use for obs-html-only options.

Obsidian keeps it as ordinary frontmatter, so the author edits it in Properties or source.
The packaged `note-profile.schema.json` constrains it and owns the defaults; the converter
contains no front-page titles, labels or opening mode of its own.

```yaml
obsHtml:
  layout: paged              # or scrolling
  heading: cover             # or compact
  pages:
    - {page: cover}
    - {page: abstract, title: Abstract}
    - {page: contents, title: Contents}
  figures: {numbering: none, label: Figure}
  print: {paper: A4, margin: 20mm}
  cssSnippets: [house-style] # .obsidian/snippets/house-style.css
```

- `layout` chooses the view every opening starts in: `paged` (paper sheets) or `scrolling`
  (continuous reading). Readers can still switch during the session; that choice is not saved
  as the next opening's state. It replaces the removed `report.reading.paged` setting.
- `heading` presents the cover metadata at the top of Home. `cover` (default) is the title box,
  which `pages` can also place as the title sheet. `compact` is one line: organization, product
  name and version, document type and title (subtitle last), separated by `·`; the other cover
  fields (template, people, SAP number, legal entity, copyright, confidentiality) are not shown.
  The compact line is never a sheet of its own: in the paged and PDF projections it opens the
  first declared front page, so `pages` must declare at least one page and no `cover`.
- `pages` is the ordered list of generated front pages of the paged and PDF projections.
  Each kind (`cover`, `abstract`, `contents`) appears at most once.
  - `cover` is the title sheet built from the cover metadata. It has no `title`; its heading is
    the document title.
  - `abstract` places the abstract Markdown: its lead sheet followed by one page group per
    top-level second-level heading. The optional plain-text `title` becomes the lead sheet's
    heading and running-header section; without it the lead sheet has no generated heading.
    A manifest whose abstract contains Markdown must declare `abstract`; authored prose is
    never silently dropped from the PDF.
  - `contents` is the generated chapter list with measured page numbers; the optional
    plain-text `title` is its heading.
  - An omitted kind produces no page. `pages: []` is valid for a manifest without abstract
    Markdown.
- `figures` numbers captioned `figure` fences. `numbering` is `none` (default), `document`
  (`Figure 1`, `Figure 2`, … in contents order) or `chapter` (`Figure <n>.<m>`, where `<n>` is the
  top-level contents position of the chapter, its subchapters included, and `<m>` counts within
  it). `label` is the plain-text word before the number (default `Figure`, for example `Abb.`);
  `labelPlural` precedes merged references (default `Figures`).

  The number precedes the first caption paragraph; uncaptioned figures and notes outside the
  contents (record notes, reproduction copies) are not numbered. Authors never type numbers.
- `print` sets the paper of the paged and PDF projections: `paper` is a portrait paper name
  from configuration's `report.print.paperSizes` and `margin` the margin
  on every side in millimetres (`20mm`). Omitted keys use the defaults; configuration owns the
  margin limits. It replaces the removed project `report.paper` setting.
- `cssSnippets` lists CSS snippet names, without `.css`, from the vault's snippet folder
  (configuration's `input.cssSnippetFolder`, Obsidian's `.obsidian/snippets` by default).

  The HTML embeds them in list order after its own styles, so they style screen, pages and
  PDF and win at equal specificity. Obsidian's own enabled-snippet list is a per-device
  appearance choice and is not read: the document declares what it needs.

  A listed snippet that is missing, or that contains `</style`, is an input error. The
  default is none.
- Generated abstract sections are [register](#registers) embeds in the abstract Markdown.
- Vaults that declare none of these keys keep the packaged defaults shown above, which reproduce
  the established cover, "Abstract", "Contents", and paged opening.

  The default is compatibility: an existing vault keeps its document unchanged until its author
  decides otherwise. Attachments are not a profile key; see the attachment rule under
  [Document home and abstract](#document-home-and-abstract).
- The profile is presentation configuration, not document metadata: it is neither a Document
  metadata row nor shown in Home's frontmatter.

  On an ordinary note (for example a copied manifest inside a reproduction folder) the
  document-level keys are inert; only the selected
  manifest's profile applies.

### Registers

Decided by the user, 4 Nov 2026 (`spec/backlog/review-macro-syntax.md`). Generated registers
are Obsidian Bases views in `.base` files of the vault ([[generic-tables]] owns the embed),
embedded where they appear: glossary, references, numeric values, mark registers such as
open points and document metadata.

`obsHtml.macros` is rejected with a migration message; the spec vault's `registers.base` is
the starter.

```markdown
<!-- open-points.md, listed in the manifest TOC like any chapter -->
Optional authored introduction.

![[registers.base#Open points]]
```

- A vault may keep all its registers as views of one `.base` file, so they are easy to find.
  `![[file.base#View]]` embeds one view; `![[file.base]]` embeds all views with a selector.
- Registers are a superset of Bases. Each view is valid Bases YAML that Obsidian renders as a
  plain table of notes. Keys under `obsHtml:`, which Obsidian ignores, make obs_html render
  the rich register, for example one row per marked paragraph instead of one per note.
- The view's own filter is the fallback and must select something sensible in Obsidian: notes
  with the mark tag, notes with `kind: glossary`, notes with a `url`, numeric-value notes.
- Filters, columns, titles and grouping are authored in the view. obs_html owns no default
  columns or filters for registers; the spec vault's `.base` file is the documented starter.
- Rows that are not notes (marked paragraphs, glossary terms, chapters with a callout,
  document metadata) come from the shared record projections, selected by the view's
  `obsHtml.records`; a base-level `obsHtml.records` is the default for all its views.
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
- Rendering the `obsHtml` keys inside Obsidian itself (a plugin) is a possible later step, not
  planned.

## Report behavior

- Generation produces exactly one HTML file containing the report shell and all chapters.
- `report.dataCompression` selects `gzip` (the default) or `none` for canonical
  report-data transport. Gzip uses one base64-encoded island; a plain JSON island
  remains valid and may be used when compression would increase the encoded size.

  This changes storage, not note/query/review semantics or the original downloaded
  evidence bytes. Both formats are self-contained and use one decoding owner.
  Unsupported decoding or malformed payloads produce a visible initialization
  error, not an apparently successful empty report.

  All dependent runtimes wait for validated decoding. Save reviewed HTML encodes
  a consistent snapshot of the current canonical model and reader/review state,
  keeps it compressed, and removes disposable materialized views rather than
  embedding another raw model. Async compression must not lose file-picker user
  activation, clear unsaved state after failed writes, or mark later edits saved.

  Reopen, read-only extraction and source reproduction use the same format contract.
  The island retains its `report-data` identity. During opening its decoded JSON
  replaces the encoded text in memory; saving replaces that disposable projection
  with exactly one encoded current snapshot. Plain transport remains readable
  without browser compression support.

  Gzip requires native stream decompression; unavailable support is an explicit
  opening error, never a network fallback.
  A save captures model, review and dirty baseline together before awaiting work.
  Only a successfully closed file may advance that captured baseline; a download
  cannot confirm completion, and edits arriving later remain unsaved.
- The authored chapter order follows the manifest; presentation of headings is owned by
  [[report-ui]].
- Exactly one chapter or subchapter is visible at a time.
- The active chapter has its own scroll range; content never continues into the next one.
- Left and right controls move through all items in depth-first manifest order.
- Selecting a table-of-contents item or changing chapters resets content scroll to the top.
- Stable URL fragments identify chapters so browser history and direct links work.
- Home is always a reachable navigation destination, including when a filter leaves
  one or no matching authored chapters. Previous/next, breadcrumb/Home and both
  sidebar/document contents derive from the same retained navigation sequence.

  A still-visible active chapter cannot be stranded outside that sequence.
  Reports may explicitly scope their global query to record data rather than
  authored chapters; that scope preserves chapter navigation and PDF chapter inclusion.
  The ordinary report's chapter-filter behavior remains the default.
- The manifest frontmatter's `obsHtml.query` owns the optional global query profile
  (schema: `note-profile.schema.json`); project configuration rejects a `report.query`.

  Instead of the profile, the manifest may name one internal note link, such as an
  adapter's generated configuration note, whose own `obsHtml.query` holds the profile.

  `scope` is `chapters` (default) or `records`. In record scope, optional `where`
  selects the count/facet population using the same exact, AND-combined record conditions
  as dynamic figures. It does not remove authored chapters or document/PDF sections.

  Optional `fields` is a curated discoverable catalog of `{field, source?, label?}`:
  `field` is the query alias, `label` defaults to that alias, and `source` defaults to
  `field`, or is a nonempty array of source paths whose scalar values are unioned.

  Source paths address canonical fields and may follow a canonical internal note reference
  prefix into the target's remaining metadata path, including arrays of references.

  For example, `roles.origin.item.disciplines` follows `roles.origin` to its canonical
  note, then reads `item.disciplines`; target metadata is never copied into path notes.
  Alias values are derived again after canonical edits, never serialized as another dataset.

  An explicit catalog limits discoverable fields but does not bypass the ordinary
  discriminative-facet rule: constants, single-value fields and near-unique fields
  are not attribute pills. The default distinct-value upper fraction is one half
  of the applicable population, owned by configuration/schema.

  Text and identifiers remain directly queryable even when not offered as facets. Raw
  metadata remains
  queryable without becoming discoverable noise.
  Example: `{"scope":"records","where":[{"field":"kind","equals":"path"}],
  "fields":[{"field":"discipline","source":["roles.origin.item.disciplines",
  "roles.destination.item.disciplines"],"label":"Discipline"}]}`.
- Styles, scripts, and local assets are embedded so the HTML file is portable.
  Reports may opt into version-pinned, integrity-checked CDN delivery of Plotly through
  `report.figures.plotlyDelivery: cdn`; the default `embedded` preserves offline graph
  interaction.

  CDN-backed Plotly plots do not embed a duplicate static image; printing uses an on-demand SVG of
  the interactive graph, not a stored fallback. CDN failure displays an explicit
  interaction-unavailable notice. Local attachments are unaffected.

  `report.embedPdfs` defaults to `true`. Setting it to `false` leaves PDF links pointing
  to the local source files instead of embedding their bytes; those PDFs do not travel
  with the standalone HTML. Other attachment types are unaffected.

### Optional reproduction archive

An explicitly requested reproduction archive captures the selected vault and generator inputs.
CLI invocation and prerequisites are owned by [[cli]]; controls and PDF presentation by
[[report-ui]]. The source boundary is defined here.

It discloses the selected vault's explicit directory snapshot, including scripts/data not
in the TOC, whether or not that vault has Git metadata. Installed dependency directories,
Python environments identified by `pyvenv.cfg`, Python caches, generated
`data_output`/`design_output` and compiled executables are excluded.

Generic names such as `output`, `outputs`, `build` or `cache` do not establish that a declared
source is disposable.
Dot folders such as `.obsidian` stay excluded, except the CSS snippets the manifest lists:
they are declared inputs of the document.
Extracted source archives carry a source inventory so rebuilding without `.git` preserves
the same selection.
Their build configuration is a complete, schema-valid configuration of the original
build's settings, including `input.styleFolder`, so a rebuild from the extracted archive
validates.

Symlinks are rejected, never followed outside that boundary.

The generator's package source,
project manifest, uv lockfile, README and platform bootstrap wrappers accompany
the vault snapshot.

Implementation-source selection follows the owning Git-tracked source tree and any explicitly
included new implementation files, schemas, and other source resources needed by this build,
not a recursive copy of the checkout.

Do not collect build products, environments, installed dependencies, caches, unrelated binaries,
other project inputs or worker state. A selected external/non-Git vault remains supported;
its declared source boundary must not be silently reduced to visible chapters alone.

Original attachments have one embedded payload owner shared by reader downloads and source
reproduction. Source packaging must not embed another full copy of those bytes.

Compression or references are packaging only: downloaded evidence is byte-identical to the
supplied original,
and the downloaded ZIP remains a complete, ordinary reproducible archive. Missing or corrupt
payloads produce explicit errors rather than incomplete successful downloads.

With source embedding, reader assets use `obs-asset:` references into a descriptor map.
Each descriptor declares `archivePath`, `mime` and original-byte `sha256`; its owning ZIP
member is stored once with ZIP deflate compression.

The download remains that complete ZIP, not a thin archive requiring sidecars. Browsers
hydrate references with native decompression
and digest validation to local Blob URLs; reviewed-save retains descriptors and the ZIP,
not those process-local URLs.

Missing members, unsupported/encrypted compression, malformed ZIP metadata and digest
mismatches fail explicitly. This transport changes no authored
input semantics and does not make archived originals the authority for edited model state.

The embedded ZIP is a generic compressed source store, not an adapter-specific attachment
mechanism. Its central directory owns member paths and sizes; do not serialize another file
inventory or raw/base64 member bodies into the reader.

The complete ordinary ZIP can be downloaded for source/configuration authoring outside the
HTML. There is no source-file
browser or configuration editor in the reader or Settings.

Explicit attachment links can download one selected member after local decompression and
integrity validation through the same generic owner. Individual downloads preserve the
original bytes and basename; source/script files are downloads, not executable previews.
A missing or corrupt selected member fails explicitly, without a successful empty download.

An adapter-supported input refresh must not require downloading or extracting this archive.
The reader parses a newly selected input and calculates from current canonical records.

On successful replacement, the canonical update and the changed owning archive entry must
be committed at one revision; old unreferenced bytes and decoded URL caches are superseded,
not retained as a second payload. Cancellation or failure preserves the previous revision.

Saving/reopening the HTML must retain that same current owner and permit another update.
Compressed storage is not a reason to require a source-archive authoring workflow.

Effective configuration and a rebuild script accompany the sources; bundle instructions give
explicit vault/settings paths for the wrappers rather than using the checkout's default spec.

The generator checkout must be available; an incomplete archive is an error.

Hidden files, external absolute-path dependencies and OS/Python executables are not collected.
Non-hidden source files are included without secret detection; authors must inspect the archive
before distributing it.

Command authorization is recorded but rerunning commands still requires an explicit
rebuild flag. uv/Python and downloadable locked dependencies remain prerequisites; this is a
source reproduction bundle, not an offline VM or a promise of byte-identical timestamps.

Network resources and external tools are not made offline by this flag.

Never execute embedded files automatically.

## Cover metadata and history

The manifest optionally supplies nonempty plain-text `document type`, `organization`, `template`,
`sap number`, `copyright`, `confidentiality`, and `legal entity` fields.

Optional `product` is a mapping containing
`name` and optionally `version`, both nonempty strings.

Optional `authors`, `reviewers`, and
`approvers` accept a nonempty string or list of nonempty strings.

These values populate the cover;
empty strings, nulls and empty lists/mappings are treated as unassigned and omitted.

Empty product
members are omitted as well.

They are not proof of approval or legal status.

Title/subtitle and
cover fields are excluded from the residual Key / Value table to avoid repeating their presentation.

The organization remains manifest-owned even though its value is displayed on the cover and
page frame rather than repeated in that table.

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

Revision labels and dates appear in History, not on the cover.

Both normal HTML
and document/PDF views render the same canonical history through the shared query-table engine
(`obsHtml.records: documentHistory`, columns `version`, `date`, `author`, `change`).

History is not repeated as raw JSON in metadata.

In document view it occupies its own section
after the abstract and before Contents; normal Home displays it after the abstract.

Generation time remains separate from document revision dates.

## Chapter content

- The manifest is the inclusion root.

  Its TOC targets, abstract and metadata links seed inclusion;
  links and table-query matches from included notes add their source notes recursively until
  no new notes are reached.

  Queries may inspect the vault's Markdown metadata index, but only
  matched/referenced notes enter the canonical report store.

  Unreferenced notes stay out.

  Links are wikilinks and embeds in body text (not in code) and in frontmatter string
  values. A `base` fence (also inside a `cards` body) or an embedded `.base` file selects
  the notes whose record matches its `filters` and any view's `filters`.

  A frontmatter `query`, and a cards metric, selects the notes whose record has every
  `where` condition (`equals` an exact text value or a list holding it; `exists` a nonblank
  value), narrowed by its `from` owner's selection; the `from` and `secondary` owner notes
  are included too. Each note is included once, so cycles end.

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
- Optional note frontmatter `obsHtml: {document: false}` declares a canonical record-only
  projection. `document` is boolean and defaults to true; the reserved mapping is constrained
  by `note-profile.schema.json`.

  Record-only notes remain queryable and available to figures and explicit canonical
  reference/detail tabs, but do not appear in generic Search, chapter activation or
  standalone technical note details. A link to one shows its
  [[report-ui#Link hover card|hover card]] and, when clicked, the note in the
  [[report-ui#Floating window|floating window]] (reference notes, decided 29 Oct 2026).

  A record-only manifest or authored TOC target is an input error, not a silently dropped
  chapter. Direct browser
  document fragments targeting a record-only note return to Home. Ordinary source attachment
  links and explicitly declared subject tabs retain their behavior. Producers opt into this
  distinction through data, never inferred note kinds or generator-specific filenames.

  Clicking a document link to an unlisted note shows it in the floating window; the page stays.
  A direct browser fragment still opens an unlisted note in the same reader with a Home
  breadcrumb and browser history. Unlisted notes never become TOC children or previous/next
  chapter stops.
- Standard Markdown is supported before optional Obsidian extensions.
- `[[wikilinks]]` resolve by source-relative path, vault-relative path, unique note name, and
  then alias. Relative Markdown note links use the same canonical targets. Nested note links
  and note-heading fragments are resolvable; ambiguous note references fail generation
  explicitly. Link examples inside code remain literal.

  A link's `attrs.chapter` names the chapter of its target; a link to the manifest names
  `home`, which no chapter identifier takes. Name lookup skips the manifest. `null` remains
  only for a target that does not exist; the build then warns, naming the source note, the
  target and the remedy (decided 5 Nov 2026).
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
- Each type declares its HTML presentation (rail icon as today's marks, box, collapsed box or
  inline badge); nothing is inferred from content. In Markdown a callout is always a block.
- Registers, cards, hover cards and profiles select callouts by type from the shared record
  projections. In Obsidian, Bases views of them fall back to note lists.

Obsidian is the reference syntax. A blockquote is a callout when the first line of its
first paragraph is `[!type]`, optionally followed directly by a fold marker `+` or `-`
and then by a space and an inline-Markdown title: `> [!warning]- Check the limits`.
The type is case-insensitive. Later lines of the blockquote, including nested blocks and
callouts, are the callout body. Presentation follows [[report-ui]].

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
- `important` keeps its established obs_html meaning: an untitled emphasis box for key
  takeaways, not Obsidian's alias of `tip`. An authored title is still shown.
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
into prose. HTML renders that link as the canonical value followed by its unit, retaining
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
not report-specific counters or a second canonical dataset. Calculated display
values are derived view state, not authored values, review edits or dirty-state
changes. Print, previews and reviewed-copy reopening resolve them from the
current query/filter state.

Merely switching an unrelated detail tab must not recompute every aggregate.
Implicit query references carry only `data-quantity-reference` naming the owning
canonical source path, not a copied query, count or canonical dataset. Materialized
references, previews and print clones reuse cached values until canonical/filter
changes invalidate them.

The note owns its display unit; every implicit reference uses that same unit. Use micrometres
for comparable node-flatness and small tolerance quantities, with exact conversion from
millimetres and no change to physical meaning. Other dimensions keep appropriate consistent
units. Do not merge unrelated quantities merely to normalize units.

The Node side-by-side migration applies this ownership across current report prose, tables,
callouts and captions. Preserve relations, ranges, signs, datums and engineering
qualifications; move value-specific provenance and discussion to the corresponding note.

Identifiers (drawing, reference, chapter, figure, open-point and model names), dates,
enumeration and algebraic constants are not engineering-quantity references. Static figure
pixels, source drawings, archived historical drafts and executable model inputs are not
rewritten or recalculated.

Existing model inputs remain authoritative for model-owned
quantities; derive their report notes from those inputs instead of hand-copying new defaults.

#### Numeric direction (decided 29 Oct 2026, not yet implemented)

Which numbers become notes is an author's judgment. A number with a meaning (an upper limit,
a requirement, a measured property) becomes a numeric-value note. A number that is obvious from
structure ("three points" above a three-item list) or that goes stale (one test run's duration)
is not written at all.

Range, tolerance and vector are numeric types, not separate concepts. Their parts are typed
frontmatter fields of the one note, and the unlabelled link renders all of them.

A derived value records its provenance in one of three ways: prose in the note, a stored
command that reproduces it, or a stored query over the document's own records.

Everything a query computes runs live in the HTML, so a reader's change updates it at once.
Values from external systems or heavy analysis are computed offline and stay plain data.
There is no hard border: analytic equations with numbers plugged in should run live, and
work that is too heavy for the browser runs offline.

Numeric notes will carry a unit system, so values of the same physical quantity convert
between units and can be added or subtracted across units. Tolerance stack-up is a candidate
to move live. The equation system itself is designed separately
(`spec/backlog/nodes-numeric-system.md`).

### Reference notes and link text

Decided 29 Oct 2026, implemented 4 Nov 2026 (`spec/backlog/reference-items.md`).

A note with a `url` field is the reference to that external thing, whatever its kind. It may
also hold internal content: a `description`, details and records. Each external thing has
exactly one such note, however often it is linked.

Every document link to something external targets that note, never the URL. Systems of record
are not exempt: Catalog and Catalog items link to their internal record notes.

- A click goes to the note. A note with a place in the table of contents navigates as usual. A
  note without one opens in the [[report-ui#Floating window|floating window]] and the page
  stays put.
- A hover shows a card with the note's `description` and its external link
  ([[report-ui#Link hover card|hover card]]).
- A bare URL in authored prose, and a table `linkProperty` to an external URL, are lint
  warnings.
- The references register is a query over notes with a `url`, not a maintained list.

Link text: the text written in the link wins. An unlabelled link renders by the target's kind:
a numeric-value note shows its value and unit (and range or tolerance once typed), and any other
note shows its title. There is no placeholder syntax such as `$value` in link text.
"Unlabelled" means a wikilink without `|label`: `[[alias]]` and `[[note-name]]` show the
target's title, not the alias or file name written; a Markdown link always has its own text.
Heading and block links keep their existing labels.

The lint runs with the paragraph warnings on every build (stderr, never in the HTML): a
Markdown link, autolink or bare `http(s)` URL in a note body (code excluded), and a base
`linkProperty` whose path, or its last segment, holds an external URL (plain or as a Markdown
link) in any included note.

### Remaining chapter content

#### Figure input direction

Ordinary plots are authored as Markdown fences containing equations and plot details, not
custom generator code per report.

The Node report's ordinary plots use this path. Its complex geometry figures may remain
report-owned Python scripts
that provide figure data and subplot composition to generic infrastructure. Report-specific
equations, geometry and engineering logic stay outside the converter.

`figure` fences contain a YAML mapping with `version: 1`, `kind: plot`, `kind: svg`, or
`kind: sankey`, and `source` (a vault-relative JSON artifact). An optional `caption`
supplies visible figure prose; omission renders no caption or placeholder. Plot and SVG
figures also declare `fallback` (vault-relative SVG).

Paths are relative to the note, confined to the vault, and artifacts are read-only
inputs. Rendering/checking never runs
producers. Existing explicit command authorization remains unchanged. Authored SVG is
embedded as an image, never executable inline markup.

At the core boundary, a generated figure is a versioned JSON FigureDescriptor. It
carries neutral data, an ordered panel list, and provenance; it does not carry rendered
markup, stylesheet values, or a browser payload.

Each panel has viewport bounds and grid placement. Its axes declare their scale, numeric
limits, and labels. Provenance records the producer command as ordered strings and may
record stable fingerprints for its input artifacts. The descriptor schema is the
executable owner of this shape; adapters choose their own rendering from it.

#### Figure descriptor

The FigureDescriptor has `schemaVersion: 1`, a stable `id`, an object-valued `data`
payload, one or more panels, and provenance. A panel has a stable `id`, numeric
`bounds` (`x`, `y`, positive `width`, and positive `height`), and a non-negative
`grid` row/column with positive spans.

It has one or more axes. Every axis has a stable `id`, `linear` or `log` scale, numeric
`minimum` and `maximum` limits, and a text label. Provenance has a nonempty ordered
command array and can list input artifact IDs with stable fingerprints.

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
are build errors. Numbering itself is the manifest's `obsHtml.figures` decision
([Document presentation profile](#document-presentation-profile)).

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
  from the packaged list; `obsHtml.figures.labelPlural` names the plural (default `Figures`).

Implementation decisions, same date:

- The figure lint shares the paragraph-warning path: every build and `--check` print one
  source-located stderr warning per finding; none changes the HTML. An image alone in its
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

Confirmed defaults, same date:

- Numbering stays off unless the manifest sets it (documents opt in, nodes sets `chapter`):
  a document without numbering renders unchanged, and numbers belong to documents whose
  figures are all captioned and referenced by block links.
- CDN-delivered Plotly stays opt-in and shows an explicit notice when the network fails:
  the embedded default keeps one HTML file interactive offline, so only an author who
  accepts the network dependency trades size for it, and a reader never sees a silent gap.
- The Sankey option keeps the name `countLabels`: it says what it configures, the words shown
  with record counts, and renaming would only move every author's fence without new meaning.

For `plot`, `domain: [minimum, maximum]`, `samples` (2–2000), ordered `equations`,
`traces`, and `layout` are authored in the fence. Source JSON binds named finite numbers
or arrays.

Equations are a bounded arithmetic expression language, not Python execution: numeric
literals, names, `+ - * / **`, unary signs, and calls to `sqrt`, `exp`, `log`,
`sf` (standard-normal survival), `sum`, `mean`, and `prod` only. Arrays broadcast against
scalars; array pairs require identical length.

`x` is the sampled coordinate. Each ordered equation binds one name; source names cannot be
overwritten. Attributes, indexing,
comprehensions, strings, keywords, arbitrary calls, and nonfinite results are errors.
Plot traces name equations and a primary/secondary y axis, color, dash and label.

Optional `at` coordinates (a numeric array or exported array name) sample the same equations
for markers without duplicating report calculations. `mode`, `marker` and `legend` control
their presentation.
Layout declares titles, limits, linear/log axes and legend. No executable strings are
passed to the browser. Print always uses the complete report-owned default SVG.

For `svg`, source JSON has `version: 1` and `panels`: each panel declares `id`, `title`,
and `box: [x, y, width, height]` in SVG viewBox coordinates. Optional grid/span/aspect/axis
metadata documents the producer's composition. The complete exact SVG remains the default
and print view; an inspector selects a panel for independent uniform vector viewport
zoom, pan and reset.

This is viewport inspection, not data reflow or recalculation. Producers retain responsibility
for engineering geometry, subplot placement, annotation,
hatching and provenance. Interaction and visual-parity requirements belong to [[report-ui]].

Python-generated figures follow one producer convention: the report-owned script writes the
exact `<name>.svg` and its `<name>.figure.json` panel sidecar side by side (an ordinary plot
writes `<name>.parameters.json` for its fence's equations, plus its SVG `fallback`).

The author places, captions, numbers and references the figure only through the Markdown fence;
the
generator and project adapters add nothing. Panel boxes are in SVG viewBox units.

For `sankey`, source JSON has `version: 1`, `nodes`, and `links`. Each node has a unique
nonempty `id`, display `label`, and integer `stage` from 0 through 15; each link names existing
`source` and `target` node ids and a finite positive `value`.

Optional node/link `color` values are six-digit hex colors; a link may also carry a display `label`.
Ordinary flow
links must move to a strictly later stage. At least two nodes and one link are required. Unknown fields,
duplicate ids, missing endpoints, nonfinite or nonpositive values, and graphs above 256
nodes, 1024 links, or 4 MiB of source JSON are errors.

An optional `data` mapping makes a Sankey a dynamic projection of canonical report records.

It has a nonempty `where` list; every condition names a canonical record field and has either
`exists: true` or an exact string `equals` value. A dynamic link has its own nonempty `where`
list with the same condition shape. Each canonical record matching `data.where`, the current
report-wide filter, and a link's conditions contributes one unit to that link.

The authored positive `value` is the portable unfiltered and print default. Generic browser
infrastructure
recomputes link weights and layout from the same canonical records when the report filter
changes. The query-table filter remains table-local and does not alter the diagram.

Dynamic Sankey projections omit zero-population nodes, their inactive links and labels
without deleting the authored alternatives from the canonical figure definition.
Declarative placement can put intermediate sinks above or below the main flow;
the report owner supplies placement, not domain-specific inference in the converter.

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

Node membership is the union of incident links' conditions, restricted by `data.where`;
a strand uses its own conditions restricted by that population. Equality clauses are
anchored exact values, not substring matches; existence requires a nonempty value.
Dynamic node counts use that same visible incident-link union.

An optional link `unique` names a canonical field containing its distinct target-item
identities.
A shared sink unions those values only from matching active incoming contributions,
so hiding a contributing level cannot retain that level's item counts. Without
incoming contribution fields, the node's existing `unique` field remains the default.

A counted node shows two lines below its label: `<n> <unit>` and `<n> <unique>`. The fence's
optional `countLabels: {unit: <noun>, unique: <word>}` names them; the neutral defaults are
`records` and `unique`. Domain vocabulary is authored in the
fence, never built into the converter.

Accessible names fall back to `alt`, the rendered caption text, `source` and finally `Figure`.
Producers must declare link predicates at canonical path granularity, not broaden a
strand to all paths sharing an originating item. A selected expression replaces the
global Filter expression and opens that input; there is no second selection state.

The converter renders the bounded declarative graph as a self-contained SVG; it does not
infer domain meaning, execute code, fetch assets, or copy source records into the graph.

The report owner defines node labels, stages, record predicates and the unfiltered value
derived from its canonical model. Rendering, record selection, report-filter integration
and SVG layout are generic. Conditions are data-only field checks, not query strings or
executable expressions. See [[report-ui]] for diagram interaction and print behavior.

### Markdown body and frontmatter

- Relative Markdown links and local images must stay within the source vault.
- The Markdown body is the complete source of rendered prose content.
- Converter paragraph diagnostics measure authored prose with the supported Markdown dialect,
  before render-time decoration, and retain its source location. Home diagnostics measure only
  the authored abstract, not generated content or metadata. Reusing a parsed body must not let
  rendering mutate the tokens consumed by diagnostics or subsequent renders.
- Optional YAML frontmatter must be a mapping with string keys. Its values are normalized
  to JSON-compatible scalars, lists, and mappings for the canonical report store.
- Frontmatter is never rendered verbatim as body text and cannot inject styles.

  Obsidian's `cssclasses` (one class name or a list of them) is the note's styling hook: the
  names are validated CSS class identifiers and are projected onto that note's rendered
  container, as [[report-ui]] places it. Styles come only from the CSS snippets the manifest
  lists (see [Document presentation profile](#document-presentation-profile)); obs-html gives the
  classes no meaning of its own.

- Every frontmatter field is available to the shared query language. Nested mapping fields
  use dotted names, quoted field names address spaces,
  and bare queries search both field names and values. Within quoted query values, `\"`
  and `\\` escape a literal quote and backslash.
- The reader may expose frontmatter as derived metadata outside the Markdown body.

### Mark tags

Replaced by callout types (user, 4 Nov 2026; see [Callouts](#callouts)); this section describes
the current implementation until that migration lands.

Mark tags classify a paragraph as an open point, risk, warning, decision or another fixed kind.
This section owns their syntax and records. Their icon rail and optional box are owned by
[[report-ui#Content sections]] (box opt-in per kind: `report.borderedTags` in `cfg.json`), and
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
- The Node report uses these marked paragraphs in their owning authored chapters instead of
  a separately maintained numbered open-point register or synthetic open-point notes. Preserve
  the question, decision impact, actions, existing answers, evidence and unresolved
  qualifications together in the owning marked paragraph so all appear in its generated
  overview row.

  Concision must not separate substantive content from the point; an answer alone does not
  imply closure. Replace legacy register links with links to the owning marked
  paragraphs. Counts and overview tables query the canonical marks, never a parallel dataset.

### Base fences

- A fenced block with info string `base` is declarative table content embedded in an ordinary note.

  This is the general authoring contract for report data tables, not a Node-only adapter.
  The owning Markdown declares each table's query, placement, columns and view options;
  supported card bodies and the manifest abstract use the same fenced syntax.
  Removing, moving or changing a fence removes, moves or changes that table.

  Neither a chapter name nor application code may silently append or reinstate a report
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

  The bridge translates those declarations; it does not invent report semantics. Supported
  standard syntax retains its Obsidian
  meaning. Unsupported syntax fails explicitly, never falling back to an application-specific
  interpretation. Report-only extensions must not redefine standard Bases fields.

  Home has no implicit tables. Its tables are ordinary fences in the manifest
  abstract (the maintained `spec/manifest.md` is an example). History and residual
  metadata headings are authored too. This intentionally replaces the former
  invisible Home defaults: migrating an existing manifest is an additive source
  change, never a renderer fallback.

  A Base normally evaluates canonical note rows once, as native Bases does.
  `obsHtml.records` explicitly selects a report-only row projection: `note`, `chapter`,
  `tag`, `glossary`, `documentHistory` or `documentMetadata`. A `note` projection adds
  the report's own note fields to the canonical note rows (see [[generic-tables]]).

  A filter comparison on a bare `recordType` is rejected with a migration message naming
  `obsHtml.records`. View filters intersect global Base filters during discovery and rendering.

  Filter syntax and comparison semantics are owned by the Bases filter grammar in
  [[generic-tables]]. The separate report UI's notion of an assigned
  value is not a redefinition of standard Base equality.
  Standard views have at most one `groupBy` property; multi-property sorting is
  supported, but multi-property grouping is not reinterpreted as native syntax.
  Native note columns and predicates read actual frontmatter and supported `file`
  properties, not report-synthesized chapter/title/discriminator fields.

  Data-dependent columns are opt-in presentation, not a domain query compiler.

  `obsHtml.expandProperties` maps an ordered property to
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
  claim. A card may declare `obsHtml.metricsFrom` with `sourceNote`, `property`,
  `labelProperty`, `distinctProperty` and an ordinary count `where`. Each object
  in that canonical data list supplies a label and the field whose distinct
  values are counted.

  The declaration, not the data producer, owns this query and whether/where
  these metrics exist. Optional `link: {note, groupProperty}`
  routes the label to that authored note's matching table group without a
  generated table ordinal; `tone`/`toneRules` use the existing metric contracts.

  This is a typed presentation projection, not string interpolation, arbitrary
  template syntax, a new predicate evaluator or a numeric/formula engine.

  An authored metric's `obsHtml.projection` selects an opaque trusted
  application-provided field projection. A Base's `obsHtml.viewProjection`
  similarly opts into an application presentation; optional `fallbackColumns`
  declares its all-hidden column view. These declarations do not grant trust.

  Applications may only narrow the authored result rows or project its columns,
  never replace or resurrect its query/composition. Removed opt-ins receive no
  application presentation. Generated table ordinals are not application APIs.

  Authored Node report tables use these queries, never pipe-delimited Markdown tables.
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
  the Bases filter grammar in [[generic-tables]].
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

  Report-only additions live under
  a top-level `obsHtml` mapping so normal Bases syntax remains portable and can expand independently.

  For a view whose membership or order cannot be expressed by canonical note properties,
  `obsHtml.members` is an ordered list of `{path, label?}` entries. `path` is a unique,
  vault-relative Markdown filename; `label` is optional view-local display text, exposed only
  as the derived `obsHtml.label` cell.

  The list never writes membership, rank, or labels into a note. It intersects the standard
  Base filter and initializes row order; interactive filters
  and sorting remain table-local. Every path must resolve to a file inside the vault, or
  `--check` fails. Notes matching a Base query are included even without prose backlinks.

  `obsHtml.maxRows` is an optional positive integer specifying the approximate number of
  ordinary body rows in the table's vertical viewport. It constrains visual height only;
  page size, filtering, grouping, sorting, and row membership remain independent. Omission
  preserves the unbounded current table presentation, and invalid values or unsupported
  `obsHtml` properties fail validation.
- Notes containing base fences remain ordinary manifest chapters: authored prose before and after a
  fence renders normally, and manifest position alone determines chapter hierarchy and navigation.

### Glossary

- Glossary tables consume canonical glossary records rather than inferring definitions from rendered
  prose. Each concept has one canonical glossary record regardless of its aliases.

  Glossary-note discovery supplies these records rather than maintaining hardcoded definitions.
- Glossary notes declare `kind: glossary`, a nonempty `term`, and a nonempty inline
  Markdown `definition` in frontmatter. Their definitions and aliases feed the canonical record,
  and glossary tables link terms to their source note.

## Command-derived content

- A fenced block with the info string `cmd` is derived content rather than prose.
- When command execution is authorized for a build, the fence body runs from the vault
  root and its captured output replaces the source fence in the report.
- A `cmd silent` fence is a producer: on an authorized build, all producers run from
  the vault root in path and source order before the vault is read for conversion.
  It renders no command output. Its files are ordinary vault inputs, so an unauthorized
  build and `--check` use only artifacts already on disk.
- Command output is HTML-escaped and rendered as preformatted content; it cannot inject
  report markup or styles.
- A timeout or nonzero exit fails generation so stale or partial reference output is not
  published.
- Builds never execute command fences without explicit authorization because a vault may
  contain arbitrary commands.
- The CLI note uses this extension to embed help from the executable that owns it.

## Reviewed copy

Explicitly enabled property editors modify a canonical note's designated frontmatter
field in the report's in-memory model, not a second finding/explanation data store.
Source vault files remain unchanged. Only fields explicitly declared editable by the
authored report contract may be changed; imported evidence, identifiers and derived
results are not implicitly editable.

The initial use is a text explanation for a finding. Edits must update dependent views
and survive standalone HTML download and reopen,
together with existing review comments and decisions. Serialize the current canonical
data safely, without stale duplicate values, executable input or copied transient DOM.

This extends the existing reviewed-copy export rather than adding a competing saver.
The concrete editor declaration and validation belong to the implementation ticket.

The canonical reviewed-copy model also saves the last successfully applied global filter
expression as finite reader state, separate from notes and review annotations.
Reopening compiles that expression through the shared query runtime and restores the actual
Filter input and open bar. Empty or closed filters reopen unfiltered with the bar closed.

Invalid input drafts never replace the last valid expression in saved state.
If a stored expression cannot compile, show it and its error in the open Filter bar rather
than silently discarding it. Fresh generation remains unfiltered; appearance always starts
Light with Pages. Reader state is excluded from semantic review-dirty comparisons.

An absent trusted view selection means an empty selection. Registering that empty
default does not add a persisted override or mark newly opened HTML as changed.

Returning to an implicit empty default removes its override; explicitly saved
selections retain their loaded baseline. Initialization must not rebase genuine
reader or canonical edits made while other startup work is still finishing.

Reviewed reader state also retains visible column keys in display order, keyed by the
table's stable identity. Resized column widths are session-only view state, never reader
state or a document change.

The table owner validates and rebuilds these settings against its current column catalog;
saved rows or rendered DOM
are not a second data source. Invalid settings show a table diagnostic, not silent success.

Fresh reports keep authored defaults. Table-local filter, grouping, sorting, pagination,
expansion and edited base definitions remain session-only in this bounded contract.

A `property-editor` fence contains `version: 1`, `field`, and `label`, plus an optional
positive `maxLength` (default and bound owned by its schema).

An optional static `projection` mapping declares `blank` and `nonblank` maps of top-level frontmatter
fields to safe primitive values. Projection keys cannot name the edited field; values must
match the existing field types, and arrays must be flat and homogeneous.

After validating the entire mapping, a committed edit selects `blank` for trimmed empty text
and `nonblank` otherwise, then atomically commits the text and selected values. The mapping is
data only: no callback, expression, formula, domain switch or authored script runs in the
report. The source-owned model precomputes both outcomes.

A property editor opts one existing top-level string property of that canonical note into
plain-text editing, including empty strings.

Generated Home and presentation-semantic properties are not editable, whether directly or
through a derived projection. The editor
schema owns the shared protected-field constraint, applied case-insensitively at generation
and at the runtime transaction boundary.

Enter or leaving the editor commits text; query fields and metadata caches are refreshed.
Saved copies replace the report data island from the canonical model, not rendered inputs.
Markdown and HTML are never interpreted in
edited text; stale per-property rendered metadata is invalidated.

The runtime applies an edit and its selected projection as one transaction. It validates all
target notes and fields, checks values against the existing field types, and rebuilds every
affected query record before changing canonical data.

Only then are all notes and records updated together, table caches invalidated, one
canonical-change notification emitted, and
the active report filter reapplied once.

Object values, nested arrays, undeclared fields, note creation/deletion, and HTML or figure
mutation are rejected. Projections serialize in the same reviewed-copy model as property edits.

The browser treats review annotations, per-reviewer decisions, and changes committed
through these canonical property editors as unsaved reviewed-copy state.

A report opened from a generated or reviewed HTML file starts clean. A semantic change marks it dirty;
reverting all changes to the loaded state clears that state. Viewing, filtering,
navigation, presentation changes, and edits that do not change a canonical value do not
make semantic review state dirty.

Persisted reader-state changes do, however, make the HTML document unsaved relative to its captured saved snapshot. The
shared
changed-HTML notice and unload confirmation use this document-level comparison;
transient navigation, hover and nonserialized presentation remain excluded.

The comparison also covers the current embedded source archive, when present,
through its existing archive owner rather than a second serialized payload.
Importing reviewed copies marks it dirty only when the merged comments,
reviewers, or decisions change.

A successful File System Access write establishes the new clean baseline; opening the save picker, cancelling it, or a
failed write does not. A browser's standard download API
provides no signal that the user accepted, completed, or retained the downloaded file, so
initiating a download does not establish a clean baseline.

The page remains dirty after download initiation; reopening the downloaded report starts a new clean baseline. On unload,
unsaved document state requests the browser's native confirmation without relying on custom text.
The Comments bar persistently explains how to save and that leaving with dirty or
unconfirmed changes risks losing them.

- A reviewed copy is a generated standalone HTML report whose one `obs-comments` JSON island
  contains versioned annotations and per-reviewer block decisions created through the
  Comments bar.

  New comment targets may additionally retain their canonical review-item identifier,
  section label, and whether the context was the whole item. These optional descriptive
  fields survive save/reopen and import without changing version 2 or the canonical text
  and table anchors.

  They are descriptive, not part of merge identity: their absence in legacy copies does not
  duplicate an otherwise identical comment. Legacy targets remain valid;
  clipboard export explicitly reports
  unavailable context rather than inventing missing identities or page numbers.
- Review checklist items are derived in document order from rendered list items, table data
  rows, standalone code blocks, figures, and paragraphs that are not inside
  one of those units.

  A paragraph or code block inside another review unit does not create a
  duplicate item.

  Markdown images remain part of their containing paragraph; standalone media
  may use a figure item.

  Visual line wrapping never creates another item.
- Rendered headings may receive exact-text comments but are not checklist items and carry no
  Accept or Reject decision.
- Ordinary review item identifiers are chapter-local deterministic ordinals; generated table
  rows use their table/row keys so reordering does not change review identity.
  Like text anchors, they are not re-anchored across regenerated reports.
- Reviewer identities are stored with the reviewed copy even when that reviewer has not made a
  decision. Missing decisions are waiting. An item's displayed state is aggregated across known
  reviewers with precedence rejected, then accepted, then waiting: any rejection wins, otherwise
  any acceptance overrides missing decisions.
- The named reviewer's state is derived across every chapter and exposed to the browser query
  model as the `review` field. Aggregate worst state remains a display property of each item;
  neither derived state is persisted as a second copy of reviewer decisions.
- Batch decisions use the same per-reviewer item decisions as individual actions, never
  a parallel acceptance state store. A batch rejection may have one scoped annotation
  associated with the exact affected stable item identities. Preserve those associations
  safely in reviewed-copy serialization, merge and extraction; existing annotations
  remain compatible.

  The gesture and waiting-only scope are owned by [[report-ui]]. Version 2 annotations
  optionally carry `batch: {scope, items}`. `scope` is
  `section`, `chapter`, or `document`; `items` is a nonempty, duplicate-free array
  of `{chapter, item}` review identities. This is an annotation association, not a
  second decision store. Extraction retains the scope and exact identities.
- Comment extraction accepts the returned HTML as untrusted data, requires exactly one valid
  island, and never executes or imports the report's scripts, markup, or comments.
- Extraction produces a deterministic text list for human or agent triage. It does not edit
  the returned copy, source Markdown, or project configuration.

## One count query

- A document counts records one way: the record-metric `where` conditions with optional
  `distinct` and `denominator` (see [Document home and abstract](#document-home-and-abstract)).
  A cards metric evaluates it directly; a quantity note's `query` uses the same form and is
  referenced from prose or by a metric's `from`/`secondary`. Both share one evaluator.
- A count on Home is a `cards` fence in the manifest abstract. Its metric `link` may carry
  `?tableFilter=` to drill into the table that lists the counted items.
- Manifest `summaries` (Bases-filter counts over projected table rows) were removed
  (4 Nov 2026). The manifest rejects the key with a migration message; there is no fallback.
  For example, the spec counts open points with `where: [{field: mark.open_point, exists: true}]`
  and `distinct: mark.open_point`; marker identities are unique, so this equals the open-point
  rows of the Tags table.

## Next Obsidian extension

Evaluate native Bases summaries/formulas, note embeds, and diagrams against
a side-by-side Leaves report migration before choosing the next extension. The source is
the original report folder; preserve its original report and calculation scripts.

Authorized editorial changes belong in the canonical Markdown, not hardcoded adapter summaries.
The side-by-side adapter stages normalized notes in `.obs-html/vault` and writes
`report-obs-html.html`. It preserves engineering statements and values without rerunning models.

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

Math is rendered as static MathML without remote scripts.

Ordinary Markdown citations such
as `[[1]](references.md#ref-1)` are links with bracketed labels, not nested wikilinks.

Keep the parity decision open rather than approximating unsupported syntax silently.

Reader presentation follows [[report-ui]]: authored Important callouts identify key takeaways,
linked subtitle figures orient readers. Build-comparison provenance remains outside the report.

The side-by-side edition now has the original 25 open points, 23 glossary entries,
24 references and 12 referenced figures. It uses shared query tables and a linked count.

Linked local source files follow the attachment rule (the Node edition builds without
`--embed-attachments` and keeps provenance text); source directories are explicit snapshots and
machine-specific knowledge-base links remain provenance text.

Figure numbers and cross-references
use block ids with `obsHtml.figures.numbering: chapter`; expanded images zoom and pan. Compare native PDF appearance separately;
DOM tests establish behavior, not visual parity. These findings belong to this remaining
extension decision, not additional open-point markers.

Choose the next Obsidian extension after comparing native Bases formulas/summaries, note
embeds and diagrams against the side-by-side report (embedded `.base` files are owned by
[[generic-tables]]). Preserve unsupported syntax
as an explicit limitation rather than silently approximating it.
#mark/open_point/next_obsidian_extension

See [[product]], [[architecture]], [[report-ui]], and [[cli]].

## Canonical reference presentation

### Named icon resources

Icons are one projection of the shared [[semantic-assets]] index, not a separate
catalog or glyph/drawing map in behavior code. That owner specifies typed assets,
named references, nested inheritance, state defaults, semantic colors, confined
file dependencies and validation. Its generic `report.assetIndex` replaces the
unreleased icon-only configuration proposal.

File-resource coloration and its bounded monochrome opt-in follow that same
owner; Base references use its shared semantic-identifier profile.

Existing Obsidian Base declarations reference semantic identifiers through
`obsHtml.icon.name` and composed `obsHtml.icons[*].name`. Identifiers are not
restricted to today's built-in icon-name enum. A report author can change the
catalog or select another named resource without editing application code.

Do not introduce a separate inline-Markdown dialect for this change; ordinary
file-image references retain their existing resource semantics.

Asset appearance never selects an action, navigation target, download mode,
accessible label or permission. Those remain explicit properties of the
existing control/action declaration. Link-backed icon declarations may explicitly
request `download: true` or `false`.

Preserve the legacy `snapshot` link slot's download behavior when that field is
omitted, normalize this compatibility at
the input boundary, and use an explicit download declaration in maintained
adapter output. Changing or overriding its glyph must not change its behavior.

The existing action owner supplies active/inactive or other declared state to
that resolver; state selection does not duplicate action or record semantics.
Typography/layout and application of the resolved colors remain stylesheet
responsibilities. Resource ownership and source reproduction follow [[semantic-assets]].

Base property declarations may add `obsHtml.reference: {label: [item.id, item.name]}`.

The ordered field names are resolved on the existing linked canonical note, not on the
referencing row. `file.name` denotes its source filename stem and `title` its subject title.
The input remains an ordinary wiki/Markdown link or list of links; presentation never
copies target records into relation rows.

Optional `reference.metadata: [item]` selects canonical metadata fields/subtrees
by prefix, preserving the target's field order and displaying labels relative to
the selected subtree. The default retains all ordinary note metadata; projections
may exclude transport/query wrappers without runtime knowledge of those wrappers.

`properties.<field>.obsHtml.detail: true` makes that reference eligible for the explicitly
declared `views[0].obsHtml.details: columns` mode. Missing references are empty, not
synthetic subject documents. Existing `displayName` labels apply to group captions too.

`views[0].obsHtml.wide: true` marks table composition only; [[report-ui]] owns orientation.

Icon slots use `properties.<slot>.obsHtml.icon` with a catalog resource `name`
and accessible `label`, plus one of `linkProperty` with `unavailable`,
`action: sourceArchive`, a fixed action ID registered by the explicitly selected
trusted runtime (with `unavailable` when its `card` declares a `link`, see
[Trusted floating-content actions](#trusted-floating-content-actions)), `help`
(plain text), or `unavailable` alone.

`helpProperty` may replace static help text with the canonical row's field,
using its existing trusted rich-metadata projection rather than flattening
formatted values or links to plain text. Optional `help` appends a shared
plain-text explanation. Presentation reuses the shared rich-hover owner defined
in [[report-ui]], not a separately styled instruction popup.

Help alone remains informational;
an action ID selects an existing handler, never an authored callback.
Compact slot width is owned by `report.tableIconWidthPixels`
in the shared configuration/schema.

Link properties consume existing safe rendered links, sourceArchive consumes the
existing original-source download owner, and unavailable slots remain explicitly disabled.
An authored action ID never grants runtime registration or script trust.
Default appearances, including unavailable slots, are owned by the icon catalog,
not this contract or an action-name switch.

An unavailable slot retains its explicit reason and disabled state when its appearance is
overridden.
Tooltips identify the operation as well as any row-specific instructions.
An import/replacement icon is not a claim that the browser reproduces an external
export. Icon changes preserve the same trusted action and shared rich-hover help.

### Compact declarative table presentation

A view may explicitly disable pagination (including its item totals/footer), request
equal initial widths for its displayed subject columns, and select a smaller point
size for expanded subject details. These are schema-validated `obsHtml` view options;
omitting them preserves the existing table defaults.

Shared bounds/defaults belong in configuration and its schema, not duplicated
constants.
The declarations are `pagination: false`, `columnSizing: equal`, and
`detailFontSize: 10` (points) under the view's `obsHtml` mapping.
One final labelled property may compose several existing icon actions in a compact
cell; it retains each action's accessibility and unavailable state.

This is data-only composition of existing actions, not executable authored content.
Its `obsHtml.icons` array contains existing icon declarations; singular `icon`
remains supported. They are alternative declarations for the same property.
Canonical reference metadata selection supports a human-facing ordered allowlist
without copying the selected values into relation notes.

Missing fields are omitted; safe URLs remain links and rendered descriptions are not
repeated as raw HTML.
Blank strings, nulls and empty collections are also omitted from detail metadata;
false and zero remain meaningful values.
Record-backed tables can use the existing report query catalog for field discovery
when it describes the same population; other tables retain their own field scopes.

An explicitly empty property `displayName` suppresses its visible header text while
retaining an accessible field label. It does not erase the field identity or its values.
`showEmptyDetailTabs: true` under the view's `obsHtml` preserves every displayed
detail-subject column as a tab; tabs without permitted content are visibly disabled
and cannot be activated.

The omitted/default setting retains the existing omission behavior for other reports.
`screenPageBreaks: false` under the view's `obsHtml` keeps the current table page,
including expanded details, together on one variable-height HTML sheet. This is a
screen pagination hint, not text `nowrap` or a change to row pagination. PDF retains
normal physical-paper splitting and repeated headers.

`compact: true` opts into shared compact table sizing: tightly measured composed
icon slots/header controls and the configured compact minimum text-column width.
It does not suppress overflow or remove controls; ordinary tables retain their
configured ordinary minimum. Both minima are schema-bounded shared configuration.

An opt-in `properties.<field>.obsHtml.editable: true` uses the canonical note's
already-declared property editor directly in the table cell. The owning editable
property, validation/projection and save lifecycle remain authoritative; a table
does not create another editable value or trigger downloads on edits.

`editor: singleLine` alongside `editable: true` requests a one-line text input.
An existing multiline canonical value is preserved on untouched focus/blur;
only an actual edit commits the input's one-line text through the existing owner.
`singleLine: true` on a reference property requests an ellipsized one-line cell label, with
the complete text retained as its accessible text and hover title.

`properties.<field>.obsHtml.leadingLines: [otherField, ...]` composes a plain cell:
each listed property of the same row renders as its own line, in order, before the
property's own value.

A missing, null, blank or empty leading value renders no line, so rows without it show no
empty first line. The leading properties remain ordinary
row properties; the column keeps its own field identity for sorting, filtering and
property editors, and canonical values are never concatenated or rewritten.

It is presentation only, shared by screen, static and printed tables, and applies to
plain and `linkProperty` values. Combining it with `icon`, `icons`, `reference` or
`editable` is rejected. Example: `description: {obsHtml: {leadingLines: [evidenceDate]}}`
shows the evidence date above its description.

An optional `reference.linkProperty` resolves a safe source URL on the referenced
record for its displayed label. Explicit subject-tab activation still selects
the tab; the identifier inside that subject uses the source URL. Raw identity
fields remain unchanged. `obsHtml.linkProperty` on an ordinary property similarly
links its label through another field on the same record.

Decided 29 Oct 2026: a `linkProperty` that resolves to an external URL is replaced
by linking the record's own note, which carries the `url`
([[#Reference notes and link text|reference notes]]). The URL then appears only in the hover card. Until
migrated, such a `linkProperty` is a lint warning.

An optional `reference.metadataFormats` mapping gives displayed metadata fields
an explicit `format` (`html` or `table`) and an optional raw `source` field path.
Missing raw sources retain the original plain value; canonical fields are never
rewritten by formatting. HTML is parsed inertly and copied through a finite
passive-element/attribute allowlist.

Sole entity-escaped markup may be decoded through its bounded HTML/XML layers; ordinary
percentages and prose are not
percent-decoded. A table source is the existing data-only `{headers, rows}` shape,
with scalar cells; its markup-valued cells use the same safe HTML formatter.
Empty structured tables are omitted rather than replaced by flattened schema text.

Imported image references use explicit non-fetching placeholders. Only absolute
HTTP(S) and mail links remain active; relative source links are not guessed
against the generated report's location.
Formatting is shared by initial, filtered, printed and canonically refreshed
subject details and must not add another query or canonical data owner.

Table `obs-table-set-row-keys` presentation events may restrict a mounted view to
known row identities (or reset with null); this independent presentation scope
intersects, never replaces, its authored and interactive queries. Static exports
inherit the same scope without altering canonical records.

## Shared source-archive link

The authored Markdown link target `obs-source:archive` invokes the same current
archive-download action as the cover and Settings/exports controls; it never
addresses a second archive or a separately cached copy. The source owner resolves
the current bytes at activation, including after a committed evidence replacement.

When the initial build omits the archive, generated report guidance must not claim
that a complete source ZIP is available or expose a broken download. A later
partial evidence archive retains its truthful partial label.

## Trusted runtime and canonical replacement

The builder alone may select one regular vault-local JavaScript bundle with
`--trusted-runtime-bundle ID=PATH`. Markdown, Base definitions, metadata, ordinary
assets and uploaded evidence never authorize executable code.

The bundle registers its selected ID and unique fixed actions before
`obs-html-ready`; missing, malformed,
duplicate and mismatched registration fails visibly. Authored action declarations
are data, not callbacks. Source reproduction records the original explicit selection
in its rebuild command; it does not infer trust from the extracted manifest.

`obsReport.stageCanonicalTransaction({expectedRevision, notes, assetChanges,
sourceChanges})` stages a detached complete canonical-note candidate and its single
owning ZIP. The framework validates safe content, identities, attachment references
and confined source changes before returning a revision-checked commit handle.

The commit updates notes, archive and descriptors together, invalidates derived views
and emits one canonical change. Parsing, source projection, compression, validation,
cancellation or revision failure leaves the prior state unchanged. This does not
relax the narrower existing-field property-editor contract.

Runtime text uses text nodes and allowlisted semantic content, never uploaded HTML
assigned as executable markup. Selected action handlers report synchronous throws and
asynchronous rejection through the same visible application error notice.

Dynamic Sankey fences may declare `sourceNote`, an exact extensionless vault-relative
Markdown identity whose `frontmatter.graph` supplies current graph data.

The collector includes that confined dependency even without a navigation/link
reference. Manifest
`canonicalNotes` selects other exact canonical dependencies. These declarations select
data only, never scripts; traversal, missing files, duplicate declarations, aliases and
slug guesses are not dependency identities.

### Trusted floating-content actions

Builder-selected trusted actions may use a shared framework floating-content host;
its presentation and browser fallbacks belong to [[report-ui]]. This is a reusable
host for safe content and controls, not a new authored scripting language, form DSL,
workflow engine or parallel canonical store.

Markdown still selects registered action IDs and owns instructions, source links and
content-aware composition. Uploaded files,
ordinary metadata and Base declarations do not gain permission to execute rendering code.

A Base action icon may add `card` to turn its activation into a guided action card
instead of an immediate file picker. The declaration contains only bindings to the
row's existing canonical fields and fixed labels:

required `title` and `submit` (the Apply label), optional `subject` (field shown as the card
subject), `content` (fields rendered as rich instructions through the shared rich-metadata
owner), `link` (field whose safe rendered links open the source in a new tab), and
`input: {property, label}` (one required, nonblank text value prefilled from that
field).

Unknown keys are rejected. The card shows the source link first, above the
subject and instructions, because the reader opens the source before following them.

A declared `link` is a precondition of the card: a row whose `link` field renders no
safe link gets no card, and its action slot is disabled (not dispatched) with the
icon's authored `unavailable` reason, like other unavailable slots. An action icon
whose card declares `link` therefore requires `unavailable`.

The author decides which rows qualify through the row data and this declaration; the
generator does not recognise particular rows. Choosing or dropping a file only stages it.
Apply passes `{noteId, file, values, signal, report}` to the same registered
action handler; `values` contains only the declared input property. The handler,
not the card, validates and commits.

Actions without `card` keep the existing file-picker behavior.
`obsReport.openFloatingWindow({use, title, mount, returnFocus})`
shows trusted content in the document's one [[report-ui#Floating window|floating window]];
`use` names the header ("Evidence collection" for guided action cards).
`mount(container, session)` mounts trusted controls once and the session exposes `active`,
`mode`, an abort `signal` and idempotent `close()`, which removes that content from the
window's history (closing the window when nothing else is left).

A floating action's draft remains transient until explicit submission. File bytes
and required accompanying metadata are validated and staged through the existing
revision-checked canonical transaction, then committed together.

Failure, cancellation or stale revision leaves the previous canonical model and
archive
unchanged. Closing a card must not allow pending asynchronous work to commit later.
Successful submission uses the existing canonical-change and unsaved-HTML owners.
Do not serialize helper windows, draft files or a second copy of evidence payloads.

### Current source projection after a trusted update

A complete source archive must rebuild the updated canonical result, not an earlier
normalized vault. The trusted adapter stages its current generated Markdown and
original-input filename mappings together with the evidence replacement.

The generic transaction validates vault-local source changes, preserves unrelated
members, updates
the source inventory and commits all bytes at the same checked canonical revision.

Source Markdown contains ordinary local attachment paths, never process-local Blob URLs.
An archive first created by upload without initial sources remains a partial evidence
archive; it must not acquire complete-source instructions or claims.
