import { tone } from "../labels";

export function StatusBadge({ code, label }: { code: string; label: string }) {
  return <span className={`badge badge-${tone(code)}`}>{label}</span>;
}
