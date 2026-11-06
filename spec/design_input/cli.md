# CLI

The executable help is the CLI reference. Option semantics, examples, prerequisites,
diagnostics and operation restrictions belong to its parser, not this note.

````cmd
uv run obs-document --help
````

This command fence derives the reference from the running CLI. See [[input-model]] for source
semantics and the core's configuration schema, `src/obs/config.schema.json`, for its defaults. An
adapter's own command line is part of that adapter's specification.

## Command fences through the core

A build through the core authorizes command fences once, on the core:

```sh
uv run obs-document --source spec/manifest.md --document <scratch>/spec.json \
  --capability-reference <scratch>/capabilities.json --execute-commands \
  --adapter html --adapter-config adapters.json --destination <scratch>/spec.html
```

`--execute-commands` makes the core run the vault's command fences from the vault root and put
their captured output into the Document; without it, a command fence fails the build naming its
note and the flag ([[capabilities/command-fences#Authorization]]).
