import { useEffect, useState } from "react";

import { api, type Overview as OverviewData, type RunListItem } from "../api/client";
import { formatNumber } from "../labels";
import { RunsTable } from "./History";

export function Overview() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [recent, setRecent] = useState<RunListItem[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.overview(), api.runs()])
      .then(([o, runs]) => {
        setData(o);
        setRecent(runs.slice(0, 5));
      })
      .catch(() => setError("Server tidak bisa dihubungi."));
  }, []);

  return (
    <div className="page">
      <header className="page-head">
        <h1>Overview</h1>
        <p className="mono muted">Ringkasan semua run di komputer ini.</p>
      </header>
      {error && <div className="notice bad">{error}</div>}
      {data && (
        <dl className="stats wide">
          {[
            ["Run", data.runs],
            ["Selesai", data.runs_done],
            ["Toko dikunjungi", data.stores],
            ["Produk", data.products],
            ["Kontak", data.contacts],
          ].map(([label, value]) => (
            <div className="stat card" key={label}>
              <dt className="mono">{label}</dt>
              <dd>{formatNumber(Number(value))}</dd>
            </div>
          ))}
        </dl>
      )}
      <section className="card">
        <div className="card-head">
          <span className="mono">Run terbaru</span>
          <span className="spacer" />
          <a className="button ghost" href="#/runs">
            SEMUA RIWAYAT
          </a>
        </div>
        {recent.length ? (
          <RunsTable runs={recent} />
        ) : (
          <p className="empty mono">
            Belum ada run. <a href="#/">Mulai scrape</a>.
          </p>
        )}
      </section>
    </div>
  );
}
