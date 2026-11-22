# obs

Obsidian-compatible Markdown is the single point of truth, rendered to HTML and other formats.

This repository holds the core, which resolves a vault into a JSON Document. Output adapters are
components in repositories of their own, the first the HTML adapter `obs-html`, which a clone finds
and installs with `obs-components` ([Components](spec/design_input/components.md)). The
[Repository layout](spec/design_input/architecture.md#repository-layout) owns the structure.

## Getting it running

Install Git with the package manager:

- Windows: `winget install --id Git.Git -e --source winget`
- Debian and Ubuntu: `sudo apt-get install -y git`
- Fedora: `sudo dnf install -y git`
- macOS: `brew install git`

Clone `https://github.com/<owner>/<repository>`, then run RUNME in the clone. It installs what
[RUNME.conf](RUNME.conf) declares and the machine lacks, then hands every argument to
`obs-document`, so this prints obs-document's help:

```sh
./RUNME.sh --help
```

On Windows:

```powershell
powershell -ExecutionPolicy Bypass -File RUNME.ps1 --help
```

The bundled specification embeds live command output through a `cmd` fence. Building it requires
`--execute-commands`; without that authorization the build stops before running any command.
Through RUNME, the HTML adapter is installed once as the component `obs-html`, and then one call
builds the specification:

```sh
./RUNME.sh components install obs-html
./RUNME.sh --source spec/manifest.md --adapter obs-html --destination out.html --execute-commands
```

[One-call build](spec/design_input/cli.md#one-call-build) owns what this call reads and writes, and
[Components](spec/design_input/components.md) how a component is found, installed and named.

## Develop

Follow [AGENTS.md](AGENTS.md) and the [testing policy](spec/design_input/quality.md). For example:

```powershell
uv run pytest test/test_paragraph_lint.py
uv run obs-document --help
```

The complete suite runs in parallel with one command, after its
setup has installed the Node test packages the browser tests use (its docstring is its reference):

```powershell
uv run python test/suite.py --setup
uv run python test/suite.py
```

## Design and reference

- [CLI](spec/design_input/cli.md): live executable help.
- [Input model](spec/design_input/input-model.md): authored source contracts.
- [Components](spec/design_input/components.md): finding and installing adapters and styles.

## License

[MIT](LICENSE).
