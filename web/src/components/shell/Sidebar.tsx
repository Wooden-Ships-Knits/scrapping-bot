import { Bug, History, LayoutDashboard, Radar } from "lucide-react";
import type { ReactNode } from "react";

import type { Route } from "../../router";

type Item = { href: string; label: string; icon: ReactNode; active: boolean };

export function Sidebar({ route, open, onNavigate }: { route: Route; open: boolean; onNavigate: () => void }) {
  const sections: { title?: string; items: Item[] }[] = [
    {
      items: [
        { href: "#/overview", label: "Overview", icon: <LayoutDashboard size={17} />, active: route.page === "overview" },
      ],
    },
    {
      title: "Playground",
      items: [
        { href: "#/", label: "Scrape", icon: <Radar size={17} />, active: route.page === "new" || route.page === "run" },
      ],
    },
    {
      title: "Workspace",
      items: [{ href: "#/runs", label: "Riwayat", icon: <History size={17} />, active: route.page === "history" }],
    },
  ];
  return (
    <aside className={`sidebar ${open ? "open" : ""}`} aria-label="Navigasi utama">
      <a className="brand" href="#/" onClick={onNavigate}>
        <span className="brand-mark" aria-hidden="true">
          <Bug size={18} />
        </span>
        Scrapebot
      </a>
      <div className="workspace">
        <span className="avatar" aria-hidden="true">
          L
        </span>
        <span>
          <strong>Lokal</strong>
          <small>127.0.0.1</small>
        </span>
      </div>
      <nav>
        {sections.map((section, i) => (
          <div className="nav-section" key={section.title ?? i}>
            {section.title && <p className="nav-title">{section.title}</p>}
            {section.items.map((item) => (
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
          </div>
        ))}
      </nav>
      <p className="sidebar-foot">Alat internal · hanya halaman publik · robots.txt dipatuhi</p>
    </aside>
  );
}
