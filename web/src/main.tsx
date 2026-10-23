import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { MarketProvider, useMarket } from "./MarketContext";
function MarketApp() {
  const { market, source, adjustment } = useMarket();
  return <App key={market + ":" + source + ":" + adjustment} />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MarketProvider>
      <MarketApp />
    </MarketProvider>
  </StrictMode>,
);
