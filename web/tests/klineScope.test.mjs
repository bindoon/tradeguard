import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/api.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2020,
  },
});
const isolatedApi = outputText
  .replace(/import \{[^}]+\} from "\.\/MarketContext";/, `
    const activeMarket = () => window.testScope.market;
    const activeSource = () => window.testScope.source;
    const activeAdjustment = () => window.testScope.adjustment;
  `)
  .replace("import.meta.env.VITE_API_URL", '""');
const testModule = `
  const window = { location: { origin: "http://127.0.0.1:8188" }, testScope: {} };
  export function setTestScope(scope) { window.testScope = scope; }
  ${isolatedApi}
`;
const { fetchKline, setTestScope } = await import(
  `data:text/javascript;base64,${Buffer.from(testModule).toString("base64")}`
);

test("queued chart keeps its scan scope even after the active market changes", async (t) => {
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    requests.push(new URL(url));
    return { ok: true, json: async () => [] };
  });
  setTestScope({ market: "US", source: "longbridge", adjustment: "none" });

  await fetchKline("002593.SZ", 160, "2026-10-22", "baostock", {
    market: "CN",
    adjustment: "forward",
  });

  assert.equal(requests.length, 1);
  assert.equal(requests[0].pathname, "/api/kline/002593.SZ");
  assert.deepEqual(Object.fromEntries(requests[0].searchParams), {
    days: "160",
    endDate: "2026-10-22",
    source: "baostock",
    market: "CN",
    adjustment: "forward",
  });
});

test("ordinary stock charts still use the current market selection", async (t) => {
  let requested;
  t.mock.method(globalThis, "fetch", async (url) => {
    requested = new URL(url);
    return { ok: true, json: async () => [] };
  });
  setTestScope({ market: "HK", source: "longbridge", adjustment: "none" });

  await fetchKline("00700.HK", 120, "2026-10-21");
  assert.deepEqual(Object.fromEntries(requested.searchParams), {
    days: "120",
    endDate: "2026-10-21",
    market: "HK",
    source: "longbridge",
    adjustment: "none",
  });
});
