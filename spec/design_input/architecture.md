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
there is no pin between them.

The root `adapters.json` registers each adapter by the path of
its `adapter.json`. Each part tests only itself; `uv run python test/suite.py` runs every
part's suite in its own pytest process.

The decision, 5 to 6 Nov 2026, as a matrix ([[capabilities/pugh-decisions]]): the datum is the
first adapter as it stood, a repository of its own that pinned the core by commit; the marks
read this section and that repository's history, whose 113 commits of 5 Nov hold 4 pin moves.

```figure
version: 1
kind: pugh
caption: One repository against the adapter in a repository of its own.
content:
  title: Where an integrated adapter lives
  chosen: folder
  criteria:
    - {key: pins, label: "Pin moves of the core (5 Nov)", weight: 2, better: lower, floor: 1}
    - {key: commit, label: Core and adapter change in one commit, weight: 3, better: higher, kind: judged}
    - {key: bookkeeping, label: "No pin file, sync step or second lock file", weight: 1, better: higher,
       kind: judged}
    - {key: suite, label: One command runs every suite, weight: 1, better: higher, kind: judged}
    - {key: own, label: "Each part keeps its package, tests and spec", weight: 2, better: higher,
       kind: judged}
    - {key: later, label: A later adapter may still live apart, weight: 1, better: higher, kind: judged}
  candidates:
    - {key: apart, label: The adapter in its own repository,
       what: "The first adapter as it stood, pinning the core by commit and syncing it as a module.",
       values: {pins: 4}}
    - {key: folder, label: The adapter as a folder of this repository,
       what: A uv workspace member under adapters/ that depends on the core by path.,
       values: {pins: 0}, marks: {commit: 2, bookkeeping: 1, suite: 1, own: 0, later: 0}}
  datum: {prefer: [apart]}
```
^repository-layout-decision

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
JSON capability reference for their definitions and dependencies.

Its schema and the adapter-manifest schema are the executable owners of the exchanged shape.
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
it, so they read `spec/manifest.md: …`.

ROOT is for messages only: the Document stays
machine-independent and never carries it, and neither does the artifact. Without the argument, on
a direct adapter call on a Document, messages name paths relative to the vault.

