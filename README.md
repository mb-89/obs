# obs

Obsidian-compatible Markdown is the single point of truth, rendered to HTML and other formats.

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
uv run obs-html --help
```

Browser tests use the local DOM adapter:

```powershell
npm --prefix test/browser ci
```

## Design and reference

- [CLI](spec/design_input/cli.md): live executable help.
- [Configuration](spec/design_input/configuration.md): defaults and schemas.
- [Input model](spec/design_input/input-model.md): authored source contracts.
- [Artifact UI](spec/design_input/artifact-ui.md): reader, review, and PDF presentation.

## License

[MIT](LICENSE).
