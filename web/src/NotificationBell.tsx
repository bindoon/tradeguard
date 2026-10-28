import { useEffect, useRef, useState } from "react";
import { Bell, X } from "lucide-react";
import { useMarket } from "./MarketContext";
import { loadNotices, readNotice, Notice } from "./workspaceApi";

export default function NotificationBell() {
  const { market, source, adjustment } = useMarket();
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<Notice[]>([]);
  const [error, setError] = useState("");
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    let cancelled = false;
    setRows([]);
    setError("");
    const load = () => {
      if (source) loadNotices().then((data) => {
        if (!cancelled) { setRows(data); setError(""); }
      }).catch(() => { if (!cancelled) setError("提醒读取失败，请稍后重试"); });
    };
    load();
    const timer = window.setInterval(load, 60000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [market, source, adjustment, open]);
  useEffect(() => {
    if (!open) return;
    const click = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setOpen(false); button.current?.focus(); }
    };
    document.addEventListener("pointerdown", click);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerdown", click);
      document.removeEventListener("keydown", key);
    };
  }, [open]);
  const unread = rows.filter((n) => !n.read).length;
  return <div className="relative shrink-0" ref={root}>
    <button ref={button} className="tg-button relative" aria-label={`提醒记录${unread ? `，${unread} 条未读` : ""}`} aria-expanded={open} aria-controls="notification-panel" onClick={() => setOpen(!open)}>
      <Bell size={19} aria-hidden="true" />
      {unread > 0 && <span className="absolute -right-2 -top-2 rounded-full bg-red-600 px-1.5 text-xs font-semibold text-white">{unread > 99 ? "99+" : unread}</span>}
    </button>
    {open && <section id="notification-panel" aria-label="提醒记录" className="absolute right-0 top-full z-50 mt-3 max-h-[65vh] w-[min(360px,85vw)] overflow-y-auto rounded-xl border border-slate-300 bg-white p-4 shadow-2xl">
      <div className="flex items-center justify-between"><h2 className="font-semibold text-slate-900">提醒记录</h2><button aria-label="关闭提醒" onClick={() => { setOpen(false); button.current?.focus(); }}><X size={18} /></button></div>
      {error && <p role="alert" className="mt-3 text-sm text-red-600">{error}</p>}
      {!error && !rows.length && <p className="tg-muted">暂无提醒记录</p>}
      {rows.map((n) => <button key={n.id} className={`mt-3 block w-full rounded-lg border p-3 text-left text-sm ${n.read ? "border-slate-200 text-slate-500" : "border-cyan-700 text-slate-900"}`} onClick={async () => {
        if (n.read) return;
        try { await readNotice(n.id); setRows((items) => items.map((item) => item.id === n.id ? { ...item, read: true } : item)); }
        catch { setError("标记已读失败，请重试"); }
      }}>
        <span className="block">{!n.read && <span className="mr-2 text-cyan-700">●</span>}{n.title}</span>
        <span className="mt-2 block text-xs text-slate-500">{new Date(n.created_at).toLocaleString("zh-CN")} · {n.read ? "已读" : "点击标记已读"}</span>
      </button>)}
    </section>}
  </div>;
}
