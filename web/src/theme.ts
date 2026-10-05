import { useEffect, useState } from "react";

export type Theme = "dark" | "light";
const KEY = "scrapebot.theme";

function stored(): Theme {
  try {
    const value = localStorage.getItem(KEY);
    if (value === "dark" || value === "light") return value;
  } catch {
    // storage blocked: fall through to the default
  }
  return "dark";
}

/** Dark by default, remembered per browser. */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(stored);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      // a preference only; nothing breaks without it
    }
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "dark" ? "light" : "dark"))];
}
