const fs = require("node:fs");

const [documentPath, destination] = process.argv.slice(2);
const document = JSON.parse(fs.readFileSync(documentPath, "utf8"));
fs.writeFileSync(destination, JSON.stringify({
  schemaVersion: document.schemaVersion,
  capabilities: document.capabilities,
}) + "\n");
