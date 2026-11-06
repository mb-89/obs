# obs

Obsidian-compatible Markdown is the single point of truth, rendered to HTML and other formats.

This one repository holds the core, which resolves a vault into a JSON Document, and its
integrated output adapters under `adapters/`; the first is the HTML adapter in
[adapters/html](adapters/html/README.md), run as `uv run obs-html`. The
[Repository layout](spec/design_input/architecture.md#repository-layout) owns the structure.

## Install and run

Run the platform wrapper from the project folder; it passes its arguments to `obs-document`:

```powershell
.\RUNME.ps1 --help
.\RUNME.ps1 --source spec/manifest.md --adapter html --destination out.html --execute-commands
```

The bundled specification embeds live command output through a `cmd` fence. Building it requires
`--execute-commands`; without that authorization the build stops before running any command.

Through the core, one call builds the specification:

```sh
uv run obs-document --source spec/manifest.md --adapter html --destination out.html --execute-commands
```

[One-call build](spec/design_input/cli.md#one-call-build) owns what this call reads and writes.

## Develop

Follow [AGENTS.md](AGENTS.md) and the [testing policy](spec/design_input/quality.md). For example:

```powershell
uv run pytest test/test_paragraph_lint.py
uv run obs-document --help
```

The complete suite, the core's and every adapter's, runs in parallel with one command, after its
setup has installed the Node test packages the browser tests use (its docstring is its reference):

```powershell
uv run python test/suite.py --setup
uv run python test/suite.py
```

## Design and reference

- [CLI](spec/design_input/cli.md): live executable help.
- [Configuration](adapters/html/spec/configuration.md): defaults and schemas.
- [Input model](spec/design_input/input-model.md): authored source contracts.
- [Artifact UI](adapters/html/spec/artifact-ui.md): reader, review, and PDF presentation.

## License

[MIT](LICENSE).
