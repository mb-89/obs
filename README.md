# obs-html

The HTML and PDF output adapter for obs. The initial smoke adapter reads a contract-valid Document
and writes portable HTML containing its title.

## Core module

`se.toml` pins the Document contract. Use the module command to synchronize that pin, or configure
a local `[paths]` override while developing against a core checkout.

## Smoke adapter

`adapters.json` registers the `html` adapter and `adapter.json` declares the contract version and
supported capability identifiers. Run the focused contract check with:

```powershell
uv run pytest test/test_smoke_adapter.py
```

## License

[MIT](LICENSE).
