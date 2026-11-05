// Writes each asset's SHA-256, computed from the Document's own bytes; it never opens the vault.
const crypto = require("node:crypto");
const fs = require("node:fs");

const [documentPath, destination] = process.argv.slice(2);
const document = JSON.parse(fs.readFileSync(documentPath, "utf8"));
const digests = Object.fromEntries(document.assets.map((asset) => [
  asset.id,
  crypto.createHash("sha256").update(Buffer.from(asset.data, "base64")).digest("hex"),
]));
fs.writeFileSync(destination, JSON.stringify(digests) + "\n");
