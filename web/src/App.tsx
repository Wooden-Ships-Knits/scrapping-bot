import { useState } from "react";

import { Sidebar } from "./components/shell/Sidebar";
import { Topbar, type Crumb } from "./components/shell/Topbar";
import { Detection } from "./pages/Detection";
import { History } from "./pages/History";
import { Overview } from "./pages/Overview";
import { RetailerMap } from "./pages/RetailerMap";
import { RunPage } from "./pages/RunPage";
import { Scrape } from "./pages/Scrape";
import { Traffic } from "./pages/Traffic";
import { useRoute, type Route } from "./router";
import { useTheme } from "./theme";

const CRUMBS: Record<Route["page"], Crumb[]> = {
  new: [{ label: "Scrape" }, { label: "Start a new run" }],
  overview: [{ label: "Overview" }],
  detection: [{ label: "Detection" }],
  traffic: [{ label: "Store traffic" }],
  retailer: [{ label: "Process" }, { label: "Retailer map" }],
  history: [{ label: "Run history" }],
  run: [{ label: "Run history", href: "#/runs" }, { label: "Run detail" }],
};

export function App() {
  const route = useRoute();
  const [theme, toggleTheme] = useTheme();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  // Narrow screens open the menu as a drawer; wide screens collapse it.
  const toggleSidebar = () => {
    if (window.matchMedia("(max-width: 860px)").matches) setSidebarOpen((o) => !o);
    else setCollapsed((c) => !c);
  };

  return (
    <div className={`shell ${collapsed ? "collapsed" : ""}`}>
      <Sidebar route={route} open={sidebarOpen} onNavigate={() => setSidebarOpen(false)} />
      {sidebarOpen && <div className="scrim" onClick={() => setSidebarOpen(false)} aria-hidden="true" />}
      <div className="main-area">
        <Topbar crumbs={CRUMBS[route.page]} theme={theme} onToggleTheme={toggleTheme} onToggleSidebar={toggleSidebar} />
        <main>
          {route.page === "new" && <Scrape />}
          {route.page === "overview" && <Overview />}
          {route.page === "detection" && <Detection />}
          {route.page === "traffic" && <Traffic />}
          {route.page === "retailer" && <RetailerMap />}
          {route.page === "history" && <History />}
          {route.page === "run" && <RunPage key={route.runId} runId={route.runId} />}
        </main>
      </div>
    </div>
  );
}
