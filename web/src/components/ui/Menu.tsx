import { useEffect, useRef, useState, type ReactNode } from "react";

/** A button that opens a small panel below it; closes on outside click or Escape. */
export function Menu({
  label,
  icon,
  children,
  className = "chip",
  align = "left",
  ariaLabel,
}: {
  label: ReactNode;
  icon?: ReactNode;
  children: ReactNode | ((close: () => void) => ReactNode);
  className?: string;
  align?: "left" | "right";
  ariaLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const close = () => setOpen(false);
  return (
    <div className="menu" ref={root}>
      <button
        type="button"
        className={className}
        aria-expanded={open}
        aria-haspopup="true"
        aria-label={ariaLabel}
        onClick={() => setOpen((o) => !o)}
      >
        {icon}
        {label}
      </button>
      {open && (
        <div className={`menu-panel ${align}`} role="menu">
          {typeof children === "function" ? children(close) : children}
        </div>
      )}
    </div>
  );
}
