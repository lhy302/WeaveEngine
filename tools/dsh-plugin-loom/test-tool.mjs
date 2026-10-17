import { apply } from "file:///C:/Users/Administrator/.dsh/profiles/node_modules/dsh-plugin-loom/lib/index.js";
const defs = [];
apply({ tools: { register: d => defs.push(d) } });
const t = defs.find(d => d.name === "loom_tally_status");
if (!t) { console.log("TOOL NOT REGISTERED:", defs.map(d=>d.name)); process.exit(2); }
const result = await t.execute({});
console.log("RAW RESULT:", JSON.stringify(result));