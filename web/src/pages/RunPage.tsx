import { ChevronLeft, ChevronRight, Download, Play, RotateCw, Square } from "lucide-react";
import { useEffect, useState } from "react";

import { api, ApiError, type PreviewTable, type Rows, type Run } from "../api/client";
import { useRun } from "../api/useRun";
import { DataTable, type Renderers } from "../components/ui/DataTable";
import { JsonView } from "../components/ui/JsonView";
import { Menu } from "../components/ui/Menu";
import { formatNumber, formatTime, runState, skipReason, storeStatus, tone, writerLabel } from "../labels";
import { navigate } from "../router";

const LOOK_AT = ["no_products", "js_required", "blocked", "error"];
const TABLES: { key: PreviewTable; label: string }[] = [
  { key: "stores", label: "STORES" },
  { key: "products", label: "PRODUCTS" },
  { key: "contacts", label: "CONTACTS" },
  { key: "pages", label: "PAGES" },
  { key: "inputs", label: "INPUTS" },
];
const PAGE_SIZE = 50;

const badge = (code: string, label: string) => <span className={`badge badge-${tone(code)}`}>{label}</span>;

// How some columns read in the table view; the RESPONSE view keeps the raw codes.
const RENDERERS: Partial<Record<PreviewTable, Renderers>> = {
  stores: { status: (v) => badge(String(v), storeStatus(String(v))) },
  inputs: {
    status: (v) => (v === "processed" ? badge("ok", "Diproses") : badge("neutral", skipReason(String(v)))),
  },
};

export function RunPage({ runId }: { runId: string }) {
  const [nonce, setNonce] = useState(0); // bumped to reconnect after a resume
  const { run, error } = useRun(runId, nonce);
  if (!run) {
    return (
      <div className="page">
        <p className={error ? "notice bad" : "mono muted"}>{error || "Memuat run…"}</p>
      </div>
    );
  }
  return <RunDetail run={run} connectionError={error} onRestart={() => setNonce((n) => n + 1)} />;
}

