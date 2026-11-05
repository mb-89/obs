"use strict";

const assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
const { createCanonicalTransaction } = require("../src/obs_html/canonical-transaction.js");
const replacement = require("../src/obs_html/attachment-replacement.js");

const sha256 = bytes => createHash("sha256").update(bytes).digest("hex");
const describeAsset = async (archivePath, bytes, mime) => {
  if (!/^(?:application\/pdf|text\/plain)$/.test(mime)) throw new Error("Invalid replacement asset.");
  const digest = sha256(bytes);
  return { key: sha256(Buffer.from(`${archivePath}\0${digest}`)), archivePath, mime, sha256: digest };
};
const bytes = text => new TextEncoder().encode(text);

// A report whose canonical state (notes, attachment descriptors, archive members) changes only
// through the canonical transaction, as report.js and payloads.js own it.
const fakeReport = async ({ fail } = {}) => {
  const original = await describeAsset("assets/evidence/test.pdf", bytes("old"), "application/pdf");
  const reference = `obs-asset:${original.key}`;
  const { key: oldKey, ...oldDescriptor } = original;
  const state = {
    revision: 2,
    changes: 0,
    notes: [
      { slug: "home", sourcePath: "home.md", frontmatter: {}, html: "<p>Home</p>" },
      { slug: "test", sourcePath: "records/test.md", frontmatter: { evidence: reference },
        html: `<a href="${reference}">Report</a>` },
      { slug: "summary", sourcePath: "records/summary.md", frontmatter: {},
        frontmatterHtml: { evidence: `<a href="${reference}">Report</a>` }, html: "<p>Summary</p>" },
      { slug: "other", sourcePath: "records/other.md", frontmatter: { evidence: "none" }, html: "<p>Other</p>" },
    ],
    assets: { [oldKey]: { ...oldDescriptor, archivePath: `vault/${oldDescriptor.archivePath}` } },
    members: { "vault/assets/evidence/test.pdf": "old" },
    outside: "",
  };
  const transactions = createCanonicalTransaction({
    revision: () => state.revision,
    stage: async ({ notes, assetChanges }) => {
      const assets = structuredClone(state.assets);
      const members = { ...state.members };
      for (const change of assetChanges) {
        assets[change.key] = { archivePath: `vault/${change.archivePath}`, mime: change.mime, sha256: change.sha256 };
        members[`vault/${change.archivePath}`] = new TextDecoder().decode(change.bytes);
      }
      const text = JSON.stringify(notes);
      for (const key of Object.keys(assets)) if (!text.includes(`obs-asset:${key}`)) delete assets[key];
      if (fail === "stage") throw new Error("Replacement ZIP member validation failed: vault/assets/evidence/test.pdf");
      return { notes: structuredClone(notes), assets, members };
    },
    commit: staged => {
      Object.assign(state, staged);
      state.revision += 1;
      state.changes += 1;
    },
  });
  const report = {
    get revision() { return state.revision; },
    canonicalNotes: () => structuredClone(state.notes),
    embeddedAssets: () => structuredClone(state.assets),
    serializeModel: () => JSON.stringify({ notes: state.notes, embeddedAssets: state.assets, toc: [state.outside] }),
    stageCanonicalTransaction: candidate => transactions.stage(candidate),
  };
  return { state, report, oldKey };
};

const extension = (report, trusted = () => true) =>
  replacement.create({ report, payload: { describeAsset }, trusted });

const snapshot = state => structuredClone({
  revision: state.revision, notes: state.notes, assets: state.assets, members: state.members, changes: state.changes,
});

