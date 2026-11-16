"use strict";

// A Base's live source, its pure layer (src/obs_html/live-data.js; generic-tables.md, Current data):
// paths, templates, the mapping of fetched items, the merge, the safe nodes of a new row's text and
// the check. No page and no network: base.js and query.js, the page's one conditions evaluator,
// load with a #case-folding stand-in, as bases-filter-conformance.test.js does. The declaration is
// the capability note's example (spec/capabilities/live-data.md), read with the page's YAML library.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const source = name => fs.readFileSync(path.join(root, "src", "obs_html", name), "utf8");
const folding = fs.readFileSync(path.join(root, "..", "..", "src", "obs", "case-folding.json"), "utf8");
const islands = {"#base-schema": source("base.schema.json"), "#case-folding": folding};
globalThis.document = {querySelector: selector => selector in islands ? {textContent: islands[selector]} : null};
vm.runInThisContext(source("vendor/js-yaml.min.js"));
vm.runInThisContext(source("base.js"));
vm.runInThisContext(source("query.js"));
vm.runInThisContext(source("live-data.js"));
const live = globalThis.obsLiveData;

const note = fs.readFileSync(path.join(root, "spec", "capabilities", "live-data.md"), "utf8");
const declaration = globalThis.jsyaml.load(/```yaml\n([\s\S]*?)```/.exec(note)[1]).obsHtml.liveSource;
const [connector, web] = declaration.changes;
const [request] = connector.requests;
const plain = value => JSON.parse(JSON.stringify(value));

// The exported names later pieces call stay as they are.
assert.deepEqual(Object.keys(live).sort(), ["LIMITS", "check", "fillTemplate", "instant", "lower", "mapItem",
    "merge", "notePath", "readPath", "since", "validateNodes"]);
assert.deepEqual(plain(live.LIMITS), {items: 2000, fieldBytes: 65536, pathSteps: 8});

// Paths: dotted keys and [], own keys only; an object is absent; scalars keep their type; a list
// of scalars stays a list; absent and null are undefined; more than 8 steps read nothing.
const item = {a: {b: 2, c: null, d: {e: true}}, list: [{name: "x"}, {name: 3}, {other: 1}], tags: ["p", "q"]};
assert.equal(live.readPath(item, "a.b"), 2);
assert.equal(live.readPath(item, "a.d.e"), true);
assert.equal(live.readPath(item, "a.d"), undefined);
assert.equal(live.readPath(item, "a.c"), undefined);
assert.equal(live.readPath(item, "a.missing"), undefined);
assert.deepEqual(plain(live.readPath(item, "list[].name")), ["x", 3]);
assert.deepEqual(plain(live.readPath(item, "tags")), ["p", "q"]);
assert.equal(live.readPath(item, "a.toString"), undefined);
assert.equal(live.readPath({a: {a: {a: {a: {a: {a: {a: {a: {a: 1}}}}}}}}}, "a.a.a.a.a.a.a.a.a"), undefined);
assert.equal(live.readPath({a: {a: {a: {a: {a: {a: {a: {a: 1}}}}}}}}, "a.a.a.a.a.a.a.a"), 1);

// Templates: {name} only; a missing or non-scalar value fills nothing; inside a url, encoded.
assert.equal(live.fillTemplate("issues/{repo}-{number}.md", {repo: "widgets", number: 12}), "issues/widgets-12.md");
assert.equal(live.fillTemplate("issues/{repo}-{number}.md", {repo: "widgets"}), undefined);
assert.equal(live.fillTemplate("?q={q}", {q: "a b&c"}, {url: true}), "?q=a%20b%26c");
assert.equal(live.fillTemplate("?q={q}", {q: ["a"]}, {url: true}), undefined);

// Instants: a date and time with its offset, compared as instants, never as text.
assert.equal(live.instant("2026-11-01T10:00:00Z"), live.instant("2026-11-01T11:00:00+01:00"));
assert.ok(Number.isNaN(live.instant("2026-11-01")));
assert.ok(Number.isNaN(live.instant("2026-11-01T10:00:00")));
assert.ok(Number.isNaN(live.instant("yesterday")));