An adapter writes each warning to stderr, one per line, in the error form of
[[input-model#Chapter content|contract failures]] after `Warning: `:
`Warning: <note path>: <field path>: <what is wrong>. <remedy>.`, its note path below ROOT.

A warning does not fail the build: the adapter still writes the artifact and exits with 0. The core
shows these lines on success, each after the adapter's name ([[cli#One-call build]]); on failure,
a nonzero exit, the adapter's stderr is the detail of the core's failure message.

A call that builds several documents ([[cli#Several documents per call]]) starts the adapter once
per document, each with its own Document, destination and vault root: the call shape stays one
Document to one artifact for every adapter, and the core's start is what the call shares.

### Vault files an option names

An adapter renders from the Document alone, with one exception: a file the call names explicitly
with a vault-file option ([[cli#Adapter options]]). The adapter reads that file at the path the
core passes. The Document never carries it, so no vault content alone makes an adapter read a file.

A path option was chosen over carrying the file's bytes in the Document, unlike the
[project configuration](#project-configuration). An adapter may trust such a file, for example as
code its artifact runs, and that trust belongs to the explicit option of the build. A Document
that carried the bytes would let any Document opt into what only the call may choose.

The file lies inside the vault, so the tie to the source machine stays within the vault the build
reads anyway. The [source archive](#source-archive) holds the file and the build record repeats the
option with its vault-relative path, so a rebuild from the archive names the same file (worker
decision, 6 Nov 2026, high confidence).

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

### Source archive

A source archive discloses the vault's source data, so the Document carries it only when the
build asks for it: `obs-document --source <manifest> --embed-source` adds the Document's
`sourceArchive`, the vault's source files, each with its vault-relative `path`.

An adapter that offers a source archive packages these files, embeds them and attaches them to a PDF from the
Document alone; one that offers none ignores them. Without the option the Document has no
`sourceArchive`, and nothing in it says what the vault holds beyond what the chapters use.

The files are the vault's explicit directory snapshot: every file below the manifest's folder,
scripts and data outside the chapters included, except

- hidden files and folders (a name that starts with a dot),
- installed dependency and generated folders (`__pycache__`, `node_modules`,
  `site-packages`, `__pypackages__`, `data_output`, `design_output`, `*.egg-info`, `*.dist-info`),
- Python environments (a folder holding `pyvenv.cfg`) and
- compiled files (`.pyc`, `.pyo`, `.exe`, `.dll`, `.so`, `.dylib`, `.o`, `.obj`, `.class`).

The vault's [CSS snippets](#css-snippets) are
source files despite their hidden folder. A symlink fails the build, naming its path and the
remedy, so the archive never reaches outside the vault. The core detects no secrets: the author
inspects what the option discloses.

A file the Document already holds as an asset carries that asset's `id` instead of its bytes, so
the Document holds each file's bytes once ([Asset bytes](#asset-bytes)); every other file carries
its bytes as base64 `data`.

Carrying the files was chosen over carrying a finished ZIP or a reference the adapter may read:
a ZIP would hold a second copy of every asset's bytes and fix a packaging an adapter may want
otherwise (compression, a rebuild script, its own sources beside the vault's), and a reference ties
the adapter to the source machine's vault, as an asset root would.

The archive holds the vault only: it refers to the generator instead of copying it.

The `sourceArchive.build` record says what rebuilds the artifact, since the adapter builds from
the Document alone and the core is what knows it:

- the public `repository` (the `Repository` URL of obs's `pyproject.toml`),
- the `commit` of the checkout obs runs from (core and adapter come from this one repository),
- the package versions of every lockfile Git tracks there (`lockfiles`, by
  repository-relative path: `uv.lock` and each `package-lock.json`),
- and the `arguments` of the call that rebuild it, in the order `--adapter NAME`,
  `--destination` with the destination's file name only, each `--adapter-option`,
  `--execute-commands`, `--embed-source`,
- and the `style` the manifest declares, where it declares one ([Declared style](#declared-style)).

The record names no
path of the build machine: `--source` is the manifest the Document names, and `--document`,
`--config`, `--adapter-config` and `--capability-reference` name files outside the vault, so they
are left out.

An obs that runs from no Git checkout cannot name its commit: `--embed-source` then
fails naming the folder and the remedy, to run obs from a clone of its repository. The working
tree's uncommitted changes are not recorded.

Reading the commit and lockfiles from the checkout
was chosen over package metadata, because only a checkout holds the lockfiles and the commit
together.

The archive holds the vault alone, so a vault rebuilds from it only when its command fences read
nothing outside it: a fence names no path outside the vault root, neither an absolute one nor one
that climbs above the root, and calls only installed programs, those of obs at the recorded
commit included.

What it needs from outside comes from such a program. The rule is the author's
to keep; the core does not refuse such a fence. `test/structure/test_command_fences_stay_in_vault.py`
holds obs's own specification to it.

### CSS snippets

An Obsidian vault keeps its CSS snippets in its snippet folder, `.obsidian/snippets` unless core
configuration's `input.cssSnippetFolder` names another (`src/obs/config.schema.json`).

The Document's `cssSnippets` carries every `.css` file directly in that folder, in name order, each
with its `name` (the file name without `.css`), its vault-relative `path` and its `text`; a vault
without the folder has none. A snippet that is not UTF-8 text, or that resolves outside the vault,
fails the build naming its path.

An adapter applies the snippets its own namespace declares, by
name, from the Document alone; the core states nothing about how they style an artifact.

Carrying every snippet was chosen over reading which ones a document declares: the declaration is
a presentation choice in an adapter's namespace, which the core never reads
([[input-model#Core and adapter namespaces]]), and Obsidian's own list of enabled snippets is a
per-device appearance setting, not part of the document.

Snippets are small, so carrying the
undeclared ones costs little. The source archive carries the snippet files despite their hidden
folder: they are inputs of the documents that declare them.

### Declared style

A vault declares its style as a dependency in its manifest, in the core's namespace:
`obs.style` is a style module pinned to a commit, with the keys of an se module (se's README,
Modules): `url`, the public `https` clone URL of the module's repository, `ref`, the pin, a full
40-hex commit SHA, and optionally `path`, the module's folder inside that repository.

The Document's `style` carries that identity, `url`, `ref` and `path` as declared, and never the
module's files: an adapter that offers styles resolves and applies it; one that offers none
ignores it. A manifest without `obs.style` gives a Document without `style`, and the adapter's
default style applies.

Only the manifest declares a style: `obs.style` in any other note is an
input error naming the note and the field. A declaration that names no pin (a `ref` that is no
full commit SHA, such as a branch name) or no public `https` URL cannot be resolved the same way
by every build, so it fails the build naming the field, the declared style and the remedy.

Since the manifest is a source file, the [source archive](#source-archive) carries the
declaration, and a rebuild from the archive resolves the same pinned style without repeating an
option.

`sourceArchive.build.style` records the declared identity beside the generator, so the
archived build configuration names every pinned input of the rebuild. A one-off style that a
call passes to an adapter directly (an option the adapter's manifest does not declare to the
core) never reaches the Document or the build record, so it does not apply to a rebuild.

Declaring the style in the manifest was chosen over core configuration (`--config`): the
configuration is a file outside the vault, which the build record leaves out, so a rebuild from
the archive could not see it; the manifest travels with the vault (worker decision, 6 Nov 2026,
medium confidence).

### Project configuration

A vault may hold one project configuration: the JSON file that `input.projectConfigFilename` of the
core's configuration names in the manifest's folder, `cfg.json` by that key's default in
`src/obs/config.schema.json`. The core reads it on every build, with or without `--config`, once
per build, and splits its top-level keys in two:

- The core's keys, those `src/obs/project.schema.json` declares (`$schema`, `schemaVersion`,
  `input` and `execution`). The core validates them and applies them over its configuration: each
  key the vault's file sets replaces the value of `--config`, or the schema default without
  `--config`.

  A key or value the schema refuses fails the build naming the file, the field path and
  the schema's remedy. The vault's `input.manifestFilename` also names the note a vault folder
  given as `--source` resolves to ([[cli#One-call build]]).
- Every other top-level key. The core reads none of them and carries them unread in the
  Document's `projectConfig`: `path`, the file's vault-relative path, and `settings`, those keys
  with their values as written.

  An adapter applies the keys it knows over its own settings and
  refuses any other one, naming the file below the vault root, the field path and the remedy, so a
  key that neither the core nor the adapter knows fails the build. An adapter documents its keys
  and their precedence in its own specification.

The order is the interim adapter's, which merged the vault's file over the configuration its
`--config` named: schema defaults, then `--config`, then the vault's file. A vault without the
file gives a Document without `projectConfig`.

Carrying the settings in the Document was chosen over passing the file's path to the adapter as an
option its manifest declares: a path ties the adapter to the source machine's vault, as an asset
root would ([Asset bytes](#asset-bytes)), and the adapter would have to tell the core's keys from
its own, while the core already reads the file.

The file is a vault file, so the
[source archive](#source-archive) holds it and a rebuild from the archive reads it again and applies
it; `--config` lies outside the vault and the build record leaves it out, so a setting that must
survive a rebuild belongs in the vault's file (worker decision, 6 Nov 2026, high confidence).

## Input contracts

The core owns data-only input contracts for command fences, callouts, cards, editable
properties, and queries. Their JSON Schema definitions and parsing validation describe
source semantics only; every presentation projection remains an adapter concern.
Command-fence execution is the core's ([Command output](#command-output)).

Core configuration is restricted to source resolution and authorized command limits.
Artifact, browser, and style settings remain adapter configuration; the core carries only a
declared style's identity ([Declared style](#declared-style)).

The core schema set includes base definitions, note profiles, project configuration,
and the input/execution subset of cross-cutting configuration. Document construction
validates every recognized fence and applicable frontmatter field with these contracts.

Document chapter content is a recursive node tree with `type`, `attrs`, `children`,
and optional `text`.

Its fixed structural types are the Markdown blocks and inline marks every adapter renders,
listed by `document.schema.json` (`structuralType`) and described in
[[capabilities/markdown#Document nodes]].

Every other type is a capability identifier.
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

Each of the core's schemas is compiled into its validator once per process, by the module that
owns it. The Document schema's local references are resolved when it is compiled, not once per
node.

A vault build checks each figure body as its fence is parsed, so the error names the note and the
fence. The Document pass checks it again: that is the only check of a Document read from a file.

While parsing, a paragraph's child is checked against `$defs/blockNode` only where its type keys
one of that definition's branches; a child of any other type cannot be a block node.

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
SVG composition and graph/diagram data remain artifact-owned calculations; the core resolves
equation figures ([[input-model#Equation figures]]).

Generic figure infrastructure owns validation, confined inputs, presentation, interaction, and
optional projection of canonical artifact records through the existing artifact filter.

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
