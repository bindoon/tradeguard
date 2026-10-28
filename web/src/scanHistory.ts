import type { ScanSummary } from "./types";

export function groupScanHistory(rows: ScanSummary[]) {
  const days = new Map<string, ScanSummary[]>();
  for (const row of rows)
    days.set(row.scanDate, [...(days.get(row.scanDate) || []), row]);
  const ready = (row: ScanSummary) =>
    ["success", "partial"].includes(row.status) ? 1 : 0;
  return [...days.entries()]
    .sort(([a], [b]) => b.localeCompare(a))
    .map(([date, runs]) => {
      runs.sort(
        (a, b) =>
          ready(b) - ready(a) ||
          (b.scannedStockCount ?? b.tradableCount ?? 0) -
            (a.scannedStockCount ?? a.tradableCount ?? 0) ||
          Number(b.status === "success") - Number(a.status === "success") ||
          (b.executionDate || "").localeCompare(a.executionDate || ""),
      );
      return { date, primary: runs[0], others: runs.slice(1) };
    });
}
