import { useEffect, useState } from "react";

import { api, type RunListItem } from "../api/client";
import { formatNumber, formatTime, runState } from "../labels";
import { StatusBadge } from "./StatusBadge";

export function RunHistory() {
  const [runs, setRuns] = useState<RunListItem[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .runs()
      .then(setRuns)
      .catch(() => setError("Server tidak bisa dihubungi."));
  }, []);

  if (error) return <p className="alert alert-bad">{error}</p>;
  if (!runs) return <p className="muted">Memuat riwayat…</p>;
  if (runs.length === 0) {
    return (
      <section className="panel">
        <p className="muted">
          Belum ada run. <a href="#/">Mulai run baru</a>.
        </p>
      </section>
    );
  }
  return (
    <section className="panel">
      <h1>Riwayat run</h1>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Dimulai</th>
              <th>Jenis</th>
              <th>Masukan</th>
              <th className="num">Tautan</th>
              <th className="num">Toko</th>
              <th className="num">Produk</th>
              <th>Status</th>
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
                  <StatusBadge code={r.state} label={runState(r.state)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