// Map: a connector-shaped answer and a REST-shaped one give the same fields through the declaration.
const connectorItem = {number: 12, state: "OPEN", labels: ["ready", "bug"], updated_at: "2026-11-05T09:30:00Z",
    title: "Fix the widget", body: "Steps"};
const restItem = {number: 12, state: "open", labels: [{name: "ready"}, {name: "bug"}],
    updated_at: "2026-11-05T09:30:00Z", title: "Fix the widget", body: "Steps", pull_request: null};
const fromConnector = live.mapItem(declaration, connector, request, connectorItem);
const fromWeb = live.mapItem(declaration, web, web.requests[0], restItem);
assert.deepEqual(plain(fromConnector), plain(fromWeb));
assert.equal(fromConnector.path, "issues/widgets-12.md");
assert.equal(fromConnector.changed, Date.parse("2026-11-05T09:30:00Z"));
assert.deepEqual(plain(fromConnector.fields), {repo: "widgets", number: 12, state: "open", labels: ["ready", "bug"],
    updated: "2026-11-05T09:30:00Z", status: "Next", where: "Fix the widget"});
assert.deepEqual(plain(fromConnector.body), [{type: "paragraph", children: [{type: "text", text: "Steps"}]}]);
// exclude: a pull request is ignored; without its key or a changed instant an item is no row.
assert.equal(live.mapItem(declaration, connector, request, {...connectorItem, pull_request: {url: "https://x.test/1"}}), null);
assert.equal(live.mapItem(declaration, connector, request, {...connectorItem, number: null}), null);
assert.equal(live.mapItem(declaration, connector, request, {...connectorItem, updated_at: "soon"}), null);
// derive: the first case that matches wins; a closed item is Done whatever its labels.
assert.equal(live.mapItem(declaration, connector, request, {...connectorItem, state: "CLOSED"}).fields.status, "Done");
// A shown row the item belongs to keeps its text and its kept value; fillNew is for new rows only.
const shownRow = {sourcePath: "issues/widgets-12.md", frontmatter: {repo: "widgets", number: 12, status: "Waiting"}};
const planned = live.mapItem(declaration, connector, request, {...connectorItem, labels: ["planned"]}, () => shownRow);
assert.equal(planned.fields.status, "Waiting");
assert.equal(planned.body, undefined);
assert.equal(planned.fields.where, undefined);
// A new item whose derive lands on keep is no row: the page cannot know its value.
assert.equal(live.mapItem(declaration, connector, request, {...connectorItem, labels: ["planned"]}), null);
assert.equal(live.mapItem(declaration, connector, request, {...connectorItem, labels: []}), null);
// accept: a new item must meet it; a shown one need not.
const accepting = {...declaration, accept: [{field: "labels", equals: "bug"}]};
assert.notEqual(live.mapItem(accepting, connector, request, connectorItem), null);
assert.equal(live.mapItem(accepting, connector, request, {...connectorItem, labels: ["ready"]}), null);
assert.notEqual(live.mapItem(accepting, connector, request, {...connectorItem, labels: ["ready"]}, () => shownRow), null);

// Fetched text is data. Hostile values end as text or are refused; no function returns HTML.
const hostile = live.mapItem(declaration, connector, request, {...connectorItem,
    title: "<script>alert(1)</script>",
    body: "<img src=x onerror=alert(1)>\n[link](javascript:alert(1)) **bold**\n\nsee https://example.test/a.",
    labels: ["ready", "__proto__"]});
assert.equal(hostile.fields.where, "<script>alert(1)</script>");
assert.deepEqual(plain(hostile.fields.labels), ["ready", "__proto__"]);
assert.deepEqual(plain(hostile.body), [
    {type: "paragraph", children: [
        {type: "text", text: "<img src=x onerror=alert(1)>"}, {type: "lineBreak"},
        {type: "text", text: "[link](javascript:alert(1)) **bold**"}]},
    {type: "paragraph", children: [
        {type: "text", text: "see "}, {type: "link", label: "https://example.test/a", url: "https://example.test/a"},
        {type: "text", text: "."}]}]);
