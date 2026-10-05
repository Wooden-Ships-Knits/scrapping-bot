import { NewRun } from "./components/NewRun";
import { RunHistory } from "./components/RunHistory";
import { RunView } from "./components/RunView";
import { useRoute } from "./router";

export function App() {
  const route = useRoute();
  return (
    <>
      <header className="topbar">
        <a className="brand" href="#/">
          Scrapebot
        </a>
        <nav aria-label="Navigasi utama">
          <a href="#/" aria-current={route.page === "new" ? "page" : undefined}>
            Run baru
          </a>
          <a href="#/runs" aria-current={route.page !== "new" ? "page" : undefined}>
            Riwayat
          </a>
        </nav>
      </header>
      <main className="container">
        {route.page === "new" && <NewRun />}
        {route.page === "history" && <RunHistory />}
        {route.page === "run" && <RunView key={route.runId} runId={route.runId} />}
      </main>
    </>
  );
}
