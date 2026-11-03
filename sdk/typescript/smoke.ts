/** Smoke test for the TypeScript SDK against the hosted API.
 *  Run: MEMLINE_API_KEY=ml_... node smoke.ts   (Node 22+ strips types)
 *  Or against a local server: MEMLINE_BASE_URL=http://127.0.0.1:8000 */
import { Memline } from "./src/index.ts";

const key = process.env.MEMLINE_API_KEY;
if (!key) throw new Error("set MEMLINE_API_KEY");
const ml = new Memline({ apiKey: key, baseUrl: process.env.MEMLINE_BASE_URL });

const out = await ml.remember({
  text: "Jordan lives in Austin and works at Globex.",
  userId: "u-sdk-ts",
  infer: false,
});
console.assert(out.results?.length > 0, "remember returned no results");
const id = out.results[0].id;

const hits = await ml.search({ query: "where does Jordan live", userId: "u-sdk-ts" });
console.assert(hits.results?.length > 0, "search returned no results");
console.assert(Array.isArray(hits.results[0].why), "search result missing why");

const health = await ml.memoryHealth("u-sdk-ts");
console.assert(typeof health.grounded_pct === "number", "health missing grounded_pct");

console.log("TS SDK smoke ok:", { stored: id, why: hits.results[0].why.slice(0, 2) });