assert.throws(() => live.validateNodes([{type: "paragraph", children: [
    {type: "link", label: "x", url: "javascript:alert(1)"}]}]), TypeError);
assert.throws(() => live.validateNodes([{type: "paragraph", children: [{type: "html", html: "<b>x</b>"}]}]), TypeError);
assert.throws(() => live.validateNodes([{type: "paragraph", children: [{type: "text", text: "x", html: "<b>"}]}]), TypeError);
assert.throws(() => live.validateNodes([{type: "text", text: "outside a paragraph"}]), TypeError);
assert.throws(() => live.validateNodes([{type: "paragraph", children: [
    {type: "link", label: "x", url: "http://example.test"}]}]), TypeError);
// __proto__ in a fetched answer, or as a set target, reaches no prototype.
const polluting = JSON.parse('{"number": 13, "state": "open", "labels": ["ready"], ' +
    '"updated_at": "2026-11-05T09:30:00Z", "title": {"__proto__": {"polluted": true}}, "__proto__": {"polluted": true}}');
const unpolluted = live.mapItem(declaration, connector, {set: {repo: "widgets", ["__proto__"]: "x"}}, polluting);
assert.equal(unpolluted.fields.where, undefined);
assert.equal(Object.getPrototypeOf(unpolluted.fields), Object.prototype);
assert.equal(unpolluted.fields.polluted, undefined);
assert.equal({}.polluted, undefined);
assert.equal(Object.hasOwn(unpolluted.fields, "__proto__"), false);

// Merge: an older or equal changed changes nothing, a newer one applies, compared as instants.
const shown = new Map([["issues/widgets-12.md", {sourcePath: "issues/widgets-12.md", frontmatter: {
    repo: "widgets", number: 12, state: "open", labels: ["ready"], updated: "2026-11-05T09:30:00Z", status: "Next",
    kind: "issue", owner: "ada"}}]]);
const at = (updated, extra = {}) => ({...connectorItem, updated_at: updated, ...extra});
const merged = items => live.merge(declaration, connector, request, items, shown);
assert.equal(merged([at("2026-11-04T09:30:00Z", {state: "CLOSED"})]).rows.size, 0);
assert.equal(merged([at("2026-11-05T09:30:00Z", {state: "CLOSED"})]).rows.size, 0);
assert.equal(merged([at("2026-11-05T10:30:00+01:00", {state: "CLOSED"})]).rows.size, 0);
const newer = merged([at("2026-11-05T09:30:01Z", {state: "CLOSED", labels: []})]);
assert.equal(newer.partial, false);
assert.deepEqual(plain(newer.rows.get("issues/widgets-12.md")), {sourcePath: "issues/widgets-12.md", added: false,
    frontmatter: {repo: "widgets", number: 12, state: "closed", labels: [], updated: "2026-11-05T09:30:01Z",
        status: "Done", kind: "issue", owner: "ada"}});
// A path absent on the item removes the property; the item's newest version wins; duplicates count once.
const twice = merged([at("2026-11-06T00:00:00Z", {labels: ["running"]}), at("2026-11-07T00:00:00Z", {labels: ["ready"]}),
    at("2026-11-06T12:00:00Z", {labels: ["backlogged"]}), at("2026-11-07T00:00:00Z", {labels: ["ready"]})]);
