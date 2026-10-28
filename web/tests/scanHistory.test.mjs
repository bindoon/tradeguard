import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
const source = await readFile(
  new URL("../src/scanHistory.ts", import.meta.url),
  "utf8",
);
const { outputText } = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2020,
  },
});
const { groupScanHistory } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
);
const run = (id, source, scanned, status = "partial", date = "2025-06-20") => ({
  id,
  source,
  scannedStockCount: scanned,
  scanDate: date,
  status,
});

test("daily history selects the wider saved scan without adding stocks or signals across sources", () => {
  const wide = {
    ...run("wide", "baostock", 2900),
    hitStockCount: 108,
    candidateCount: 14,
  };
  const small = {
    ...run("small", "akshare", 42, "success"),
    hitStockCount: 4,
    candidateCount: 0,
  };
  const [day] = groupScanHistory([small, wide]);
  assert.equal(day.primary, wide);
  assert.equal(day.primary.hitStockCount, 108);
  assert.equal(day.primary.candidateCount, 14);
  assert.deepEqual(day.others, [small]);
  assert.equal(day.others[0].source, "akshare");
});
test("failed executions do not hide a usable run and older dates remain visible", () => {
  const rows = [
    run("failed", "one", 5000, "failed"),
    run("ready", "two", 2500),
    run("old", "three", 3000, "success", "2025-06-19"),
  ];
  const days = groupScanHistory(rows);
  assert.equal(days.length, 2);
  assert.equal(days[0].primary.id, "ready");
  assert.equal(days[1].date, "2025-06-19");
  assert.deepEqual(
    rows.map((row) => row.id),
    ["failed", "ready", "old"],
  );
});
