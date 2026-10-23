import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(
  new URL("../src/marketInfoCache.ts", import.meta.url),
  "utf8",
);
const { outputText } = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2020,
  },
});
const { createMarketInfoCache } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
);

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

test("switching back to a fresh market uses saved information without another request", async () => {
  const requests = [];
  const cache = createMarketInfoCache(async (market) => {
    requests.push(market);
    return { market };
  });
  await cache.load("CN");
  await cache.load("HK");
  assert.equal(cache.peek("HK").market, "HK");
  assert.equal((await cache.load("CN")).market, "CN");
  assert.deepEqual(requests, ["CN", "HK"]);
});

test("stale information remains readable during refresh; explicit refresh bypasses freshness", async () => {
  let now = 0,
    calls = 0;
  let next = deferred();
  const cache = createMarketInfoCache(
    async (market) => {
      calls++;
      return calls === 1 ? { market, rows: 1 } : next.promise;
    },
    () => now,
  );
  await cache.load("HK");
  now = 60_001;
  const refreshing = cache.load("HK");
  assert.equal(cache.peek("HK").rows, 1);
  next.resolve({ market: "HK", rows: 2 });
  assert.equal((await refreshing).rows, 2);
  next = deferred();
  const forced = cache.load("HK", true);
  assert.equal(calls, 3);
  next.resolve({ market: "HK", rows: 3 });
  assert.equal((await forced).rows, 3);
});

test("simultaneous mounts share a request, while different markets remain independent", async () => {
  const cn = deferred(),
    hk = deferred(),
    requests = [];
  const cache = createMarketInfoCache((market) => {
    requests.push(market);
    return market === "CN" ? cn.promise : hk.promise;
  });
  const first = cache.load("CN"),
    again = cache.load("CN"),
    other = cache.load("HK");
  assert.equal(first, again);
  hk.resolve({ market: "HK" });
  await other;
  assert.equal(cache.peek("CN"), null);
  cn.resolve({ market: "CN" });
  await first;
  assert.deepEqual(requests, ["CN", "HK"]);
  assert.equal(cache.peek("HK").market, "HK");
});

test("failed refresh preserves saved observations and can be retried", async () => {
  let calls = 0;
  const cache = createMarketInfoCache(async (market) => {
    if (++calls === 2) throw new Error("offline");
    return { market, version: calls };
  });
  await cache.load("US");
  await assert.rejects(cache.load("US", true), /offline/);
  assert.equal(cache.peek("US").version, 1);
  assert.equal((await cache.load("US", true)).version, 3);
});

test("a response from another market never populates the requested market", async () => {
  const cache = createMarketInfoCache(async () => ({ market: "CN" }));
  await assert.rejects(cache.load("HK"), /市场状态与请求不符/);
  assert.equal(cache.peek("HK"), null);
});
