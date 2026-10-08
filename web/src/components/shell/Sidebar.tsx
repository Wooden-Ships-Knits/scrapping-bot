import { Activity, ChartColumn, History, Play, ShieldAlert, Terminal } from "lucide-react";
import type { ReactNode } from "react";

import type { Route } from "../../router";

type Item = { href: string; label: string; icon: ReactNode; active: boolean };

export function Sidebar({ route, open, onNavigate }: { route: Route; open: boolean; onNavigate: () => void }) {
  const items: Item[] = [
    { href: "#/", label: "Scrape", icon: <Play size={16} />, active: route.page === "new" },
    { href: "#/overview", label: "Overview", icon: <ChartColumn size={16} />, active: route.page === "overview" },
    {
      href: "#/runs",
      label: "Riwayat run",
      icon: <History size={16} />,
      active: route.page === "history" || route.page === "run",
    },
    { href: "#/detection", label: "Deteksi", icon: <ShieldAlert size={16} />, active: route.page === "detection" },
    { href: "#/traffic", label: "Traffic toko", icon: <Activity size={16} />, active: route.page === "traffic" },
  ];
  return (
    <aside className={`sidebar ${open ? "open" : ""}`} aria-label="Navigasi utama">
      <a className="brand" href="#/" onClick={onNavigate}>
        <span className="brand-mark" aria-hidden="true">
          <Terminal size={16} />
        </span>
        Scrapebot
      </a>
      <nav>
        <p className="nav-title">Menu utama</p>
        {items.map((item) => (
          <a
            key={item.href}
            href={item.href}
            className="nav-item"
            aria-current={item.active ? "page" : undefined}
            onClick={onNavigate}
          >
            {item.icon}
            {item.label}
          </a>
        ))}
      </nav>
      <p className="sidebar-foot">Alat internal · hanya halaman publik · robots.txt dipatuhi</p>
    </aside>
  );
}
