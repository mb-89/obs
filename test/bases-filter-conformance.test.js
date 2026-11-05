"use strict";

// Runs the shared Bases filter and query condition fixture against the browser evaluators;
// pytest runs the same fixture against the core and the generator (test_bases_filter_conformance.py).
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const schema = fs.readFileSync(path.join(root, "src", "obs_html", "base.schema.json"), "utf8");
globalThis.document = {querySelector: selector => selector === "#base-schema" ? {textContent: schema} : null};
vm.runInThisContext(fs.readFileSync(path.join(root, "src", "obs_html", "base.js"), "utf8"));
vm.runInThisContext(fs.readFileSync(path.join(root, "src", "obs_html", "query.js"), "utf8"));

const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "bases-filter-conformance.json"), "utf8"));
// Artifact records also carry the reader's own fields; a condition must not see them.
const records = fixture.records.map(record => ({
    id: record.id, sourcePath: record.path, frontmatter: record.frontmatter,
    marks: (record.marks || []).map(mark => ({kind: mark.category, label: mark.id})),
    fields: {title: record.id, slug: record.id},
}));
const valueFor = (record, field) => globalThis.obsBases.recordValue(record, field);

for (const {filter, expected} of fixture.cases) {
    const compiled = globalThis.obsBases.compileFilter(filter, valueFor);
    assert.deepEqual(records.filter(record => compiled.match(record)).map(record => record.id), expected,
        `filter ${JSON.stringify(filter)}`);
}
for (const filter of fixture.unsupported) {
    assert.throws(() => globalThis.obsBases.compileFilter(filter, valueFor), TypeError,
        `unsupported filter ${JSON.stringify(filter)} must be rejected`);
}
for (const {where, expected} of fixture.conditions) {
    const conditions = globalThis.obsQuery.compileConditions(where);
    assert.deepEqual(records.filter(record => conditions.match(record)).map(record => record.id),
        expected, `where ${JSON.stringify(where)}`);
}
console.log(`${fixture.cases.length} cases, ${fixture.conditions.length} conditions and ${fixture.unsupported.length} unsupported filters conform.`);
