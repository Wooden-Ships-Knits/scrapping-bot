import { ArrowRight, Contact, Package, Play, RefreshCw, Search, Store, Terminal } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { api, type Overview as OverviewData, type RunListItem } from "../api/client";
import { formatNumber, formatTime, runState } from "../labels";
import { RunsTable, shortId } from "./History";

const CHART_RUNS = 14;
const RECENT_RUNS = 5;

export function Overview() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(() => {
    Promise.all([api.overview(), api.runs()])
      .then(([o, r]) => {
        setData(o);
        setRuns(r);
        setError("");
      })
      .catch(() => setError("Server tidak bisa dihubungi."));
  }, []);
  useEffect(load, [load]);

  const q = query.trim().toLowerCase();
  const recent = (q ? runs.filter((r) => `${r.run_id} ${r.source_name}`.toLowerCase().includes(q)) : runs).slice(
    0,
    RECENT_RUNS,
  );
  const perRun = (n: number) => (data && data.runs ? formatNumber(Math.round(n / data.runs)) : "0");

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Overview</h1>
          <p>Ringkasan semua run di komputer ini.</p>
        </div>
        <div className="page-actions">
          <button type="button" className="icon-button bordered" aria-label="Muat ulang" onClick={load}>
            <RefreshCw size={16} />
          </button>
          <a className="button" href="#/">
            <Play size={14} /> Run baru
          </a>
        </div>
      </header>
      {error && <div className="notice bad">{error}</div>}
      {data && (
        <dl className="stats">
          <Tile label="Total run" icon={<Terminal size={15} />} value={data.runs} sub={`${formatNumber(data.runs_done)} selesai`} />
          <Tile label="Toko dikunjungi" icon={<Store size={15} />} value={data.stores} sub={`Rata-rata ${perRun(data.stores)} per run`} />
          <Tile label="Produk terkumpul" icon={<Package size={15} />} value={data.products} sub={`Rata-rata ${perRun(data.products)} per run`} />
          <Tile label="Kontak" icon={<Contact size={15} />} value={data.contacts} sub={`Rata-rata ${perRun(data.contacts)} per run`} />
        </dl>
      )}

      {runs.length > 0 && <ProductsChart runs={runs.slice(0, CHART_RUNS).reverse()} />}

      <section className="card">
        <div className="card-head">
          <h2>Run terbaru</h2>
          <span className="spacer" />
          <label className="search">
            <Search size={15} aria-hidden="true" />
            <span className="sr-only">Cari run</span>
            <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Cari ID run atau masukan…" />
          </label>
          <a className="link-arrow" href="#/runs">
            Lihat semua riwayat <ArrowRight size={15} />
          </a>
          <p>Run yang tercatat di komputer ini, terbaru dulu.</p>
        </div>
        {recent.length ? (
          <RunsTable runs={recent} />
        ) : (
          <p className="empty">
            {q ? "Tidak ada run yang cocok." : <>Belum ada run. <a href="#/">Mulai scrape</a>.</>}
          </p>
        )}
        {runs.length > 0 && (
          <div className="card-foot">
            Menampilkan {formatNumber(recent.length)} dari {formatNumber(runs.length)} run
          </div>
        )}
      </section>
    </div>
  );
}

function Tile({ label, icon, value, sub }: { label: string; icon: ReactNode; value: number; sub: string }) {
  return (
    <div className="stat">
      <dt>
        {label}
        <span aria-hidden="true">{icon}</span>
      </dt>
      <dd>{formatNumber(value)}</dd>
      <p className="sub">{sub}</p>
    </div>
  );
}

/** A rounded axis maximum with two even steps: 0, half, max. */
function niceMax(value: number): number {
  if (value <= 0) return 10;
  const step = 10 ** Math.floor(Math.log10(value));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * step >= value) return m * step;
  return 10 * step;
}

const compact = new Intl.NumberFormat("id-ID", { notation: "compact" });
const shortDate = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("id-ID", { day: "numeric", month: "short" });
};

/** Products per run, oldest on the left; each bar opens its run. Unfinished runs are hatched. */
function ProductsChart({ runs }: { runs: RunListItem[] }) {
  const max = niceMax(Math.max(...runs.map((r) => r.products)));
  const peak = runs.reduce((a, b) => (b.products > a.products ? b : a));
  const average = Math.round(runs.reduce((sum, r) => sum + r.products, 0) / runs.length);
  return (
    <section className="card" aria-label="Produk per run">
      <div className="card-head">
        <h2>Produk per run</h2>
        <span className="muted small">{runs.length} run terakhir</span>
        <p>Jumlah produk yang terkumpul di setiap run. Arahkan kursor ke batang untuk detail; klik untuk membuka run.</p>
      </div>
      <div className="chart">
        <div className="chart-axis" aria-hidden="true">
          <span>{compact.format(max)}</span>
          <span>{compact.format(max / 2)}</span>
          <span>0</span>
        </div>
        <div className="chart-plot">
          {runs.map((r) => (
            <a
              key={r.run_id}
              className={`chart-bar ${r.state === "done" ? "" : "open"}`}
              href={`#/runs/${r.run_id}`}
              aria-label={`Run ${shortId(r.run_id)}, ${formatTime(r.started_at)}: ${formatNumber(r.products)} produk, ${runState(r.state)}`}
            >
              <span className="chart-fill" style={{ height: `${(100 * r.products) / max}%` }} />
              <span className="chart-tip" role="tooltip">
                <strong>{formatNumber(r.products)} produk</strong>
                #{shortId(r.run_id)} · {formatTime(r.started_at)}
                <br />
                {r.source_name} · {runState(r.state)}
              </span>
            </a>
          ))}
        </div>
        <div className={`chart-x ${runs.length > 7 ? "dense" : ""}`} aria-hidden="true">
          {runs.map((r) => (
            <span key={r.run_id}>{shortDate(r.started_at)}</span>
          ))}
        </div>
      </div>
      <div className="card-foot">
        <span>
          Tertinggi: <strong>#{shortId(peak.run_id)}</strong> ({formatNumber(peak.products)} produk)
        </span>
        <span>Rata-rata: {formatNumber(average)} produk/run</span>
        {runs.some((r) => r.state !== "done") && <span>Batang bergaris: run belum selesai</span>}
      </div>
    </section>
  );
}
