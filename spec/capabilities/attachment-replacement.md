---
kind: adapter-behavior
capability:
  id: attachment-replacement
  summary: Replace one attachment and every record that references it in one revision-checked transaction.
  authoring: From the builder-selected trusted runtime bundle, call the obsHtml.attachments trusted extension.
  dependsOn: ["trusted-actions", "attachments", "source-updates"]
  source: "[[attachment-replacement#Contract]]"
---

# Attachment replacement

Reader: whoever writes a trusted runtime bundle for an obs-html report, or changes this extension.

A trusted runtime bundle replaces an attachment with
`obsReport.trustedExtension("obsHtml.attachments").replace(...)`. The replacement and every
canonical record that references the attachment change together in one canonical transaction, or
nothing changes; a replacement prepared against an older revision is refused.

## Namespace and trust

- Namespace: `obsHtml.attachments`, the namespace obs-html uses for its own options.
- Trust: the HTML must have been built with `--trusted-runtime-bundle ID=PATH`, and that bundle
  must have registered with `obsReport.registerApplication`. Otherwise `trustedExtension` throws
  and names the option as the remedy. Markdown, metadata and uploaded files never reach the
  extension; only the selected bundle's code calls it.

## Contract

```js
const result = await obsReport.trustedExtension("obsHtml.attachments").replace({
    expectedRevision, // the obsReport.revision the replacement was prepared against
    key,              // the 64-hex key of the attachment's obs-asset: reference
    bytes,            // Uint8Array, the new content
    mime,             // optional; defaults to the current attachment's type
    signal,           // optional AbortSignal; aborting before commit applies nothing
});
// result: {previousKey, key, dependents, revision}
```

- The attachment must be a vault member of the source archive. The new bytes keep its vault path,
  so source Markdown links to it stay valid and no source change is needed.
- Dependent records are the canonical notes whose fields or content reference
  `obs-asset:<key>`; each such reference moves to the new key. The extension refuses an attachment
  that no record references, or that the report references outside its canonical notes.
- The extension stages one `obsReport.stageCanonicalTransaction` candidate (notes, archive member
  and descriptors) and commits it. The transaction's own rules apply: authored chapters cannot
  change, so the dependents are record notes, and a stale revision, a validation, compression or
  cancellation failure leaves notes, archive and descriptors unchanged.
- Every refusal is an `Error` whose message starts with `Trusted extension obsHtml.attachments:`
  and says what to do instead.

[`attachment-replacement.js`](../../src/obs_html/attachment-replacement.js) implements the
extension; `test/attachment-replacement.test.js` and
`test/test_attachment_replacement_browser.py` test it.
