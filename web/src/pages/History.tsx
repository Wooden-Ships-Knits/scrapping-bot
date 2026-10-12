import { useEffect, useState } from "react";

import { api, type RunListItem } from "../api/client";
import { formatNumber, formatTime, plural, runState, tone } from "../labels";

/** The short, readable end of a run id ("20261005T085253123Z-56162b" → "56162b"). */
export const shortId = (runId: string) => runId.split("-").pop() ?? runId;

export function RunsTable({ runs }: { runs: RunListItem[] }) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>Run ID</th>
            <th>Input</th>
            <th>Started</th>
            <th className="num">Stores</th>
            <th className="num">Products</th>
            <th>Status</th>
            <th className="end">Action</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.run_id}>
              <td className="mono" title={r.run_id}>
                <strong>#{shortId(r.run_id)}</strong>
              </td>
              <td>
                {r.source_name}
                <span className="sub">
                  {r.mode === "test" ? "Limited" : "Full"} · {plural(r.links_in, "link")}
                </span>
              </td>
              <td className="mono small">{formatTime(r.started_at)}</td>
              <td className="num">
                {formatNumber(r.stores_done)} / {formatNumber(r.stores_total)}
              </td>
              <td className="num">
                <strong>{formatNumber(r.products)}</strong>
              </td>
              <td>
                <span className={`badge badge-${tone(r.state)}`}>{runState(r.state)}</span>
              </td>
              <td className="end">
                <a className="button ghost small-button" href={`#/runs/${r.run_id}`}>
                  Details
                </a>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function History() {
  const [runs, setRuns] = useState<RunListItem[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .runs()
      .then(setRuns)
      .catch(() => setError("The server cannot be reached."));
  }, []);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Run history</h1>
          <p>Every run has its own folder; nothing is overwritten.</p>
        </div>
      </header>
      {error && <div className="notice bad">{error}</div>}
      {!runs && !error && <p className="muted">Loading the history…</p>}
      {runs && runs.length === 0 && (
        <section className="card empty-card">
          <p className="muted">
            No runs yet. <a href="#/">Start a new run</a>.
          </p>
        </section>
      )}
      {runs && runs.length > 0 && (
        <section className="card">
          <RunsTable runs={runs} />
        </section>
      )}
    </div>
  );
}
