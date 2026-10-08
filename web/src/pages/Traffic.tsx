import { Activity, Monitor, RefreshCw, Server, ShoppingCart } from "lucide-react";
import { useCallback, useEffect, useState, type KeyboardEvent, type ReactNode } from "react";

import { ApiError, api, type Traffic as TrafficData, type TrafficPeriod } from "../api/client";
import {
  formatNumber,
  trafficCityKind,
  trafficDevice,
  trafficPeriod,
  trafficProblem,
  trafficSource,
} from "../labels";

const PERIODS: TrafficPeriod[] = ["1h", "24h", "7d"];
const POLL_MS = 30_000;
const STALE_MS = 3 * 60_000;
// With about 5% of sessions adding to cart, 50 sessions and none is under a 1 in 20 chance
// for real shoppers: likely automated.
const COLD_SESSIONS = 50;
const PERIOD_KEY = "traffic-period";

function savedPeriod(): TrafficPeriod {
  try {
    const p = localStorage.getItem(PERIOD_KEY);
    if (p && (PERIODS as string[]).includes(p)) return p as TrafficPeriod;
  } catch {
    // storage blocked: use the default
  }
  return "24h";
}

const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const hm = (iso: string) => new Date(iso).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
const pct = (part: number, whole: number) =>
  whole ? `${(Math.round((1000 * part) / whole) / 10).toLocaleString("id-ID")}%` : "–";

/** Sessions on our own Shopify store, refreshed every 30 seconds while the page is open. */
export function Traffic() {
  const [period, setPeriod] = useState<TrafficPeriod>(savedPeriod);
  const [data, setData] = useState<TrafficData | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const load = useCallback(() => {
    api
      .traffic(period)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: unknown) =>
        setError(e instanceof ApiError ? e : new ApiError(0, "unreachable", "Server tidak bisa dihubungi.")),
      );
  }, [period]);

  useEffect(() => {
    load();
    const timer = window.setInterval(() => {
      setNow(Date.now());
      if (document.visibilityState === "visible") load();
    }, POLL_MS);
    const onVisible = () => document.visibilityState === "visible" && load();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [load]);

  const choose = (p: TrafficPeriod) => {
    setPeriod(p);
    try {
      localStorage.setItem(PERIOD_KEY, p);
    } catch {
      // not remembered; fine
    }
  };

  const shown = data && data.period === period ? data : null;
  const live = data && now - Date.parse(data.minutes_at) < STALE_MS && !error;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Traffic toko</h1>
          <p>
            Pengunjung {data ? <span className="mono">{data.shop}</span> : "toko kita"} dari Shopify Analytics. Diperbarui
            otomatis setiap 30 detik.
          </p>
        </div>
        <div className="page-actions">
          <span className={`live-pill ${live ? "on" : ""}`} role="status" aria-live="polite">
            {data ? `${live ? "Live" : "Tertunda"} · ${clock(data.minutes_at)}` : "Menyambungkan…"}
          </span>
          <button type="button" className="icon-button bordered" aria-label="Muat ulang" onClick={load}>
            <RefreshCw size={16} />
          </button>
        </div>
      </header>

      {error && <div className="notice bad">{error.message}</div>}
      {data?.problem && <div className="notice warn">{trafficProblem(data.problem)}</div>}

      {data && (
        <div className="traffic-bar">
          <div className="segmented" role="tablist" aria-label="Rentang waktu">
            {PERIODS.map((p) => (
              <button key={p} type="button" role="tab" aria-selected={period === p} onClick={() => choose(p)}>
                {trafficPeriod(p)}
              </button>
            ))}
          </div>
          <span className="muted small">
            Grafik dan tabel untuk {trafficPeriod(period)} terakhir · diperbarui setiap 5 menit · terakhir{" "}
            {clock(data.breakdown_at)}
          </span>
        </div>
      )}

      {data && <SessionChart data={shown ?? data} />}

      {data && (
        <dl className="stats">
          <Tile
            label="Sesi 60 menit"
            icon={<Activity size={15} />}
            value={formatNumber(data.minutes.reduce((sum, m) => sum + m.sessions, 0))}
            sub={`Puncak ${formatNumber(Math.max(0, ...data.minutes.map((m) => m.sessions)))} sesi per menit`}
          />
          <Tile
            label={`Sesi ${trafficPeriod(period)}`}
            icon={<Monitor size={15} />}
            value={shown ? formatNumber(shown.totals.sessions) : "…"}
            sub={shown ? `${formatNumber(shown.totals.checkout_sessions)} sampai checkout` : "Memuat…"}
          />
          <Tile
            label="Tambah ke keranjang"
            icon={<ShoppingCart size={15} />}
            value={shown ? formatNumber(shown.totals.cart_sessions) : "…"}
            sub={shown ? `${pct(shown.totals.cart_sessions, shown.totals.sessions)} dari sesi` : "Memuat…"}
          />
          <Tile
            label="Dari kota data center"
            icon={<Server size={15} />}
            value={shown ? formatNumber(shown.data_center_sessions) : "…"}
            sub={shown ? `Dugaan bot · ${pct(shown.data_center_sessions, shown.totals.sessions)} dari sesi` : "Memuat…"}
            alert
          />
        </dl>
      )}

      {shown && (
        <div className="traffic-grid">
          <CityTable data={shown} />
          <div className="traffic-stack">
            <ShareCard title="Sumber kunjungan" items={shown.sources} label={trafficSource} />
            <ShareCard title="Perangkat" items={shown.devices} label={trafficDevice} />
          </div>
        </div>
      )}
      {shown && <PageTable data={shown} />}

      <section className="card">
        <div className="card-head">
          <h2>Yang tidak terlihat di sini</h2>
          <p>
            Shopify hanya mencatat pengunjung yang membuka halaman di browser. Bot yang mengambil{" "}
            <span className="mono">/products.json</span> langsung tidak pernah tercatat sebagai sesi. Label "kota data
            center" adalah tebakan: kota-kota itu lokasi server Google, AWS, Microsoft atau Meta.
          </p>
        </div>
      </section>
    </div>
  );
}

