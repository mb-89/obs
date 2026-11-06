---
summary: Python owns source semantics and emits one canonical artifact store; browser views derive from that store.
---

# Architecture

The system is a Python package managed and executed by `uv`.

## Flow

1. Load cross-project configuration, then the selected vault's optional project configuration,
   and resolve CLI runtime paths.
2. Resolve a source folder to its conventional manifest note, or accept an explicit note.
3. The core parses the selected manifest into a schema-valid JSON [[quality#Glossary|Document]] with document metadata, an ordered chapter tree, semantic Markdown nodes, links, and assets.
4. The core resolves every manifest link within the containing vault and validates frontmatter and supported input syntax.
5. Adapters project the Document into their output formats, each an [[quality#Glossary|artifact]]; integrated adapters live under `adapters/` ([Repository layout](#repository-layout)).
6. Resolve authorized derived-content providers, including command fences; in a core build the
   core runs them while it builds the Document ([Command output](#command-output)).
7. Resolve content links and assets within the vault boundary.
8. Render one self-contained artifact.

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

## Repository layout

The core and its adapters are one repository. The core is `src/obs`; an integrated adapter is
a folder under `adapters/`, the first in `adapters/html`. Whether a later adapter
lives here or in its own repository is decided when it comes.

An adapter folder is a member of the root uv workspace. It keeps its own `pyproject.toml`,
package, tests, browser tests, `spec/` and `adapter.json`, and depends on the core through a
workspace path dependency, so a core change and its adapter change land in one commit and
there is no pin between them. The root `adapters.json` registers each adapter by the path of
its `adapter.json`. Each part tests only itself; `uv run python test/suite.py` runs every
part's suite in its own pytest process.

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
Its `records` are owned by [[capabilities/bases#Note records|Note records]].
Its `manifest.path` is the manifest note's vault-relative path, so an adapter's message about the
manifest names that note, as one about a chapter names the chapter's note.

An adapter never parses Markdown: what the author wrote arrives as nodes, metadata values
included ([[capabilities/markdown#Document nodes]],
[[capabilities/markdown-frontmatter#Document node]]).

The boundary has no Python types, package entry points, application names, or
output-format terms. An implementation may change language without changing either
JSON contract.

### Adapter call

The core starts an adapter as its manifest's `command` followed by the Document's path, the
destination, the standard arguments and the arguments of the options the call passes: an option
exists only where the manifest's `options` declare it, and each kind of option has one form on the
command line ([[cli#Adapter options]]). The core never names an adapter or one of its options.

The one standard argument is `--vault-root ROOT`, which every adapter accepts. Where the core built
the Document from a manifest, ROOT is the manifest's folder as the user gave it (`spec` for
`--source spec/manifest.md`), and the adapter names each vault-relative path in its messages below
it, so they read `spec/manifest.md: …`. ROOT is for messages only: the Document stays
machine-independent and never carries it, and neither does the artifact. Without the argument, on
a direct adapter call on a Document, messages name paths relative to the vault.

### Asset bytes

The Document embeds the bytes of every vault file it references as an image or a
marked attachment ([[capabilities/attachments#Document node]],
[[capabilities/embeds#Document node]]), so an adapter renders from the Document alone
and never reads the vault. Each such file is one `assets` entry, however often it is
referenced, carrying its vault-relative `path` and its bytes as base64 `data`.

Embedding was chosen over an asset root the adapter may read: an asset root ties the
adapter to the source machine's vault, while the artifact must open on another
machine without it ([[product#Goals]]). The Document therefore stays one
self-contained file.

An asset whose `href` has a URL scheme is not a vault file and carries no `path`. A
remote image carries the `data` the build fetched, so the Document stays self-contained
([[input-model#Document home and abstract|remote images]]); one the build could not fetch,
and any other URL, carries no `data`. Whether an artifact embeds a marked attachment
stays the adapter's per-build decision ([[input-model]], `--embed-attachments`).

### Command output

The core runs command fences; an adapter never does. `obs-document --source <manifest>
--execute-commands` is a build's one authorization: producers run before conversion and each
other fence's captured output goes into its node ([[capabilities/command-fences]]), so the
Document stays the adapter's only input and the call passes no authorization or command root.

Running in the core was chosen over passing the authorization and a command root to the adapter.
The core already runs the producers from the vault root. Each adapter would otherwise repeat the
execution boundary, its timeout and the path replacement in captured output, and would need the
source machine's vault, which embedding assets avoids ([Asset bytes](#asset-bytes)).

An adapter therefore has no command options: it renders the node's `output`, and a node
without one fails naming the remedy.

## Input contracts

The core owns data-only input contracts for command fences, callouts, cards, editable
properties, and queries. Their JSON Schema definitions and parsing validation describe
source semantics only; every presentation projection remains an adapter concern.
Command-fence execution is the core's ([Command output](#command-output)).

Core configuration is restricted to source resolution and authorized command limits.
Artifact, browser, and style settings remain adapter configuration.
The core schema set includes base definitions, note profiles, project configuration,
and the input/execution subset of cross-cutting configuration. Document construction
validates every recognized fence and applicable frontmatter field with these contracts.

Document chapter content is a recursive node tree with `type`, `attrs`, `children`,
and optional `text`.

Its fixed structural types are the Markdown blocks and inline marks every adapter renders,
listed by `document.schema.json` (`structuralType`) and described in
[[capabilities/markdown#Document nodes]]. Every other type is a capability identifier.
An adapter never drops a node whose type it does not know: it shows the node's text plain and
raises one warning per type ("limited function", not an error) that names the type, itself and
the remedy, so a newer core's types degrade to text.
For each recognized input capability, the core emits an in-place, schema-validated
capability node containing only its authored data; it neither executes commands nor
creates presentation output.

It evaluates queries and Base filters only to decide which
notes the Document includes ([[input-model#Chapter content]]), never to emit results.

The Document separately carries semantic resources so adapters can resolve their
identifiers without inferring them from presentation nodes.

An adapter is any executable that declares the capability identifiers it supports in a
JSON manifest. The declaration is data, not a runtime registration mechanism. The
[[capability-reference|capability reference]] owns the supported identifiers and their semantics; adapters use
that reference rather than duplicating capability definitions.

The core validates a Document in one pass of `document.schema.json`. A node's rules are keyed by
its type, and a `discriminator` there selects the rules of that type by lookup
(`src/obs/discriminator.py`), so validation grows with the number of nodes, not with the number of
node types; a standard JSON Schema validator ignores the keyword and refuses the same Documents.

The core validates Document identifiers against a supplied capability reference and
requires an adapter to support each used capability's transitive dependencies before
starting its process.

The capability-reference generator reads those notes, rejects missing input-model
coverage and dependency identifiers, and writes the schema-validated JSON document.

Domain adapters own their evidence parsing, calculations, and artifact content;
an output adapter owns reusable rendering and interaction behavior. In evidence-driven
pipelines, the generated Obsidian vault is a disposable intermediate
representation, not a parallel authoring source.

Regeneration must derive it from the original evidence exports and explicitly
authored adapter inputs. Framework
defects are fixed here, not worked around through hand-edited intermediate notes.

An adapter's migrated artifact must provide its required interactions within the
adapter's edition, not redirect readers to a legacy interactive artifact. Missing
reusable capabilities belong in this framework; original evidence links and
downloads remain distinct from legacy-application navigation.

## Safety boundaries

Figure support uses data-only Markdown contracts and a reusable generic presentation/runtime.
Plot equations, SVG composition, and graph/diagram data remain artifact-owned calculations;
generic figure infrastructure owns validation, confined inputs, presentation, interaction,
and optional projection of canonical artifact records through the existing artifact filter.

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
- A generated artifact never refers to source-machine local files.
- Comment text is rendered with DOM text APIs and serialized with script-closing characters
	escaped. A returned artifact is untrusted input to the read-only extractor.

See [[product]] and [[input-model]].