assert.equal(twice.rows.get("issues/widgets-12.md").frontmatter.status, "Next");
const unlabelled = {...connectorItem, updated_at: "2026-11-08T00:00:00Z"};
delete unlabelled.labels;
assert.equal(Object.hasOwn(merged([unlabelled]).rows.get("issues/widgets-12.md").frontmatter, "labels"), false);
// A new item on keep adds no row; a new one that derives a value is added with its text.
assert.equal(merged([{...connectorItem, number: 40, labels: ["planned"]}]).rows.size, 0);
const added = merged([{...connectorItem, number: 41}]).rows.get("issues/widgets-41.md");
assert.equal(added.added, true);
assert.equal(added.frontmatter.status, "Next");
assert.equal(added.frontmatter.where, "Fix the widget");
assert.deepEqual(plain(added.body), [{type: "paragraph", children: [{type: "text", text: "Steps"}]}]);
// Limits: past 2000 items, or a value over 64 KiB, the item is dropped and the read is partial.
const many = Array.from({length: 2001}, (_, index) => ({...connectorItem, number: 100 + index}));
const capped = merged(many);
assert.equal(capped.partial, true);
assert.equal(capped.rows.size, 2000);
assert.equal(capped.rows.has("issues/widgets-2100.md"), false);
const huge = merged([{...connectorItem, number: 42, title: "x".repeat(65537)}, {...connectorItem, number: 43}]);
assert.equal(huge.partial, true);
assert.deepEqual([...huge.rows.keys()], ["issues/widgets-43.md"]);
assert.equal(merged([{...connectorItem, number: 44, title: "x".repeat(65536)}]).partial, false);

// since: per request, one second before the newest changed of the rows that carry its set values.
const population = [
    {sourcePath: "issues/widgets-1.md", frontmatter: {repo: "widgets", number: 1, updated: "2026-11-01T10:00:00Z"}},
    {sourcePath: "issues/widgets-2.md", frontmatter: {repo: "widgets", number: 2, updated: "2026-11-03T10:00:00+02:00"}},
    {sourcePath: "issues/gadgets-1.md", frontmatter: {repo: "gadgets", number: 1, updated: "2026-11-04T10:00:00Z"}},
];
assert.equal(live.since(declaration, {set: {repo: "widgets"}}, population), "2026-11-03T07:59:59.000Z");
assert.equal(live.since(declaration, {set: {repo: "gadgets"}}, population), "2026-11-04T09:59:59.000Z");
assert.equal(live.since(declaration, {set: {repo: "sprockets"}}, population), undefined);

// The check: a population the declaration reproduces passes.
const row = (number, status, extra = {}) => ({sourcePath: `issues/widgets-${number}.md`, frontmatter: {
    repo: "widgets", number, state: "open", labels: ["ready"], updated: "2026-11-01T10:00:00Z", status, ...extra}});
const good = [row(1, "Next"), row(2, "Done", {state: "closed"}), row(3, "Anything", {labels: ["planned"]}),
    row(4, "Kept", {labels: []})];
assert.deepEqual(live.check(declaration, good), []);
// Each failure names the note, the check and the field.
assert.deepEqual(plain(live.check(declaration, [...good, row(5, "Running")])),
    [{notePath: "issues/widgets-5.md", check: "derive", field: "status"}]);
assert.deepEqual(plain(live.check(declaration, [...good, {...row(6, "Next"), sourcePath: "elsewhere/six.md"}])),
    [{notePath: "elsewhere/six.md", check: "notePath", field: "issues/{repo}-{number}.md"}]);
assert.deepEqual(plain(live.check(declaration, [...good, row(7, "Next", {number: " "})])),
    [{notePath: "issues/widgets-7.md", check: "key", field: "number"}]);
assert.deepEqual(plain(live.check(declaration, [...good, {...row(1, "Next"), sourcePath: "issues/widgets-1.md"}])),
    [{notePath: "issues/widgets-1.md", check: "key", field: "repo, number"}]);
assert.deepEqual(plain(live.check(declaration, [...good, row(8, "Next", {updated: "2026-11-01"})])),
    [{notePath: "issues/widgets-8.md", check: "changed", field: "updated"}]);
// Each request's set values occur in at least one row.
const elsewhere = good.map(entry => ({...entry, frontmatter: {...entry.frontmatter, repo: "gadgets"},
    sourcePath: entry.sourcePath.replace("widgets", "gadgets")}));
assert.deepEqual(plain(live.check(declaration, elsewhere)),
    [{notePath: "", check: "set", field: "repo"}, {notePath: "", check: "set", field: "repo"}]);
