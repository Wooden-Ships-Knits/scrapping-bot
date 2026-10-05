import { useEffect, useState } from "react";

import { api, type RunListItem } from "../api/client";
import { formatNumber, formatTime, runState, tone } from "../labels";

export function RunsTable({ runs }: { runs: RunListItem[] }) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th className="mono">Dimulai</th>
            <th className="mono">Jenis</th>
            <th className="mono">Masukan</th>
            <th className="mono num">Tautan</th>
            <th className="mono num">Toko</th>
            <th className="mono num">Produk</th>
            <th className="mono">Status</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.run_id}>
              <td>
                <a href={`#/runs/${r.run_id}`}>{formatTime(r.started_at)}</a>
              </td>
              <td>{r.mode === "test" ? "Uji" : "Penuh"}</td>
              <td>{r.source_name}</td>
              <td className="num">{formatNumber(r.links_in)}</td>
              <td className="num">
                {formatNumber(r.stores_done)}/{formatNumber(r.stores_total)}
              </td>
              <td className="num">{formatNumber(r.products)}</td>
              <td>
                <span className={`badge badge-${tone(r.state)}`}>{runState(r.state)}</span>
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
        <h1>Riwayat run</h1>
        <p className="mono muted">Setiap run punya foldernya sendiri; tidak ada yang ditimpa.</p>
      </header>
      {error && <div className="notice bad">{error}</div>}
      {!runs && !error && <p className="mono muted">Memuat riwayat…</p>}
      {runs && runs.length === 0 && (
        <section className="card empty-card">
          <p className="mono muted">
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