function Tile({
  label,
  icon,
  value,
  sub,
  alert = false,
}: {
  label: string;
  icon: ReactNode;
  value: string;
  sub: string;
  alert?: boolean;
}) {
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

const CHART_H = 200;

function niceTop(peak: number): number {
  if (peak <= 10) return Math.max(2, Math.ceil(peak / 2) * 2);
  const step = 10 ** Math.floor(Math.log10(peak));
  for (const m of [1, 2, 5, 10]) if (m * step >= peak) return m * step;
  return 10 * step;
}
const PAD = { top: 12, right: 12, bottom: 24, left: 34 };

/** Keeps an SVG in step with its container's width, so text is never stretched. */
function useWidth<T extends HTMLElement>(): [(el: T | null) => void, number] {
  const [el, setEl] = useState<T | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!el) return;
    const update = () => setWidth(el.clientWidth);
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [el]);
  return [setEl, width];
}

const dayHour = (iso: string) =>
  new Date(iso).toLocaleString("id-ID", { weekday: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const day = (iso: string) => new Date(iso).toLocaleDateString("id-ID", { weekday: "short", day: "numeric" });

/** Sessions over the chosen period, as a line; the last point is still running (dashed). */
function SessionChart({ data }: { data: TrafficData }) {
  const minutes = data.series;
  const perMinute = data.series_grain === "minute";
  const week = data.period === "7d";
  const tickLabel = week ? day : hm;
  const tipLabel = week ? dayHour : hm;
  const unit = perMinute ? "menit" : "jam";
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const peak = Math.max(0, ...minutes.map((m) => m.sessions));
  const top = niceTop(peak);
  const last = minutes.length - 1;
  const plotW = Math.max(0, width - PAD.left - PAD.right);
  const plotH = CHART_H - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (last > 0 ? (i / last) * plotW : 0);
  const y = (v: number) => PAD.top + plotH - (v / top) * plotH;
  const pts = minutes.map((m, i) => [x(i), y(m.sessions)] as const);
  const settled = pts.slice(0, Math.max(1, last));
  const line = settled.map(([px, py], i) => `${i ? "L" : "M"}${px.toFixed(1)},${py.toFixed(1)}`).join("");
  const area = settled.length ? `${line}L${x(settled.length - 1).toFixed(1)},${y(0)}L${x(0).toFixed(1)},${y(0)}Z` : "";
  const running = last > 0 ? pts.slice(last - 1) : [];
  // Evenly spaced time labels; fewer on narrow screens so they never touch "sekarang".
  const count = plotW < 420 ? 2 : 4;
  const ticks = Array.from({ length: count }, (_, k) => Math.round((k * last) / count)).filter(
    (i, k, all) => i < last * 0.85 && all.indexOf(i) === k,
  );

  const pick = (clientX: number, box: DOMRect) => {
    if (last < 0 || plotW <= 0) return;
    const i = Math.round(((clientX - box.left - PAD.left) / plotW) * last);
    setHover(Math.min(last, Math.max(0, i)));
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    setHover((h) => Math.min(last, Math.max(0, (h ?? last) + (e.key === "ArrowLeft" ? -1 : 1))));
  };
  const shown = hover !== null ? minutes[hover] : undefined;
  const total = minutes.reduce((sum, m) => sum + m.sessions, 0);

  return (
    <section className="card" aria-label="Grafik sesi">
      <div className="card-head">
        <h2>Sesi per {unit}</h2>
        <span className="muted small">{trafficPeriod(data.period)} terakhir</span>
        <p>
          Garis putus-putus di ujung kanan adalah {unit} yang sedang berjalan. Arahkan kursor atau pakai tombol panah
          untuk detail.
        </p>
      </div>
      {minutes.length ? (
        <div
          className="line-chart"
          ref={ref}
          tabIndex={0}
          role="img"
          aria-label={`Sesi per ${unit} selama ${trafficPeriod(data.period)} terakhir: total ${formatNumber(total)}, puncak ${formatNumber(peak)} per ${unit}.`}
          onKeyDown={onKey}
          onBlur={() => setHover(null)}
        >
          {width > 0 && (
            <svg
              width={width}
              height={CHART_H}
              viewBox={`0 0 ${width} ${CHART_H}`}
              onPointerMove={(e) => pick(e.clientX, e.currentTarget.getBoundingClientRect())}
              onPointerLeave={() => setHover(null)}
              aria-hidden="true"
            >
              {[0, top / 2, top].map((v) => (
                <g key={v}>
                  <line className="lc-grid" x1={PAD.left} x2={PAD.left + plotW} y1={y(v)} y2={y(v)} />
                  <text className="lc-axis" x={PAD.left - 8} y={y(v)} dy="0.32em" textAnchor="end">
                    {v}
                  </text>
                </g>
              ))}
              {ticks.map((i) => (
                <text key={i} className="lc-axis" x={x(i)} y={CHART_H - 6} textAnchor="middle">
                  {tickLabel(minutes[i]?.at ?? "")}
                </text>
              ))}
              <text className="lc-axis" x={x(last)} y={CHART_H - 6} textAnchor="end">
                sekarang
              </text>
              <path className="lc-area" d={area} />
              <path className="lc-line" d={line} />
              {running.length === 2 && (
                <path
                  className="lc-line lc-running"
                  d={`M${running[0]![0].toFixed(1)},${running[0]![1].toFixed(1)}L${running[1]![0].toFixed(1)},${running[1]![1].toFixed(1)}`}
                />
              )}
              {settled.length > 0 && (
                <circle className="lc-end" cx={settled[settled.length - 1]![0]} cy={settled[settled.length - 1]![1]} r={4} />
              )}
              {hover !== null && pts[hover] && (
                <g>
                  <line className="lc-cross" x1={pts[hover][0]} x2={pts[hover][0]} y1={PAD.top} y2={PAD.top + plotH} />
                  <circle className="lc-dot" cx={pts[hover][0]} cy={pts[hover][1]} r={5} />
                </g>
              )}
            </svg>
          )}
          {shown && hover !== null && pts[hover] && (
            <div
              className="chart-tip line-tip"
              role="status"
              style={{ left: Math.min(Math.max(pts[hover][0], 80), width - 80), top: Math.max(pts[hover][1] - 12, 0) }}
            >
              <strong>{formatNumber(shown.sessions)} sesi</strong>
              {tipLabel(shown.at)}
              {hover === last ? " · masih berjalan" : ""}
            </div>
          )}
        </div>
      ) : (
        <p className="empty">Belum ada sesi dalam 60 menit terakhir.</p>
      )}
    </section>
  );
}

function CityTable({ data }: { data: TrafficData }) {
  return (
    <section className="card" aria-label="Asal kota">
      <div className="card-head">
        <h2>Asal kota</h2>
        <span className="muted small">25 kota teratas</span>
      </div>
      {data.cities.length ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Kota</th>
                <th className="num">Sesi</th>
                <th className="num">Keranjang</th>
              </tr>
            </thead>
            <tbody>
              {data.cities.map((c) => {
                const cold = c.kind !== "own_team" && c.sessions >= COLD_SESSIONS && c.cart_sessions === 0;
                return (
                  <tr key={`${c.city}|${c.country}`}>
                    <td>
                      <span className="traffic-place">
                        {c.city || <span className="muted">(kota tidak diketahui)</span>}
                        <span className="muted small">{c.country}</span>
                        {c.kind === "data_center" && <span className="badge badge-warn">{trafficCityKind(c.kind)}</span>}
                        {c.kind === "own_team" && <span className="badge badge-neutral">{trafficCityKind(c.kind)}</span>}
                        {cold && <span className="badge badge-bad">Banyak sesi, 0 keranjang</span>}
                      </span>
                    </td>
                    <td className="num">{formatNumber(c.sessions)}</td>
                    <td className="num">{formatNumber(c.cart_sessions)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="empty">Belum ada sesi di rentang ini.</p>
      )}
    </section>
  );
}

function ShareCard({
  title,
  items,
  label,
}: {
  title: string;
  items: { name: string; sessions: number }[];
  label: (code: string) => string;
}) {
  const total = items.reduce((sum, i) => sum + i.sessions, 0);
  const max = Math.max(1, ...items.map((i) => i.sessions));
  return (
    <section className="card" aria-label={title}>
      <div className="card-head">
        <h2>{title}</h2>
      </div>
      {items.length ? (
        <ul className="share-list">
          {items.map((i) => (
            <li key={i.name}>
              <span>{label(i.name)}</span>
              <span className="share-track" aria-hidden="true">
                <span className="share-fill" style={{ width: `${(100 * i.sessions) / max}%` }} />
              </span>
              <span className="num">
                {formatNumber(i.sessions)} · {pct(i.sessions, total)}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="empty">Belum ada sesi di rentang ini.</p>
      )}
    </section>
  );
}

function PageTable({ data }: { data: TrafficData }) {
  return (
    <section className="card" aria-label="Halaman pertama yang dibuka">
      <div className="card-head">
        <h2>Halaman pertama yang dibuka</h2>
        <span className="muted small">12 halaman teratas</span>
      </div>
      {data.pages.length ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Halaman</th>
                <th className="num">Sesi</th>
                <th className="num">Keranjang</th>
              </tr>
            </thead>
            <tbody>
              {data.pages.map((p) => (
                <tr key={p.path}>
                  <td className="mono traffic-path" title={p.path}>
                    {p.path || "(tidak diketahui)"}
                  </td>
                  <td className="num">{formatNumber(p.sessions)}</td>
                  <td className="num">{formatNumber(p.cart_sessions)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="empty">Belum ada sesi di rentang ini.</p>
      )}
    </section>
  );
}
