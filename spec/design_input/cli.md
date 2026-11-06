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

The capability reference is the core's own fact, so the core ships it as package data: every
build of the package, editable ones included, writes `src/obs/capability-reference.json` from
`spec/capabilities` (`hatch_build.py`), and `--capability-reference` names another reference only
where one is wanted. The file is generated beside the package that ships it rather than in
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

Repeated pairs were chosen over a job file, as the interim CLI chose them: callers already
assemble argument arrays, and a job file would be a second input format with its own schema and
path rules. The call pays the core's start once, and the adapter once per document: the
[[architecture#Adapter call|adapter call]] hands an adapter one Document and one destination, and
a call that hands it several would change that contract for every adapter.

## Adapter options

`--adapter-option NAME=VALUE`, repeatable, passes an option to the adapter without the core naming
any adapter: the adapter declares each option it takes in the `options` of its `adapter.json`
(`src/obs/adapter.schema.json`), and the core hands it over as declared. An option the adapter does
not declare fails the call before the build, naming the adapter's manifest, the option and the
declared ones. A boolean option, the only kind so far, is `--NAME` on the adapter's command line
when its value is `true` and left out when it is `false`.
