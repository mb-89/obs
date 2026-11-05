"use strict";

const assert = require("node:assert/strict");
const { createCanonicalTransaction } = require("../src/obs_html/canonical-transaction.js");

async function run() {
  let state = {
    revision: 3,
    notes: [{ slug: "old", frontmatter: { kind: "item" } }],
    archive: "original",
    notifications: 0,
  };
  const transactions = createCanonicalTransaction({
    revision: () => state.revision,
    stage: async candidate => {
      if (candidate.notes.some(note => note.slug === "invalid")) {
        throw new Error("invalid note projection");
      }
      return {
        notes: structuredClone(candidate.notes),
        archive: candidate.assetChanges[0]?.archive || state.archive,
      };
    },
    commit: candidate => {
      state = {
        ...state,
        revision: state.revision + 1,
        notes: candidate.notes,
        archive: candidate.archive,
        notifications: state.notifications + 1,
      };
    },
  });

  const staged = await transactions.stage({
    expectedRevision: 3,
    notes: [{ slug: "new", frontmatter: { kind: "item" } }],
    assetChanges: [{ archive: "replacement" }],
  });
  assert.equal(state.notes[0].slug, "old", "staging leaves canonical notes unchanged");
  assert.equal(state.archive, "original", "staging leaves the archive unchanged");
  assert.equal(state.notifications, 0);
  staged.commit();
  assert.equal(state.notes[0].slug, "new");
  assert.equal(state.archive, "replacement");
  assert.equal(state.revision, 4);
  assert.equal(state.notifications, 1, "one successful transaction emits one change");
  assert.throws(() => staged.commit(), /already committed/);

  const failedBeforeCommit = await transactions.stage({
    expectedRevision: 4,
    notes: [{ slug: "invalid" }],
    assetChanges: [{ archive: "must-not-commit" }],
  }).then(() => null, error => error);
  assert.match(failedBeforeCommit.message, /invalid note projection/);
  assert.equal(state.revision, 4);
  assert.equal(state.notes[0].slug, "new");
  assert.equal(state.archive, "replacement");

  const conflict = await transactions.stage({
    expectedRevision: 4,
    notes: [{ slug: "later" }],
    assetChanges: [{ archive: "later-archive" }],
  });
  state.revision++;
  assert.throws(() => conflict.commit(), /revision conflict/);
  assert.equal(state.notes[0].slug, "new");
  assert.equal(state.archive, "replacement");
  assert.equal(state.notifications, 1);
}

run().then(() => console.log("Canonical transaction tests passed."))
  .catch(error => { console.error(error); process.exitCode = 1; });
