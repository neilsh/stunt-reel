// Validates one .glb with the Khronos glTF validator and prints its findings as JSON.
// Usage: node validate.mjs <file.glb>. Exit 0 with no errors, 1 with errors, 2 on usage or read failure.
// Prints the counts, the count per code and the first 200 messages, errors before infos.
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const validator = require("gltf-validator");

const [file] = process.argv.slice(2);
if (!file) {
  console.error("usage: node validate.mjs <file.glb>");
  process.exit(2);
}
let bytes;
try {
  bytes = new Uint8Array(await readFile(file));
} catch (error) {
  console.error(`validate: cannot read ${file}: ${error.message}`);
  process.exit(2);
}
let report;
try {
  report = await validator.validateBytes(bytes);
} catch (error) {
  console.error(`validate: the validator failed on ${file}: ${error.message}`);
  process.exit(2);
}
const { numErrors, numWarnings, numInfos, numHints } = report.issues;
// A broken file can raise thousands of messages; print the first MAX_MESSAGES and count each code.
const MAX_MESSAGES = 200;
const byCode = {};
for (const { code } of report.issues.messages) byCode[code] = (byCode[code] ?? 0) + 1;
// Errors first, so a file with thousands of them shows the ones that fail the check.
const ordered = [...report.issues.messages].sort((a, b) => a.severity - b.severity);
const messages = ordered.slice(0, MAX_MESSAGES).map(({ severity, code, message, pointer }) => ({
  severity,
  code,
  message,
  pointer,
}));
const summary = {
  file,
  numErrors,
  numWarnings,
  numInfos,
  numHints,
  countsByCode: byCode,
  messagesShown: messages.length,
  messages,
};
console.log(JSON.stringify(summary, null, 2));
process.exitCode = numErrors > 0 ? 1 : 0;
