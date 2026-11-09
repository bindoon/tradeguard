import { FormEvent, useEffect, useState } from "react";
import PortfolioPage, { PortfolioProps } from "./PortfolioPage";
import SelectionShell from "./SelectionShell";

async function session(action: string, credentials?: FormData) {
  const response = await fetch("/api/portfolio/" + action, {
    method: action === "session" ? "GET" : "POST",
    ...(credentials && {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.fromEntries(credentials)),
    }),
  });
  if (response.status === 429) throw new Error("尝试次数过多，请稍后再试。");
  if (response.status === 401) throw new Error("用户名或密码错误。");
  if (!response.ok) throw new Error("登录服务暂不可用，请稍后再试。");
  return (await response.json() as { authenticated: boolean }).authenticated;
}

export default function PortfolioAccess(props: PortfolioProps) {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    session("session").then(setAuthenticated).catch((err: Error) => {
      setAuthenticated(false);
      setError(err.message);
    });
  }, []);

  async function changeSession(action: "login" | "logout", credentials?: FormData) {
    setBusy(true);
    setError("");
    try {
      setAuthenticated(await session(action, credentials));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void changeSession("login", new FormData(event.currentTarget));
  }

  if (authenticated) return <PortfolioPage {...props} onLogout={() => void changeSession("logout")} accessError={error} />;
  return (
    <SelectionShell {...props} currentSection="portfolio">
      <form className="tg-panel mx-auto mt-10 max-w-md space-y-4" onSubmit={login}>
        <h1 className="tg-title">登录查看持仓</h1>
        <label className="block space-y-1">
          <span>用户名</span>
          <input className="tg-input block w-full" name="username" autoComplete="username" required />
        </label>
        <label className="block space-y-1">
          <span>密码</span>
          <input className="tg-input block w-full" name="password" type="password" autoComplete="current-password" required />
        </label>
        {error && <p className="text-sm text-red-600" role="alert">{error}</p>}
        <button className="tg-primary" disabled={authenticated === null || busy}>登录</button>
      </form>
    </SelectionShell>
  );
}
