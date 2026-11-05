# obs-html

The HTML and PDF output adapter for obs. It renders a contract-valid JSON Document, and nothing
else, to portable HTML or PDF.

## Core module

`se.toml` pins the Document contract. Use the module command to synchronize that pin, or configure
a local `[paths]` override while developing against a core checkout.

## Adapter

`adapters.json` registers the `html` adapter and `adapter.json` declares the contract version,
the `obs-html` command and the capability identifiers it renders. `uv run obs-html --help` is the
command reference. Run the focused contract check with:

```powershell
uv run pytest test/test_adapter_manifest.py
```

## License

[MIT](LICENSE).