async function run() {
  assert.equal(replacement.namespace, "obsHtml.attachments");

  {
    const { report } = await fakeReport();
    assert.throws(() => extension(report, () => false),
      /Trusted extension obsHtml\.attachments: .*--trusted-runtime-bundle ID=PATH/);
  }

  {
    const { state, report, oldKey } = await fakeReport();
    const result = await extension(report).replace({
      expectedRevision: 2, key: oldKey, bytes: bytes("new"),
    });
    assert.notEqual(result.key, oldKey);
    assert.deepEqual(result.dependents, ["records/test", "records/summary"]);
    assert.equal(result.revision, 3);
    assert.equal(state.changes, 1, "one replacement is one canonical change");
    assert.deepEqual(Object.keys(state.assets), [result.key], "the old descriptor leaves with its references");
    assert.equal(state.members["vault/assets/evidence/test.pdf"], "new");
    const text = JSON.stringify(state.notes);
    assert.equal(text.includes(oldKey), false, "no record keeps the replaced attachment");
    assert.equal(state.notes[1].frontmatter.evidence, `obs-asset:${result.key}`);
    assert.match(state.notes[1].html, new RegExp(`obs-asset:${result.key}`));
    assert.match(state.notes[2].frontmatterHtml.evidence, new RegExp(`obs-asset:${result.key}`));
    assert.equal(state.notes[3].frontmatter.evidence, "none", "unrelated records are untouched");
  }

  {
    const { state, report, oldKey } = await fakeReport({ fail: "stage" });
    const before = snapshot(state);
    const error = await extension(report).replace({ expectedRevision: 2, key: oldKey, bytes: bytes("new") })
      .then(() => null, caught => caught);
    assert.match(error.message, /obsHtml\.attachments: staging failed, nothing was applied: Replacement ZIP member/);
    assert.deepEqual(snapshot(state), before, "a failure part-way leaves everything unchanged");
  }

  {
    const { state, report, oldKey } = await fakeReport();
    const before = snapshot(state);
    const controller = new AbortController();
    const staging = report.stageCanonicalTransaction;
    report.stageCanonicalTransaction = async candidate => {
      const staged = await staging(candidate);
      controller.abort();
      return staged;
    };
    const error = await extension(report).replace({
      expectedRevision: 2, key: oldKey, bytes: bytes("new"), signal: controller.signal,
    }).then(() => null, caught => caught);
    assert.match(error.message, /cancelled after staging; nothing was applied/);
    assert.deepEqual(snapshot(state), before, "a cancellation after staging leaves everything unchanged");
  }

  {
    const { state, report, oldKey } = await fakeReport();
    const before = snapshot(state);
    const error = await extension(report).replace({ expectedRevision: 1, key: oldKey, bytes: bytes("new") })
      .then(() => null, caught => caught);
    assert.match(error.message, /revision 1 is stale \(current 2\); re-read report\.revision/);
    assert.deepEqual(snapshot(state), before, "a stale revision is refused before staging");
  }

  {
    const { state, report, oldKey } = await fakeReport();
    const staging = report.stageCanonicalTransaction;
    report.stageCanonicalTransaction = async candidate => {
      const staged = await staging(candidate);
      state.revision += 1;
      return staged;
    };
    const before = snapshot(state);
    const error = await extension(report).replace({ expectedRevision: 2, key: oldKey, bytes: bytes("new") })
      .then(() => null, caught => caught);
    assert.match(error.message, /obsHtml\.attachments: commit failed: Canonical transaction revision conflict at commit/);
    assert.deepEqual(snapshot(state), {...before, revision: 3}, "a source that moved on while staging is refused at commit");
  }

  {
    const { state, report, oldKey } = await fakeReport();
    const before = snapshot(state);
    const refusals = [
      [{ expectedRevision: 2, key: "nope", bytes: bytes("new") }, /key must be the 64-hex key/],
      [{ expectedRevision: 2, key: "0".repeat(64), bytes: bytes("new") }, /no embedded attachment has key/],
      [{ expectedRevision: 2, key: oldKey, bytes: bytes("old") }, /replacement bytes equal attachment/],
      [{ expectedRevision: 2, key: oldKey, bytes: bytes("new"), mime: "text/html" }, /replacement is invalid/],
      [{ expectedRevision: 2, key: oldKey, bytes: "new" }, /bytes must be a Uint8Array/],
    ];
    for (const [request, message] of refusals) {
      await assert.rejects(extension(report).replace(request), message);
    }
    state.outside = `obs-asset:${oldKey}`;
    await assert.rejects(extension(report).replace({ expectedRevision: 2, key: oldKey, bytes: bytes("new") }),
      /referenced outside the canonical notes/);
    state.outside = "";
    state.notes[1].frontmatter.evidence = "none";
    state.notes[1].html = "";
    state.notes[2].frontmatterHtml = {};
    await assert.rejects(extension(report).replace({ expectedRevision: 2, key: oldKey, bytes: bytes("new") }),
      /no canonical record references attachment/);
    assert.equal(state.changes, before.changes);
    assert.deepEqual(state.assets, before.assets);
  }
}

run().then(() => console.log("Attachment replacement tests passed."))
  .catch(error => { console.error(error); process.exitCode = 1; });
