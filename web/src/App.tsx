import { useState } from "react";

import { Sidebar } from "./components/shell/Sidebar";
import { Topbar } from "./components/shell/Topbar";
import { History } from "./pages/History";
import { Overview } from "./pages/Overview";
import { RunPage } from "./pages/RunPage";
import { Scrape } from "./pages/Scrape";
import { useRoute } from "./router";
import { useTheme } from "./theme";

const TITLES = { new: "Scrape", overview: "Overview", history: "Riwayat", run: "Scrape / Run" } as const;

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
        <Topbar title={TITLES[route.page]} theme={theme} onToggleTheme={toggleTheme} onToggleSidebar={toggleSidebar} />
        <main>
          {route.page === "new" && <Scrape />}
          {route.page === "overview" && <Overview />}
          {route.page === "history" && <History />}
          {route.page === "run" && <RunPage key={route.runId} runId={route.runId} />}
        </main>
      </div>
    </div>
  );
}
