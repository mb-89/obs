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

The report runtime's DOM tests run in Node over a test-only DOM adapter; install it once with
`npm --prefix test/browser ci`, then `uv run pytest -m dom` runs that tier alone.

## License

[MIT](LICENSE).
