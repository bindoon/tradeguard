import { useState } from "react";
import { saveWatch } from "./workspaceApi";
export default function WatchButton({
  symbol,
  runId,
}: {
  symbol: string;
  runId?: string;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  return (
    <div>
      <button className="tg-button" onClick={() => setOpen((v) => !v)}>
        ☆ 加入自选
      </button>
      {open && (
        <form
          className="mt-2 flex flex-wrap gap-2"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            try {
              await saveWatch(symbol, reason, runId);
              setOpen(false);
              setMessage("已保存到当前来源的自选");
            } catch (err) {
              setMessage((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <input
            aria-label={`${symbol} 观察原因`}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={4000}
            placeholder="为什么关注？计划观察什么？"
            className="tg-input min-w-0 flex-1"
          />
          <button disabled={busy} className="tg-primary">
            保存
          </button>
        </form>
      )}
      {message && (
        <p role="status" className="mt-1 text-xs text-cyan-700">
          {message}
        </p>
      )}
    </div>
  );
}
