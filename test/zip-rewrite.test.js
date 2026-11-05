"use strict";

const assert = require("node:assert/strict");
const { empty, inspect, rewrite, readStoredMember } = require("../src/obs_html_interim/zip-rewrite.js");

const crc32 = bytes => {
    let crc = 0xffffffff;
    for (const byte of bytes) {
        crc ^= byte;
        for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
    }
    return (crc ^ 0xffffffff) >>> 0;
};
const u16 = (view, offset, value) => view.setUint16(offset, value, true);
const u32 = (view, offset, value) => view.setUint32(offset, value, true);
function storedZip(entries, comment = "") {
    const locals = [];
    const centrals = [];
    let offset = 0;
    for (const [name, text] of entries) {
        const nameBytes = new TextEncoder().encode(name);
        const data = new TextEncoder().encode(text);
        const crc = crc32(data);
        const local = new Uint8Array(30 + nameBytes.length + data.length);
        const localView = new DataView(local.buffer);
        u32(localView, 0, 0x04034b50);
        u16(localView, 4, 20);
        u16(localView, 6, 0x0800);
        u16(localView, 8, 0);
        u16(localView, 12, 0x0021);
        u32(localView, 14, crc);
        u32(localView, 18, data.length);
        u32(localView, 22, data.length);
        u16(localView, 26, nameBytes.length);
        local.set(nameBytes, 30);
        local.set(data, 30 + nameBytes.length);
        locals.push(local);
        const central = new Uint8Array(46 + nameBytes.length);
        const centralView = new DataView(central.buffer);
        u32(centralView, 0, 0x02014b50);
        u16(centralView, 4, 20);
        u16(centralView, 6, 20);
        u16(centralView, 8, 0x0800);
        u16(centralView, 10, 0);
        u16(centralView, 14, 0x0021);
        u32(centralView, 16, crc);
        u32(centralView, 20, data.length);
        u32(centralView, 24, data.length);
        u16(centralView, 28, nameBytes.length);
        u32(centralView, 42, offset);
        central.set(nameBytes, 46);
        centrals.push(central);
        offset += local.length;
    }
    const centralSize = centrals.reduce((sum, record) => sum + record.length, 0);
    const commentBytes = new TextEncoder().encode(comment);
    const end = new Uint8Array(22 + commentBytes.length);
    const endView = new DataView(end.buffer);
    u32(endView, 0, 0x06054b50);
    u16(endView, 8, entries.length);
    u16(endView, 10, entries.length);
    u32(endView, 12, centralSize);
    u32(endView, 16, offset);
    u16(endView, 20, commentBytes.length);
    end.set(commentBytes, 22);
    const result = new Uint8Array(offset + centralSize + end.length);
    let cursor = 0;
    for (const part of [...locals, ...centrals, end]) {
        result.set(part, cursor);
        cursor += part.length;
    }
    return result;
}

const original = storedZip([
    ["vault/assets/", ""],
    ["vault/assets/evidence/role.xml", "old input"],
    ["vault/keep.txt", "keep"],
    ["vault/retain.txt", "unchanged bytes"],
], "source archive comment");
const originalBytes = original.slice();
const replacement = Uint8Array.from([0, 1, 2, 255, 13, 10]);
const updated = rewrite(original, [
    { path: "vault/assets/evidence/role.xml", bytes: replacement },
    { path: "vault/keep.txt", remove: true },
    { path: "vault/assets/evidence/next.pdf", bytes: Uint8Array.from([37, 80, 68, 70]) },
]);
assert.deepEqual([...inspect(updated).entries.map(entry => entry.name)], [
    "vault/assets/",
    "vault/assets/evidence/role.xml",
    "vault/retain.txt",
    "vault/assets/evidence/next.pdf",
]);
assert.deepEqual(readStoredMember(updated, "vault/assets/evidence/role.xml"), replacement);
assert.deepEqual(readStoredMember(updated, "vault/retain.txt"),
    new TextEncoder().encode("unchanged bytes"), "untouched ZIP members retain their bytes");
assert.equal(new TextDecoder().decode(inspect(updated).comment), "source archive comment");
const corrupted = updated.slice();
const replacementEntry = inspect(corrupted).entries.find(entry =>
    entry.name === "vault/assets/evidence/role.xml");
new DataView(corrupted.buffer).setUint32(replacementEntry.directoryOffset + 16,
    replacementEntry.crc ^ 1, true);
assert.throws(() => readStoredMember(corrupted, "vault/assets/evidence/role.xml"), /Corrupt ZIP member/);
assert.deepEqual(readStoredMember(original, "vault/assets/evidence/role.xml"),
    new TextEncoder().encode("old input"));
assert.deepEqual(original, originalBytes, "staging leaves the owning archive unchanged");
assert.throws(() => rewrite(original, [{ path: "../escape", bytes: replacement }]), /Invalid or duplicate/);
assert.throws(() => rewrite(original, [
    { path: "vault/new", bytes: replacement }, { path: "vault/new", bytes: replacement },
]), /Invalid or duplicate/);

const firstArchive = rewrite(empty(), [
    { path: "vault/assets/evidence/first.xml", bytes: replacement },
]);
assert.deepEqual(inspect(firstArchive).entries.map(entry => entry.name),
    ["vault/assets/evidence/first.xml"]);
assert.deepEqual(readStoredMember(firstArchive, "vault/assets/evidence/first.xml"), replacement);

console.log("ZIP rewrite tests passed.");
