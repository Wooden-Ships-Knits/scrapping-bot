import { Check, Copy, RefreshCw, ShieldAlert, ShieldCheck, Store } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { api, type Detection as DetectionData } from "../api/client";
import { blockMethod, blockState, formatNumber, formatTime, plural } from "../labels";
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
      .catch(() => setError("The server cannot be reached."));
  }, []);
  useEffect(load, [load]);

  const always = data?.blocked_stores.filter((s) => s.state === "always") ?? [];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Detection</h1>
          <p>How often stores recognise this bot and block it, across every run on this computer.</p>
        </div>
        <div className="page-actions">
          <button type="button" className="icon-button bordered" aria-label="Reload" onClick={load}>
            <RefreshCw size={16} />
          </button>
        </div>
      </header>
      {error && <div className="notice bad">{error}</div>}
      {!data && !error && <p className="muted">Loading…</p>}
      {data && data.visits === 0 && (
        <section className="card empty-card">
          <p className="muted">
            No stores visited yet. <a href="#/">Start scraping</a>.
          </p>
        </section>
      )}
      {data && data.visits > 0 && (
        <>
          <dl className="stats">
            <Tile label="Store visits" icon={<Store size={15} />} value={formatNumber(data.visits)} sub={`${formatNumber(data.stores)} unique stores`} />
            <Tile
              label="Blocked"
              icon={<ShieldAlert size={15} />}
              value={`${percent(data.blocked, data.visits)}%`}
              sub={`${formatNumber(data.blocked)} of ${formatNumber(data.visits)} visits`}
              alert={data.blocked > 0}
            />
            <Tile
              label="Stores that blocked"
              icon={<ShieldAlert size={15} />}
              value={formatNumber(data.stores_blocked)}
              sub={`of ${formatNumber(data.stores)} stores`}
            />
            <Tile
              label="Always block"
              icon={<ShieldCheck size={15} />}
              value={formatNumber(always.length)}
              sub="better skipped"
            />
          </dl>

          {Object.keys(data.by_method).length > 0 && (
            <section className="card">
              <div className="card-head">
                <h2>How stores block</h2>
                <p>A challenge page from an anti-bot service, or an HTTP refusal. The bot never tries to get past it.</p>
              </div>
              <div className="card-body">
                <ul className="chips" aria-label="Block methods">
                  {Object.entries(data.by_method).map(([method, n]) => (
                    <li key={method} className="tag">
                      {blockMethod(method)}: <strong>{formatNumber(n)}</strong>
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          )}

          <section className="card" aria-label="Stores that block">
            <div className="card-head">
              <h2>Stores that block</h2>
              <span className="tag solid">{plural(data.blocked_stores.length, "store")}</span>
              <span className="spacer" />
              {always.length > 0 && <CopyList domains={always.map((s) => s.domain)} />}
              <p>
                <strong>Always</strong>: blocked on every visit. <strong>Sometimes</strong>: blocked on the last visit, got
                through before. <strong>Recovered</strong>: blocked before, got through on the last visit.
              </p>
            </div>
            {data.blocked_stores.length ? (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Store</th>
                      <th>Status</th>
                      <th className="num">Blocked</th>
                      <th>Last method</th>
                      <th>Last visited</th>
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
              <p className="empty">No store has blocked this bot yet.</p>
            )}
          </section>

          <section className="card" aria-label="Blocked per run">
            <div className="card-head">
              <h2>Blocked per run</h2>
              <span className="muted small">last {Math.min(RECENT_RUNS, data.runs.length)} runs</span>
              <p>When the percentage rises, stores recognise this bot more often.</p>
            </div>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Run ID</th>
                    <th>Started</th>
                    <th className="num">Stores</th>
                    <th className="num">Blocked</th>
                    <th>Share</th>
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
      {copied ? "Copied" : `Copy ${plural(domains.length, "store")} that always ${domains.length === 1 ? "blocks" : "block"}`}
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
