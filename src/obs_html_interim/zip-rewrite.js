((root, factory) => {
    const api = factory();
    if (typeof module === "object" && module.exports) module.exports = api;
    root.ObsHtmlZipRewrite = api;
})(typeof globalThis === "undefined" ? this : globalThis, () => {
    "use strict";

    const utf8 = new TextDecoder("utf-8", {fatal: true});
    const pathIsSafe = (name) => typeof name === "string" && name.length > 0 &&
        !name.includes("\\") && !name.includes("\0") && !name.startsWith("/") &&
        !/^[A-Za-z]:/.test(name) && !name.split("/").some((part, index, parts) =>
            part === ".." || (!part && index !== parts.length - 1));
    const crc32 = (bytes) => {
        let crc = 0xffffffff;
        for (const byte of bytes) {
            crc ^= byte;
            for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
        }
        return (crc ^ 0xffffffff) >>> 0;
    };
    const bounds = (length, offset, size, message) => {
        if (!Number.isSafeInteger(offset) || !Number.isSafeInteger(size) ||
                offset < 0 || size < 0 || offset + size > length) {
            throw new Error(message);
        }
    };
    const read16 = (view, offset) => view.getUint16(offset, true);
    const read32 = (view, offset) => view.getUint32(offset, true);
    const write16 = (view, offset, value) => view.setUint16(offset, value, true);
    const write32 = (view, offset, value) => view.setUint32(offset, value, true);

    function inspect(bytes) {
        if (!(bytes instanceof Uint8Array) || bytes.length < 22) {
            throw new Error("Truncated ZIP archive.");
        }
        const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
        let end = bytes.length - 22;
        for (; end >= Math.max(0, bytes.length - 65557); end--) {
            if (read32(view, end) === 0x06054b50 &&
                    end + 22 + read16(view, end + 20) === bytes.length) break;
        }
        if (end < Math.max(0, bytes.length - 65557)) throw new Error("Invalid ZIP directory.");
        if (read16(view, end + 4) !== 0 || read16(view, end + 6) !== 0 ||
                read16(view, end + 8) !== read16(view, end + 10)) {
            throw new Error("Multipart ZIP archives are unsupported.");
        }
        const count = read16(view, end + 10);
        const directorySize = read32(view, end + 12);
        const directoryStart = read32(view, end + 16);
        const commentLength = read16(view, end + 20);
        if (count === 0xffff || directorySize === 0xffffffff || directoryStart === 0xffffffff) {
            throw new Error("ZIP64 archives are unsupported.");
        }
        bounds(bytes.length, directoryStart, directorySize, "Invalid ZIP directory bounds.");
        if (directoryStart + directorySize !== end) throw new Error("Invalid ZIP directory length.");
        const entries = [];
        const names = new Set();
        let offset = directoryStart;
        for (let index = 0; index < count; index++) {
            bounds(bytes.length, offset, 46, "Truncated ZIP member metadata.");
            if (read32(view, offset) !== 0x02014b50) throw new Error("Invalid ZIP member metadata.");
            const flags = read16(view, offset + 8);
            const method = read16(view, offset + 10);
            const compressedSize = read32(view, offset + 20);
            const size = read32(view, offset + 24);
            const nameLength = read16(view, offset + 28);
            const extraLength = read16(view, offset + 30);
            const comment = read16(view, offset + 32);
            const localOffset = read32(view, offset + 42);
            const recordLength = 46 + nameLength + extraLength + comment;
            bounds(bytes.length, offset, recordLength, "Truncated ZIP member metadata.");
            const name = utf8.decode(bytes.subarray(offset + 46, offset + 46 + nameLength));
            if (!pathIsSafe(name) || names.has(name)) throw new Error(`Invalid or duplicate ZIP path: ${name}`);
            if ((flags & 1) || ![0, 8].includes(method)) throw new Error(`Unsupported ZIP member: ${name}`);
            bounds(bytes.length, localOffset, 30, `Truncated ZIP local header: ${name}`);
            if (read32(view, localOffset) !== 0x04034b50 ||
                    read16(view, localOffset + 6) !== flags ||
                    read16(view, localOffset + 8) !== method) {
                throw new Error(`Invalid ZIP local header: ${name}`);
            }
            const localNameLength = read16(view, localOffset + 26);
            const localExtraLength = read16(view, localOffset + 28);
            bounds(bytes.length, localOffset + 30, localNameLength + localExtraLength,
                `Truncated ZIP local name: ${name}`);
            const localName = utf8.decode(bytes.subarray(localOffset + 30, localOffset + 30 + localNameLength));
            if (localName !== name) throw new Error(`Mismatched ZIP member name: ${name}`);
            const dataOffset = localOffset + 30 + localNameLength + localExtraLength;
            bounds(bytes.length, dataOffset, compressedSize, `Truncated ZIP member data: ${name}`);
            names.add(name);
            entries.push({
                name, flags, method, crc: read32(view, offset + 16), compressedSize, size,
                localOffset, dataOffset, directoryOffset: offset, recordLength,
                centralRecord: bytes.slice(offset, offset + recordLength),
            });
            offset += recordLength;
        }
        if (offset !== end) throw new Error("Invalid ZIP directory length.");
        const localEntries = [...entries].sort((left, right) => left.localOffset - right.localOffset);
        for (let index = 0; index < localEntries.length; index++) {
            const entry = localEntries[index];
            const nextOffset = localEntries[index + 1]?.localOffset ?? directoryStart;
            if (entry.localOffset >= nextOffset || entry.dataOffset + entry.compressedSize > nextOffset) {
                throw new Error(`Invalid ZIP member range: ${entry.name}`);
            }
            entry.localBytes = bytes.slice(entry.localOffset, nextOffset);
        }
        return {
            entries,
            comment: bytes.slice(end + 22, end + 22 + commentLength),
        };
    }

    function empty() {
        const archive = new Uint8Array(22);
        write32(new DataView(archive.buffer), 0, 0x06054b50);
        return archive;
    }

    function storedMember(name, raw) {
        const encodedName = new TextEncoder().encode(name);
        if (raw.length > 0xffffffff || encodedName.length > 0xffff) throw new Error("ZIP member is too large.");
        const crc = crc32(raw);
        const local = new Uint8Array(30 + encodedName.length + raw.length);
        const localView = new DataView(local.buffer);
        write32(localView, 0, 0x04034b50);
        write16(localView, 4, 20);
        write16(localView, 6, 0x0800);
        write16(localView, 8, 0);
        write16(localView, 10, 0);
        write16(localView, 12, 0x0021);
        write32(localView, 14, crc);
        write32(localView, 18, raw.length);
        write32(localView, 22, raw.length);
        write16(localView, 26, encodedName.length);
        write16(localView, 28, 0);
        local.set(encodedName, 30);
        local.set(raw, 30 + encodedName.length);

        const central = new Uint8Array(46 + encodedName.length);
        const centralView = new DataView(central.buffer);
        write32(centralView, 0, 0x02014b50);
        write16(centralView, 4, 20);
        write16(centralView, 6, 20);
        write16(centralView, 8, 0x0800);
        write16(centralView, 10, 0);
        write16(centralView, 12, 0);
        write16(centralView, 14, 0x0021);
        write32(centralView, 16, crc);
        write32(centralView, 20, raw.length);
        write32(centralView, 24, raw.length);
        write16(centralView, 28, encodedName.length);
        write16(centralView, 30, 0);
        write16(centralView, 32, 0);
        write16(centralView, 34, 0);
        write16(centralView, 36, 0);
        write32(centralView, 38, 0);
        write32(centralView, 42, 0);
        central.set(encodedName, 46);
        return {local, central};
    }

    function rewrite(bytes, changes) {
        if (!Array.isArray(changes)) throw new Error("ZIP changes must be an array.");
        const {entries, comment} = inspect(bytes);
        const updates = new Map();
        for (const change of changes) {
            if (!change || !pathIsSafe(change.path) || updates.has(change.path) ||
                    (change.remove !== true && !(change.bytes instanceof Uint8Array)) ||
                    (change.remove === true && change.bytes !== undefined)) {
                throw new Error("Invalid or duplicate ZIP change.");
            }
            updates.set(change.path, change);
        }
        const locals = [];
        const centrals = [];
        let localOffset = 0;
        const appendStored = (name, raw) => {
            const record = storedMember(name, raw);
            const centralView = new DataView(record.central.buffer);
            write32(centralView, 42, localOffset);
            locals.push(record.local);
            centrals.push(record.central);
            localOffset += record.local.length;
        };
        for (const entry of entries) {
            const change = updates.get(entry.name);
            if (change?.remove) continue;
            if (change) {
                appendStored(entry.name, change.bytes);
                updates.delete(entry.name);
                continue;
            }
            if (localOffset > 0xffffffff) throw new Error("ZIP archive exceeds the supported size.");
            const central = entry.centralRecord.slice();
            write32(new DataView(central.buffer), 42, localOffset);
            locals.push(entry.localBytes);
            centrals.push(central);
            localOffset += entry.localBytes.length;
        }
        for (const [name, change] of updates) {
            if (!change.remove) appendStored(name, change.bytes);
        }
        const directoryOffset = localOffset;
        const directorySize = centrals.reduce((total, record) => total + record.length, 0);
        const count = centrals.length;
        if (count >= 0xffff || directoryOffset > 0xffffffff || directorySize > 0xffffffff) {
            throw new Error("ZIP64 archive output is unsupported.");
        }
        const end = new Uint8Array(22 + comment.length);
        const endView = new DataView(end.buffer);
        write32(endView, 0, 0x06054b50);
        write16(endView, 4, 0);
        write16(endView, 6, 0);
        write16(endView, 8, count);
        write16(endView, 10, count);
        write32(endView, 12, directorySize);
        write32(endView, 16, directoryOffset);
        write16(endView, 20, comment.length);
        end.set(comment, 22);
        const output = new Uint8Array(directoryOffset + directorySize + end.length);
        let offset = 0;
        for (const local of locals) {
            output.set(local, offset);
            offset += local.length;
        }
        for (const central of centrals) {
            output.set(central, offset);
            offset += central.length;
        }
        output.set(end, offset);
        return output;
    }

    const readStoredMember = (bytes, name) => {
        const entry = inspect(bytes).entries.find(item => item.name === name);
        if (!entry) throw new Error(`Missing ZIP member: ${name}`);
        if (entry.method !== 0 || entry.flags & 8) throw new Error(`ZIP member is not stored: ${name}`);
        const raw = bytes.slice(entry.dataOffset, entry.dataOffset + entry.compressedSize);
        if (raw.length !== entry.size || crc32(raw) !== entry.crc) throw new Error(`Corrupt ZIP member: ${name}`);
        return raw;
    };

    return Object.freeze({empty, inspect, rewrite, readStoredMember});
});
