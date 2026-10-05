import { PanelLeft } from "lucide-react";

import type { Theme } from "../../theme";

export function Topbar({
  title,
  theme,
  onToggleTheme,
  onToggleSidebar,
}: {
  title: string;
  theme: Theme;
  onToggleTheme: () => void;
  onToggleSidebar: () => void;
}) {
  return (
    <header className="topbar">
      <button type="button" className="icon-button" aria-label="Tampilkan atau sembunyikan menu" onClick={onToggleSidebar}>
        <PanelLeft size={18} />
      </button>
      <span className="topbar-divider" aria-hidden="true" />
      <span className="topbar-title">{title}</span>
      <span className="spacer" />
      <button
        type="button"
        className="theme-switch"
        role="switch"
        aria-checked={theme === "light"}
        aria-label="Tema terang"
        onClick={onToggleTheme}
      >
        <span className="switch-track" aria-hidden="true">
          <span className="switch-thumb" />
        </span>
        {theme === "light" ? "LIGHT" : "DARK"}
      </button>
    </header>
  );
}
