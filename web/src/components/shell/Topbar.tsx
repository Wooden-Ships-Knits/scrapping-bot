import { PanelLeft } from "lucide-react";
import { Fragment } from "react";

import type { Theme } from "../../theme";

export type Crumb = { label: string; href?: string };

export function Topbar({
  crumbs,
  theme,
  onToggleTheme,
  onToggleSidebar,
}: {
  crumbs: Crumb[];
  theme: Theme;
  onToggleTheme: () => void;
  onToggleSidebar: () => void;
}) {
  return (
    <header className="topbar">
      <button type="button" className="icon-button" aria-label="Tampilkan atau sembunyikan menu" onClick={onToggleSidebar}>
        <PanelLeft size={18} />
      </button>
      <nav className="crumbs" aria-label="Lokasi">
        <a href="#/">Scrapebot</a>
        {crumbs.map((c, i) => (
          <Fragment key={c.label}>
            <span className="sep" aria-hidden="true">
              /
            </span>
            {i === crumbs.length - 1 ? (
              <span aria-current="page">{c.label}</span>
            ) : c.href ? (
              <a href={c.href}>{c.label}</a>
            ) : (
              <span>{c.label}</span>
            )}
          </Fragment>
        ))}
      </nav>
      <span className="spacer" />
      <span className="host-pill" title="Server tempat antarmuka ini berjalan">
        Lokal · {window.location.host || "127.0.0.1"}
      </span>
      <button
        type="button"
        className="theme-switch"
        role="switch"
        aria-checked={theme === "dark"}
        aria-label="Tema gelap"
        onClick={onToggleTheme}
      >
        <span className="switch-track" aria-hidden="true">
          <span className="switch-thumb" />
        </span>
        {theme === "dark" ? "GELAP" : "TERANG"}
      </button>
    </header>
  );
}
