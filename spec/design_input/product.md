---
bottom line: obs-html turns an ordered Obsidian Markdown vault into one portable, reviewable HTML report. To use it, download the source archive and follow the README's Install and Run instructions.
---

# obs-html

`obs-html` creates portable HTML reports from Obsidian-compatible Markdown vaults.
The first release is one-way: vault content is read, and generated output is never
written back into the source vault.

## Goals

- Run from a bare Windows or Unix-like machine through `RUNME.ps1` or `RUNME.sh`.
- Accept this design manifest or a manifest in another vault through the same interface.
- Produce one portable HTML file with generation provenance suitable for local viewing or static
  hosting.
- Keep all report data inside that file so it can be sent by email and opened on another
  machine without access to the source vault.
- Network CDN dependencies are allowed; local filesystem dependencies are not.
- Build distributions belong under `data/data_output/dist`, not a user-facing root folder.
- Derive the table of contents and chapter order directly from a nested link manifest.
- Present one chapter at a time with table-of-contents and previous/next navigation.
- Keep the user-facing top-level `data` and `spec` directories at no more than five
  child directories and five files each; dot-prefixed entries are exempt.

## Non-goals for the first release

- Synchronizing generated HTML changes back to Markdown.
- Reproducing the complete Obsidian application.
- Requiring Obsidian to be installed.

See [[architecture]], [[cli]], [[configuration]], and [[input-model]].
