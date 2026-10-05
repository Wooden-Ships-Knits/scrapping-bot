import type { ReactNode } from "react";

import { formatNumber } from "../../labels";

function cell(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "boolean") return value ? "ya" : "tidak";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

const LINK = /^https?:\/\//;

export type Renderers = Record<string, (value: unknown) => ReactNode>;

/** Any table rows as-is: every column, long values clipped by CSS, links clickable.
 *  `renderers` may present a column differently (a status as a badge). */
export function DataTable({
  columns,
  rows,
  renderers = {},
  hidden = [],
}: {
  columns: string[];
  rows: Record<string, unknown>[];
  renderers?: Renderers;
  hidden?: string[];
}) {
  if (rows.length === 0) return <p className="empty mono">Belum ada baris.</p>;
  columns = columns.filter((c) => !hidden.includes(c));
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c} className="mono">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map((c) => {
                const value = row[c];
                const text = cell(value);
                return (
                  <td key={c} title={text.length > 40 ? text : undefined} className={typeof value === "number" ? "num" : ""}>
                    {renderers[c] ? (
                      renderers[c](value)
                    ) : typeof value === "string" && LINK.test(value) ? (
                      <a href={value} target="_blank" rel="noreferrer">
                        {text}
                      </a>
                    ) : (
                      text
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
