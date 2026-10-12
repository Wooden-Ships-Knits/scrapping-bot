import { Activity, ChartColumn, History, Play, ShieldAlert, Store, Terminal } from "lucide-react";
import { Fragment, type ReactNode } from "react";

import type { Route } from "../../router";

type Item = { href: string; label: string; icon: ReactNode; active: boolean };
type Group = { title: string; items: Item[] };

export function Sidebar({ route, open, onNavigate }: { route: Route; open: boolean; onNavigate: () => void }) {
  // Two parts: the bot that reads stores, and the process that turns a run into insight.
  const groups: Group[] = [
    {
      title: "Scrape bot",
      items: [
        { href: "#/", label: "Scrape", icon: <Play size={16} />, active: route.page === "new" },
        { href: "#/overview", label: "Overview", icon: <ChartColumn size={16} />, active: route.page === "overview" },
        {
          href: "#/runs",
          label: "Run history",
          icon: <History size={16} />,
          active: route.page === "history" || route.page === "run",
        },
        { href: "#/detection", label: "Detection", icon: <ShieldAlert size={16} />, active: route.page === "detection" },
        { href: "#/traffic", label: "Store traffic", icon: <Activity size={16} />, active: route.page === "traffic" },
      ],
    },
    {
      title: "Process",
      items: [
        { href: "#/retailer-map", label: "Retailer map", icon: <Store size={16} />, active: route.page === "retailer" },
      ],
    },
  ];
  return (
    <aside className={`sidebar ${open ? "open" : ""}`} aria-label="Main navigation">
      <a className="brand" href="#/" onClick={onNavigate}>
        <span className="brand-mark" aria-hidden="true">
          <Terminal size={16} />
        </span>
        Scrapebot
      </a>
      <nav>
        {groups.map((group) => (
          <Fragment key={group.title}>
            <p className="nav-title">{group.title}</p>
            {group.items.map((item) => (
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
          </Fragment>
        ))}
      </nav>
      <p className="sidebar-foot">Internal tool · public pages only · robots.txt respected</p>
    </aside>
  );
}
