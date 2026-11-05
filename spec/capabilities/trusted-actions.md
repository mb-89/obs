---
kind: adapter-behavior
capability:
  id: trusted-actions
  summary: Invoke declared trusted runtime actions against canonical source state.
  authoring: Register a trusted action bundle through the explicit runtime boundary.
  dependsOn: ["[[capabilities/markdown-frontmatter]]", "[[capabilities/canonical-references]]"]
  source: "[[input-model#Trusted runtime and canonical replacement]]"
---

The register presents the owning metadata as the capability reference.

## Adapter extensions

An adapter documents each trusted extension it adds in a note of its own repository's
`spec/capabilities/` folder, in the same format as these notes: `kind: adapter-behavior` and the
same `capability` frontmatter, with the extension's contract in the note body. The core's notes do
not list adapter extensions.

The extension's namespace is the adapter's own option namespace, the camelCase form of the
adapter's name (`obsHtml` for obs-html), followed by a dot and the extension's area, for example
`obsHtml.attachments`.
