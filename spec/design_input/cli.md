# CLI

The executable help is the CLI reference. Option semantics, examples, prerequisites,
diagnostics and operation restrictions belong to its parser, not this note.

````cmd
uv run obs-document --help
````

This command fence derives the reference from the running CLI. See [[input-model]] for source
semantics and the core's configuration schema, `src/obs/config.schema.json`, for its defaults. An
adapter's own command line is part of that adapter's specification.

## One-call build

One `obs-document` call builds an artifact from a vault:

```sh
uv run obs-document --source spec/manifest.md --adapter html --destination <scratch>/spec.html --execute-commands
```

`--source` names the manifest note or the vault folder that holds it. A folder resolves to its
note named by `input.manifestFilename` of the core's configuration (`--config`), or by that key's
default in `src/obs/config.schema.json` without one, the interim adapter's `manifest.md`. The
filename is a setting rather than a fixed name because a vault keeps its manifest under the name
its author chose, and `--config` already checks a given note against it. A folder without that
note fails the call before the build, naming the folder, the filename, the setting and the remedy.

A `--destination` inside the vault, the folder of the manifest note, fails the call before the
build, naming `--destination`, the vault and the remedy, and writes nothing, as the interim adapter
refused its output there: an artifact written into its vault becomes a file of the vault it is
built from, which the next build's `--embed-source` would archive.

Both paths are compared resolved, so a symlink that leads into the vault counts as inside it, and the vault folder itself
counts as inside. With [[cli#Several documents per call|several documents]], each `--destination`
is checked against the vault of its own `--source`.

The call has no default source or destination: a build names its `--source` and its `--destination`.

The interim adapter built this repository's spec into a fixed file below `data/data_output` when
given neither; a default in the core would hard-code one repository's layout and one adapter's output
type into a core that serves any vault and any adapter. A project that wants a fixed build keeps
it as a command, as the [[cli#One-call build|example above]] does.

The capability reference is the core's own fact, so the core ships it as package data: every
build of the package, editable ones included, writes `src/obs/capability-reference.json` from
`spec/capabilities` (`hatch_build.py`), and `--capability-reference` names another reference only
where one is wanted.

The file is generated beside the package that ships it rather than in
`data/data_output`, because an editable install reads package data from the package folder; it is
ignored like every generated file. uv builds the package again when a capability note changes, and
a test fails when the shipped reference is stale against the notes.

The Document is an intermediate file most builds never keep: with `--source` and `--adapter` it
goes to a temporary file the call removes, and `--document` names a file that keeps it. The call
validates the Document once, as it builds it, and a call that reads `--document` validates it
once, as it reads it; nothing validates it again before it is written or handed to the adapter.

`--adapter-config` defaults to `adapters.json` in the current folder, the registry at the
repository root, so the call runs from there.

A build through the core authorizes command fences once, on the core: `--execute-commands` makes
the core run the vault's command fences from the vault root and put
their captured output into the Document; without it, a command fence fails the build naming its
note and the flag ([[capabilities/command-fences#Authorization]]).

The adapter's warnings reach the person, whichever command they ran: on success, `obs-document`
writes each line the adapter wrote to stderr ([[architecture#Adapter call|adapter call]]) to its
own stderr, prefixed with the adapter's registered name, so a line reads
`<adapter>: Warning: spec/chapter.md: <field path>: <what is wrong>. <remedy>.`.

The name says
which program speaks, and the note path below the vault root says where.

The name leads, rather
than following the adapter's own `Warning:`, so the line stays the adapter's line unchanged. On a
failure the adapter's stderr is the detail of the one failure message, as before, and is not
written twice. The adapter's stdout is not shown.

## Several documents per call

One `obs-document` call builds several artifacts: each `--source` pairs, in argument order, with
the `--destination` that follows it, and `--adapter` builds each of them:

```sh
uv run obs-document --adapter html --source a/manifest.md --destination a.html --source b/manifest.md --destination b.html
```

The call builds the documents one after the other, in argument order. Every other option
(`--execute-commands`, `--embed-source`, `--config`, `--adapter-option`) applies to each of them,
and each Document goes to a temporary file, so `--document` names none. A failure stops the call
and names the source it failed on; artifacts built before it stay written.

Each adapter warning names its document the same way, `--source <manifest>: <adapter>: Warning: …`, since two manifests
in one folder share a vault root.

Repeated pairs were chosen over a job file, as the interim CLI chose them: callers already
assemble argument arrays, and a job file would be a second input format with its own schema and
path rules.

The call pays the core's start once, and the adapter once per document: the
[[architecture#Adapter call|adapter call]] hands an adapter one Document and one destination, and
a call that hands it several would change that contract for every adapter.

## Adapter options

`--adapter-option NAME=VALUE`, repeatable, passes an option to the adapter without the core naming
any adapter: the adapter declares each option it takes in the `options` of its `adapter.json`
(`src/obs/adapter.schema.json`), and the core hands it over as declared. An option the adapter does
not declare fails the call before the build, naming the adapter's manifest, the option and the
declared ones. A boolean option, the only kind so far, is `--NAME` on the adapter's command line
when its value is `true` and left out when it is `false`. What the core's own options put into
the Document, such as the vault's sources with `--embed-source`, reaches every adapter through the
Document and is no adapter option.