export function RunDetail({
  run,
  connectionError,
  onRestart,
}: {
  run: Run;
  connectionError?: string;
  onRestart?: () => void;
}) {
  const finished = run.state === "done";
  const percent = run.stores_total ? Math.round((100 * run.stores_done) / run.stores_total) : 100;
  const balanced = run.links_in === run.processed + run.skipped;
  const needsLook = run.stores.filter((s) => LOOK_AT.includes(s.status));

  return (
    <div className="page">
      <header className="page-head">
        <h1>
          {run.mode === "test" ? `Run uji: ${run.limit} toko pertama` : "Run penuh"}{" "}
          <span className={`badge badge-${tone(run.state)}`}>{runState(run.state)}</span>
        </h1>
        <p className="mono muted">
          {run.source_name} · dimulai {formatTime(run.started_at)}
          {run.finished_at && <> · selesai {formatTime(run.finished_at)}</>} · {run.run_id}
        </p>
      </header>

      {connectionError && <div className="notice warn">{connectionError}</div>}
      {run.state === "failed" && (
        <div className="notice bad" role="alert">
          Run gagal: {run.error || "lihat log server"}.
        </div>
      )}
      {(run.state === "interrupted" || run.state === "stopped") && (
        <ResumeNotice run={run} onRestart={onRestart} />
      )}

      <section className="card">
        <div className="card-body">
          <div className="progress-head mono">
            {(run.state === "running" || run.state === "queued") && <StopButton run={run} />}
            <span>
              Toko dikunjungi: <strong>{formatNumber(run.stores_done)}</strong> dari {formatNumber(run.stores_total)}
            </span>
            <span>{percent}%</span>
          </div>
          <div
            className="progress"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={run.stores_total}
            aria-valuenow={run.stores_done}
            aria-label="Progres run"
          >
            <div className={`progress-bar ${finished ? "" : "live"}`} style={{ width: `${percent}%` }} />
          </div>
          <dl className="stats">
            <Stat label="Produk" value={run.products} />
            <Stat label="Halaman" value={run.pages} />
            <Stat label="Kontak" value={run.contacts} />
            <Stat label="Toko" value={run.stores_done} />
          </dl>
          <p className={`reconcile mono ${balanced ? "good" : "bad"}`} data-testid="reconciliation">
            Tautan masuk <strong>{formatNumber(run.links_in)}</strong> = diproses <strong>{formatNumber(run.processed)}</strong> +
            dilewati <strong>{formatNumber(run.skipped)}</strong> {balanced ? "✓ seimbang" : "✗ tidak seimbang"}
          </p>
          {Object.keys(run.skipped_by_reason).length > 0 && (
            <ul className="chips" aria-label="Tautan yang dilewati">
              {Object.entries(run.skipped_by_reason).map(([reason, n]) => (
                <li key={reason} className="tag">
                  {skipReason(reason)}: {formatNumber(n)}
                </li>
              ))}
            </ul>
          )}
          {finished && needsLook.length > 0 && (
            <div className="look">
              <p className="mono small muted">PERLU DILIHAT</p>
              <ul>
                {needsLook.map((s) => (
                  <li key={s.domain}>
                    <strong>{s.domain}</strong>: {storeStatus(s.status)}
                    {s.error && <span className="muted"> ({s.error})</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </section>

      {finished && run.mode === "test" && <ContinueFullRun run={run} />}

      <ResultCard run={run} />
    </div>
  );
}

function StopButton({ run }: { run: Run }) {
  const [asked, setAsked] = useState(false);
  return (
    <button
      type="button"
      className="button ghost small-button"
      disabled={asked}
      onClick={() => {
        setAsked(true);
        api.stopRun(run.run_id).catch(() => setAsked(false));
      }}
    >
      <Square size={12} /> {asked ? "MENGHENTIKAN…" : "STOP"}
    </button>
  );
}

function ResumeNotice({ run, onRestart }: { run: Run; onRestart?: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function resume() {
    setBusy(true);
    setError("");
    try {
      await api.resumeRun(run.run_id);
      onRestart?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Server tidak bisa dihubungi.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="notice warn">
      <span>
        {run.state === "stopped" ? "Run dihentikan" : "Run terhenti sebelum selesai (server dimatikan?)"}:{" "}
        {formatNumber(run.stores_done)} dari {formatNumber(run.stores_total)} toko selesai dan tersimpan.
      </span>
      <span className="spacer" />
      <button type="button" className="button primary" onClick={resume} disabled={busy}>
        <RotateCw size={14} /> {busy ? "MELANJUTKAN…" : "LANJUTKAN"}
      </button>
      {error && <span role="alert">{error}</span>}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="stat">
      <dt className="mono">{label}</dt>
      <dd>{formatNumber(value)}</dd>
    </div>
  );
}

function ContinueFullRun({ run }: { run: Run }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function start() {
    setBusy(true);
    setError("");
    try {
      const full = await api.startFullRun(run.run_id);
      navigate(`/runs/${full.run_id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Server tidak bisa dihubungi.");
      setBusy(false);
    }
  }

  return (
    <section className="card callout">
      <div className="card-body">
        <h2 className="mono">Periksa hasil uji, lalu lanjutkan</h2>
        <ol>
          <li>Rekonsiliasi di atas harus seimbang.</li>
          <li>Toko yang Anda tahu punya katalog harus berstatus “Ada produk”.</li>
          <li>Buka tab PRODUCTS atau file Excel: judul, harga dan mata uang harus sama dengan situsnya.</li>
        </ol>
        <button type="button" className="button primary" onClick={start} disabled={busy}>
          <Play size={14} /> {busy ? "MEMULAI…" : `Jalankan seluruh daftar (${formatNumber(run.links_in)} tautan)`}
        </button>
        {error && (
          <div className="notice bad" role="alert">
            {error}
          </div>
        )}
      </div>
    </section>
  );
}

type View = "table" | "response" | "params";

function ResultCard({ run }: { run: Run }) {
  const [table, setTable] = useState<PreviewTable>("stores");
  const [view, setView] = useState<View>("table");
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<Rows | null>(null);
  const [error, setError] = useState("");

  // Reload when the table, the page, or the run's progress changes.
  useEffect(() => {
    let cancelled = false;
    api
      .rows(run.run_id, table, offset, PAGE_SIZE)
      .then((r) => !cancelled && (setRows(r), setError("")))
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e.message : "Gagal memuat data."));
    return () => {
      cancelled = true;
    };
  }, [run.run_id, table, offset, run.stores_done, run.state]);

  const switchTable = (key: PreviewTable) => {
    setTable(key);
    setOffset(0);
    setRows(null);
  };
  const from = rows && rows.total ? offset + 1 : 0;
  const to = rows ? Math.min(offset + PAGE_SIZE, rows.total) : 0;

  return (
    <section className="card result" aria-label="Hasil">
      <div className="card-head">
        <span className="mono result-title">{run.source_name}</span>
        <span className="spacer" />
        {run.writers.map((w) => (
          <span key={w} className="tag">
            {writerLabel(w)}
          </span>
        ))}
        <span className="tag">
          {formatNumber(run.stores_done)}/{formatNumber(run.stores_total)} toko
        </span>
        {run.state === "done" ? (
          <Menu className="button ghost" align="right" icon={<Download size={14} />} label="DOWNLOAD" ariaLabel="Unduh hasil">
            <p className="menu-title">Unduh hasil</p>
            {run.downloads.map((d) => (
              <a key={d.key} className="menu-item" href={api.downloadUrl(run.run_id, d.key)} download={d.filename}>
                {d.label}
              </a>
            ))}
          </Menu>
        ) : (
          <span className="tag muted">menunggu selesai…</span>
        )}
      </div>

      <div className="tabs-row">
        <div className="tabs" role="tablist" aria-label="Tabel">
          {TABLES.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={table === t.key && view !== "params"}
              onClick={() => {
                switchTable(t.key);
                if (view === "params") setView("table");
              }}
            >
              {t.label}
            </button>
          ))}
        </div>
        <span className="spacer" />
        <div className="segmented" role="tablist" aria-label="Tampilan">
          {(["table", "response", "params"] as View[]).map((v) => (
            <button key={v} type="button" role="tab" aria-selected={view === v} onClick={() => setView(v)}>
              {v === "table" ? "TABLE" : v === "response" ? "RESPONSE" : "PARAMS"}
            </button>
          ))}
        </div>
      </div>

      <div className="result-body">
        {error && <div className="notice bad">{error}</div>}
        {view === "params" ? (
          <>
            <pre className="cli">{run.cli}</pre>
            <JsonView value={run.config} filename={`${run.run_id}-params.json`} />
          </>
        ) : !rows ? (
          <p className="empty mono">Memuat…</p>
        ) : view === "table" ? (
          <DataTable columns={rows.columns} rows={rows.rows} renderers={RENDERERS[table]} hidden={["run_id"]} />
        ) : (
          <JsonView
            value={rows.rows}
            filename={`${run.run_id}-${table}-${from}-${to}.json`}
            note={rows.truncated_fields ? "teks panjang dipotong di pratinjau; file unduhan berisi semuanya" : undefined}
          />
        )}
      </div>

      {view !== "params" && rows && rows.total > 0 && (
        <div className="pager mono">
          <span>
            {formatNumber(from)}–{formatNumber(to)} dari {formatNumber(rows.total)}
          </span>
          <button
            type="button"
            className="icon-button"
            aria-label="Halaman sebelumnya"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            <ChevronLeft size={16} />
          </button>
          <button
            type="button"
            className="icon-button"
            aria-label="Halaman berikutnya"
            disabled={to >= rows.total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      )}
    </section>
  );
}
