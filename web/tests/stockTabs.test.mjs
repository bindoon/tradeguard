import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(
  new URL("../src/stockTabs.ts", import.meta.url),
  "utf8",
);
const { outputText } = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2020,
  },
});
const { tabPath, readStockTabs, visitStockTab, adjacentTab } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
);
const cn =
  "/stock/600000.SH?market=CN&source=fixture&adjustment=forward&endDate=2025-06-20";
const us = "/stock/AAPL.US?market=US&source=fixture&adjustment=none";

test("tab identity ignores parameter order while preserving market, source, adjustment and date", () => {
  assert.equal(
    tabPath(cn),
    tabPath(
      "/stock/600000.SH?endDate=2025-06-20&adjustment=forward&source=fixture&market=CN",
    ),
  );
  for (const other of [
    cn.replace("fixture", "other"),
    cn.replace("forward", "none"),
    cn.replace("06-20", "06-19"),
    cn.replace("CN", "HK"),
  ]) {
    assert.notEqual(tabPath(cn), tabPath(other));
  }
});

test("revisiting a stock keeps tab order and its saved display name", () => {
  const tabs = readStockTabs(
    JSON.stringify([
      { path: cn, label: "600000.SH", name: "Synthetic CN" },
      { path: us, label: "AAPL.US" },
    ]),
  );
  assert.deepEqual(visitStockTab(tabs, cn), tabs);
  assert.equal(tabs[0].name, "Synthetic CN");
  assert.equal(visitStockTab(tabs, cn.replace("06-20", "06-19")).length, 3);
});

test("restoring old tabs deduplicates equivalent URLs and rejects foreign or non-stock paths", () => {
  const tabs = readStockTabs(
    JSON.stringify([
      { path: cn, label: "600000.SH" },
      { path: tabPath(cn), label: "600000.SH" },
      { path: "https://foreign.invalid/stock/AAPL.US?market=US", label: "Bad" },
      { path: "/portfolio?market=CN", label: "Bad" },
    ]),
  );
  assert.equal(tabs.length, 1);
  assert.deepEqual(readStockTabs("broken"), []);
  assert.equal(tabPath("/stock/AAPL.US?market=UNKNOWN"), null);
});

test("closing the active stock chooses the next tab, previous tab, then the workspace", () => {
  const tabs = readStockTabs(
    JSON.stringify([
      { path: cn, label: "600000.SH" },
      { path: us, label: "AAPL.US" },
    ]),
  );
  assert.equal(adjacentTab(tabs, tabPath(cn)), tabPath(us));
  assert.equal(adjacentTab(tabs, tabPath(us)), tabPath(cn));
  assert.equal(adjacentTab([tabs[0]], tabPath(cn)), null);
});
