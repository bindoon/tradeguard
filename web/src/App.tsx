import { useMarket, Market } from "./MarketContext";
import { useEffect, useState } from "react";
import WatchlistPage from "./WatchlistPage";
import AlertsPage from "./AlertsPage";
import { openPath, scopedPath } from "./MarketContext";
import HomePage from "./HomePage";
import ScanPage from "./ScanPage";
import ScanResultsPage from "./ScanResultsPage";
import ScreenerPage from "./ScreenerPage";
import StockDetailPage from "./StockDetailPage";
import PortfolioPage from "./PortfolioPage";
import "./index.css";

type View =
  | { type: "home" }
  | { type: "watchlist" }
  | { type: "alerts" }
  | { type: "scan-dates" }
  | { type: "scan-results"; scanDate: string }
  | { type: "screener" }
  | { type: "stock-detail"; stockCode: string; stockName: string | null }
  | { type: "portfolio" };

function parsePath(pathname: string): View {
  const cleanPath = pathname.replace(/\/+$/, "") || "/";
  if (cleanPath === "/watchlist") return { type: "watchlist" };
  if (cleanPath === "/alerts") return { type: "alerts" };
  if (cleanPath === "/") return { type: "home" };
  if (cleanPath === "/scan") return { type: "scan-dates" };
  if (cleanPath === "/screener") return { type: "screener" };
  if (cleanPath === "/portfolio") return { type: "portfolio" };
  if (cleanPath === "/monitor") return { type: "portfolio" };

  const scanResultMatch = cleanPath.match(/^\/scan\/([^/]+)$/);
  if (scanResultMatch)
    return { type: "scan-results", scanDate: scanResultMatch[1] };

  const stockMatch = cleanPath.match(/^\/stock\/([^/]+)$/);
  if (stockMatch)
    return {
      type: "stock-detail",
      stockCode: decodeURIComponent(stockMatch[1]),
      stockName: null,
    };

  return { type: "home" };
}

function viewToPath(view: View): string {
  switch (view.type) {
    case "watchlist":
      return "/watchlist";
    case "alerts":
      return "/alerts";
    case "home":
      return "/";
    case "scan-dates":
      return "/scan";
    case "scan-results":
      return `/scan/${view.scanDate}`;
    case "screener":
      return "/screener";
    case "stock-detail":
      return `/stock/${encodeURIComponent(view.stockCode)}`;
    case "portfolio":
      return "/portfolio";
  }
}

function App() {
  const { setMarket, market } = useMarket();
  const [view, setView] = useState<View>(() =>
    parsePath(window.location.pathname),
  );

  const navProps = {
    onHome: () => navigate({ type: "home" }),
    onScan: () => navigate({ type: "scan-dates" }),
    onScreener: () => navigate({ type: "screener" }),
    onPortfolio: () => navigate({ type: "portfolio" }),
  };

  useEffect(() => {
    const handlePopState = () => {
      setView(parsePath(window.location.pathname));
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  function navigate(nextView: View, replace = false) {
    if (nextView.type === "stock-detail") {
      const suffix = nextView.stockCode.split(".").pop();
      const nextMarket: Market =
        suffix === "US" ? "US" : suffix === "HK" ? "HK" : "CN";
      if (market !== nextMarket) setMarket(nextMarket);
    }
    const nextPath = scopedPath(viewToPath(nextView));
    const method = replace ? "replaceState" : "pushState";
    if (window.location.pathname !== nextPath) {
      window.history[method](null, "", nextPath);
    }
    setView(nextView);
  }

  function goBackOrFallback(fallbackView: View) {
    if (window.history.length > 1) {
      window.history.back();
      return;
    }
    navigate(fallbackView, true);
  }

  if (view.type === "watchlist") return <WatchlistPage {...navProps} />;
  if (view.type === "alerts") return <AlertsPage {...navProps} />;

  if (view.type === "scan-dates") {
    return (
      <ScanPage
        {...navProps}
        onBack={() => navigate({ type: "home" })}
        onSelectDate={(date) =>
          navigate({ type: "scan-results", scanDate: date })
        }
      />
    );
  }

  if (view.type === "screener") {
    return (
      <ScreenerPage
        {...navProps}
        onBack={() => navigate({ type: "home" })}
        onSelectStock={(code, name) =>
          navigate({ type: "stock-detail", stockCode: code, stockName: name })
        }
      />
    );
  }

  if (view.type === "scan-results") {
    return (
      <ScanResultsPage
        {...navProps}
        scanDate={view.scanDate}
        onBack={() => navigate({ type: "scan-dates" })}
        onSelectStock={(code, _name, asOf) =>
          openPath(
            scopedPath("/stock/" + encodeURIComponent(code), {
              endDate:
                asOf || (view.scanDate.length === 10 ? view.scanDate : ""),
            }),
          )
        }
      />
    );
  }

  if (view.type === "stock-detail") {
    return (
      <StockDetailPage
        key={view.stockCode + location.search}
        {...navProps}
        stockCode={view.stockCode}
        stockName={view.stockName}
        onBack={() => goBackOrFallback({ type: "home" })}
        onPortfolio={() => navigate({ type: "portfolio" })}
      />
    );
  }

  if (view.type === "portfolio") {
    return (
      <PortfolioPage
        {...navProps}
        onBack={() => navigate({ type: "home" })}
        onSelectStock={(code, name) =>
          navigate({ type: "stock-detail", stockCode: code, stockName: name })
        }
      />
    );
  }

  return (
    <HomePage
      onScan={() => navigate({ type: "scan-dates" })}
      onScreener={() => navigate({ type: "screener" })}
      onPortfolio={() => navigate({ type: "portfolio" })}
    />
  );
}

export default App;
