import { Check, Copy, RefreshCw, ShieldAlert, ShieldCheck, Store } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { api, type Detection as DetectionData } from "../api/client";
import { blockMethod, blockState, formatNumber, formatTime } from "../labels";
import { shortId } from "./History";

const RECENT_RUNS = 10;
const BADGE: Record<string, string> = { always: "bad", sometimes: "warn", recovered: "good" };

const percent = (part: number, whole: number) => (whole ? Math.round((100 * part) / whole) : 0);

/** How often stores detect and block the bot, across every run. */
export function Detection() {
  const [data, setData] = useState<DetectionData | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api
      .detection()
      .then((d) => {
        setData(d);
        setError("");
      })
      .catch(() => setError("Server tidak bisa dihubungi."));
  }, []);
  useEffect(load, [load]);

  const always = data?.blocked_stores.filter((s) => s.state === "always") ?? [];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Deteksi</h1>
          <p>Seberapa sering toko mengenali bot ini dan memblokirnya, dari semua run di komputer ini.</p>
        </div>
        <div className="page-actions">
          <button type="button" className="icon-button bordered" aria-label="Muat ulang" onClick={load}>
            <RefreshCw size={16} />
          </button>
        </div>
      </header>
      {error && <div className="notice bad">{error}</div>}
      {!data && !error && <p className="muted">Memuat…</p>}
      {data && data.visits === 0 && (
        <section className="card empty-card">
          <p className="muted">
            Belum ada toko yang dikunjungi. <a href="#/">Mulai scrape</a>.
          </p>
        </section>
      )}
      {data && data.visits > 0 && (
        <>
          <dl className="stats">
            <Tile label="Kunjungan toko" icon={<Store size={15} />} value={formatNumber(data.visits)} sub={`${formatNumber(data.stores)} toko unik`} />
            <Tile
              label="Diblokir"
              icon={<ShieldAlert size={15} />}
              value={`${percent(data.blocked, data.visits)}%`}
              sub={`${formatNumber(data.blocked)} dari ${formatNumber(data.visits)} kunjungan`}
              alert={data.blocked > 0}
            />
            <Tile
              label="Toko pernah memblokir"
              icon={<ShieldAlert size={15} />}
              value={formatNumber(data.stores_blocked)}
              sub={`dari ${formatNumber(data.stores)} toko`}
            />
            <Tile
              label="Selalu memblokir"
              icon={<ShieldCheck size={15} />}
              value={formatNumber(always.length)}
              sub="sebaiknya dilewati"
            />
          </dl>

          {Object.keys(data.by_method).length > 0 && (
            <section className="card">
              <div className="card-head">
                <h2>Cara toko memblokir</h2>
                <p>Halaman tantangan dari layanan anti-bot, atau penolakan HTTP. Bot tidak pernah mencoba menembusnya.</p>
              </div>
              <div className="card-body">
                <ul className="chips" aria-label="Cara memblokir">
                  {Object.entries(data.by_method).map(([method, n]) => (
                    <li key={method} className="tag">
                      {blockMethod(method)}: <strong>{formatNumber(n)}</strong>
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          )}

          <section className="card" aria-label="Toko yang memblokir">
            <div className="card-head">
              <h2>Toko yang memblokir</h2>
              <span className="tag solid">{formatNumber(data.blocked_stores.length)} toko</span>
              <span className="spacer" />
              {always.length > 0 && <CopyList domains={always.map((s) => s.domain)} />}
              <p>
                <strong>Selalu</strong>: diblokir di setiap kunjungan. <strong>Kadang</strong>: diblokir kunjungan
                terakhir, pernah lolos. <strong>Pulih</strong>: dulu diblokir, kunjungan terakhir lolos.
              </p>
            </div>
            {data.blocked_stores.length ? (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Toko</th>
                      <th>Status</th>
                      <th className="num">Diblokir</th>
                      <th>Cara terakhir</th>
                      <th>Terakhir dikunjungi</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.blocked_stores.map((s) => (
                      <tr key={s.domain}>
                        <td>
                          <strong>{s.domain}</strong>
                          {s.platform && <span className="sub">{s.platform}</span>}
                        </td>
                        <td>
                          <span className={`badge badge-${BADGE[s.state] ?? "neutral"}`}>{blockState(s.state)}</span>
                        </td>
                        <td className="num">
                          {formatNumber(s.blocked)} / {formatNumber(s.visits)}
                        </td>
                        <td>{blockMethod(s.last_method)}</td>
                        <td className="mono small">
                          <a href={`#/runs/${s.last_run_id}`}>{formatTime(s.last_seen)}</a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="empty">Belum ada toko yang memblokir bot ini.</p>
            )}
          </section>

          <section className="card" aria-label="Diblokir per run">
            <div className="card-head">
              <h2>Diblokir per run</h2>
              <span className="muted small">{Math.min(RECENT_RUNS, data.runs.length)} run terakhir</span>
              <p>Bila persentasenya naik, toko makin sering mengenali bot ini.</p>
            </div>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>ID run</th>
                    <th>Dimulai</th>
                    <th className="num">Toko</th>
                    <th className="num">Diblokir</th>
                    <th>Persentase</th>
                  </tr>
                </thead>
                <tbody>
                  {data.runs.slice(0, RECENT_RUNS).map((r) => (
                    <tr key={r.run_id}>
                      <td className="mono" title={r.run_id}>
                        <a href={`#/runs/${r.run_id}`}>
                          <strong>#{shortId(r.run_id)}</strong>
                        </a>
                      </td>
                      <td className="mono small">{formatTime(r.started_at)}</td>
                      <td className="num">{formatNumber(r.visits)}</td>
                      <td className="num">{formatNumber(r.blocked)}</td>
                      <td>
                        <span className="rate">
                          <span className="progress" aria-hidden="true">
                            <span className="progress-bar" style={{ width: `${percent(r.blocked, r.visits)}%` }} />
                          </span>
                          <span className="mono small">{percent(r.blocked, r.visits)}%</span>
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function CopyList({ domains }: { domains: string[] }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard
      .writeText(domains.join("\n"))
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      })
      .catch(() => setCopied(false));
  };
  return (
    <button type="button" className="button ghost small-button" onClick={copy}>
      {copied ? <Check size={14} /> : <Copy size={14} />}
      {copied ? "Tersalin" : `Salin ${formatNumber(domains.length)} toko yang selalu memblokir`}
    </button>
  );
}

function Tile({ label, icon, value, sub, alert = false }: { label: string; icon: ReactNode; value: string; sub: string; alert?: boolean }) {
  return (
    <div className={`stat ${alert ? "alert" : ""}`}>
      <dt>
        {label}
        <span aria-hidden="true">{icon}</span>
      </dt>
      <dd>{value}</dd>
      <p className="sub">{sub}</p>
    </div>
  );
}
