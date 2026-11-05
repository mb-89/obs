# obs-html

The HTML and PDF output adapter for obs. It renders a contract-valid JSON Document, and nothing
else, to portable HTML or PDF.

## Core module

`se.toml` pins the Document contract. Use the module command to synchronize that pin, or configure
a local `[paths]` override while developing against a core checkout.

On a fresh checkout, with [se](https://github.com/mb-89/SE) checked out next to this repository,
synchronize the module before running the tests:

```powershell
uv run python ../se/scripts/se_modules.py sync
uv run pytest
```

## Adapter

`adapters.json` registers the `html` adapter and `adapter.json` declares the contract version,
the `obs-html` command and the capability identifiers it renders. `uv run obs-html --help` is the
command reference. Run the focused contract check with:

```powershell
uv run pytest test/test_adapter_manifest.py
```

`uv run obs-html-inspect --help` is the reference of the PDF inspection tools, which read a
generated PDF without a viewer so print output can be verified automatically:

```powershell
uv run pytest test/test_pdf_inspect.py
```

The adapter's own features are documented as capability notes in
[spec/capabilities](spec/capabilities), for example the trusted extension
[attachment replacement](spec/capabilities/attachment-replacement.md).

The report runtime's DOM tests run in Node over a test-only DOM adapter; install it once with
`npm --prefix test/browser ci`, then `uv run pytest -m dom` runs that tier alone.

The report verification harness, `test/browser/report-harness.cjs`, opens a rendered report in that
DOM and drives it step by step (data, chapter, table, page mode, print and presentation geometry);
its header comment is its reference.

## Command fences

Reader: whoever builds a report with `--execute-commands` or reads captured command output in one.

A generated report never contains the build machine's absolute paths. Before captured command
output (stdout and stderr) is embedded, obs-html replaces:

- paths inside `--command-root` with paths relative to it (the root itself becomes `.`);
- the home folder with `~`;
- every other absolute path, such as temporary and virtual-environment folders, with the
  placeholder `<local-path>`.

Commands run with a minimal environment, so an environment dump carries nothing machine-specific
beyond the paths replaced above. They inherit only `PATH`, `PATHEXT`, `SYSTEMROOT`, `WINDIR`,
`COMSPEC` (to find and start programs), `HOME`, `USERPROFILE`, `APPDATA`, `LOCALAPPDATA` (per-user
tool settings and caches), `TMPDIR`, `TEMP`, `TMP` (temporary folders) and `LANG`, `LC_ALL` (text
encoding), where they are set; a command that needs more sets it itself.

## License

[MIT](LICENSE).
