# obs

Obsidian-compatible Markdown is the single point of truth, rendered to HTML and other formats.

This one repository holds the core, which resolves a vault into a JSON Document, and its
integrated output adapters under `adapters/`; the first is the HTML adapter in
[adapters/html](adapters/html/README.md), run as `uv run obs-html`. Until the cutover, the
interim adapter `obs-html-interim` still builds artifacts directly from a vault. The
[Repository layout](spec/design_input/architecture.md#repository-layout) owns the structure.

## Install and run

Run the platform wrapper from the project folder:

```powershell
.\RUNME.ps1 --help
.\RUNME.ps1 --execute-commands
```

The bundled specification embeds live command output through a `cmd` fence. Building it requires
`--execute-commands`; without that authorization the build stops before running any command.

## Develop

Follow [AGENTS.md](AGENTS.md) and the [testing policy](spec/design_input/quality.md). For example:

```powershell
uv run pytest test/test_content.py -k paragraph
uv run obs-html-interim --help
```

Browser tests use the local DOM adapter:

```powershell
npm --prefix test/browser ci
npm --prefix adapters/html/test/browser ci
```

The complete suite, the core's and every adapter's, runs in parallel with one command:

```powershell
uv run python test/suite.py
```

## Design and reference

- [CLI](spec/design_input/cli.md): live executable help.
- [Configuration](adapters/html/spec/configuration.md): defaults and schemas.
- [Input model](spec/design_input/input-model.md): authored source contracts.
- [Artifact UI](adapters/html/spec/artifact-ui.md): reader, review, and PDF presentation.

## License

[MIT](LICENSE).
