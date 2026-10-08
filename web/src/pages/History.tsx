import { useEffect, useState } from "react";

import { api, type RunListItem } from "../api/client";
import { formatNumber, formatTime, runState, tone } from "../labels";

/** The short, readable end of a run id ("20261005T085253123Z-56162b" → "56162b"). */
export const shortId = (runId: string) => runId.split("-").pop() ?? runId;

export function RunsTable({ runs }: { runs: RunListItem[] }) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>ID run</th>
            <th>Masukan</th>
            <th>Dimulai</th>
            <th className="num">Toko</th>
            <th className="num">Produk</th>
            <th>Status</th>
            <th className="end">Aksi</th>
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
                  {r.mode === "test" ? "Terbatas" : "Penuh"} · {formatNumber(r.links_in)} tautan
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
                  Detail
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
      .catch(() => setError("Server tidak bisa dihubungi."));
  }, []);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Riwayat run</h1>
          <p>Setiap run punya foldernya sendiri; tidak ada yang ditimpa.</p>
        </div>
      </header>
      {error && <div className="notice bad">{error}</div>}
      {!runs && !error && <p className="muted">Memuat riwayat…</p>}
      {runs && runs.length === 0 && (
        <section className="card empty-card">
          <p className="muted">
            Belum ada run. <a href="#/">Mulai run baru</a>.
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
