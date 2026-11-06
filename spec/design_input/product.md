---
summary: obs turns an ordered Obsidian Markdown vault into one JSON Document that adapters render into portable artifacts. To use it, download the source archive and follow the README's Install and Run instructions.
---

# obs

`obs` reads an Obsidian-compatible Markdown vault into one JSON Document, which an adapter renders
into an artifact. The first release is one-way: vault content is read, and generated output is
never written back into the source vault.

## Goals

- Run from a bare Windows or Unix-like machine through `RUNME.ps1` or `RUNME.sh`.
- Accept this design manifest or a manifest in another vault through the same interface.
- Keep all artifact data inside the artifact so it can be sent by email and opened on another
  machine without access to the source vault.
- Build distributions belong under `data/data_output/dist`, not a user-facing root folder.
- Derive the table of contents and chapter order directly from a nested link manifest.
- Keep the user-facing top-level `data` and `spec` directories at no more than five
  child directories and five files each; dot-prefixed entries are exempt.

## Non-goals for the first release

- Synchronizing generated artifact changes back to Markdown.
- Reproducing the complete Obsidian application.
- Requiring Obsidian to be installed.

See [[architecture]], [[cli]], and [[input-model]].
