import {
  Braces,
  ChevronLeft,
  ChevronRight,
  Database,
  Download,
  FileSpreadsheet,
  FileText,
  RotateCw,
  Square,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { api, ApiError, type PreviewTable, type Rows, type Run } from "../api/client";
import { useRun } from "../api/useRun";
import { DataTable, type Renderers } from "../components/ui/DataTable";
import { JsonView } from "../components/ui/JsonView";
import {
  formatNumber,
  formatTime,
  knitKind,
  runState,
  skipReason,
  storeStatus,
  storeType,
  storeTypeSource,
  tone,
  writerLabel,
} from "../labels";

const LOOK_AT = ["no_products", "js_required", "blocked", "error"];
const TABLES: { key: PreviewTable; label: string; count: (run: Run) => number }[] = [
  { key: "final_stores", label: "Final: toko", count: (r) => r.final_stores },
  { key: "final_products", label: "Final: produk rajut", count: (r) => r.final_products },
  { key: "stores", label: "Toko", count: (r) => r.stores_done },
  { key: "products", label: "Produk", count: (r) => r.products },
  { key: "contacts", label: "Kontak", count: (r) => r.contacts },
  { key: "pages", label: "Halaman", count: (r) => r.pages },
  { key: "inputs", label: "Masukan", count: (r) => r.links_in },
];
const VIEWS: { key: View; label: string }[] = [
  { key: "table", label: "TABEL" },
  { key: "response", label: "JSON" },
  { key: "params", label: "PARAMETER" },
];
const PAGE_SIZE = 50;

const badge = (code: string, label: string) => <span className={`badge badge-${tone(code)}`}>{label}</span>;

// How some columns read in the table view; the JSON view keeps the raw codes.
const RENDERERS: Partial<Record<PreviewTable, Renderers>> = {
  final_stores: {
    store_type: (v) => badge(String(v), storeType(String(v))),
    store_type_source: (v) => storeTypeSource(String(v)),
  },
  final_products: { knit_kind: (v) => knitKind(String(v)) },
  stores: {
    status: (v) => badge(String(v), storeStatus(String(v))),
    store_type: (v) => storeType(String(v ?? "")),
  },
  products: { knit_kind: (v) => knitKind(String(v ?? "")) },
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
  const live = run.state === "running" || run.state === "queued";
  const percent = run.stores_total ? Math.round((100 * run.stores_done) / run.stores_total) : 100;
  const balanced = run.links_in === run.processed + run.skipped;
  const needsLook = run.stores.filter((s) => LOOK_AT.includes(s.status));
  const count = (status: string) => run.status_counts[status] ?? 0;

  return (
    <div className="page">
      <section className="card">
        <div className="card-body">
          <div className="run-head">
            <div>
              <h1>{run.mode === "test" ? `Run terbatas: ${run.limit} toko pertama` : "Run penuh"}</h1>
              <p className="run-meta">
                <span className={`badge badge-${tone(run.state)}`}>{runState(run.state)}</span>
                <span>
                  {run.source_name} · dimulai {formatTime(run.started_at)}
                  {run.finished_at && <> · selesai {formatTime(run.finished_at)}</>}
                </span>
              </p>
              <p className="run-id">{run.run_id}</p>
            </div>
            {live && <StopButton run={run} />}
          </div>

          <div className="progress-head">
            <span>
              Toko dikunjungi: <strong>{formatNumber(run.stores_done)}</strong> dari {formatNumber(run.stores_total)}
            </span>
            <span className="mono">{percent}%</span>
          </div>
          <div
            className="progress"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={run.stores_total}
            aria-valuenow={run.stores_done}
            aria-label="Progres run"
          >
            <div className={`progress-bar ${live ? "live" : ""}`} style={{ width: `${percent}%` }} />
          </div>
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
        </div>
      </section>

      {connectionError && <div className="notice warn">{connectionError}</div>}
      {run.state === "failed" && (
        <div className="notice bad" role="alert">
          Run gagal: {run.error || "lihat log server"}.
        </div>
      )}
      {(run.state === "interrupted" || run.state === "stopped") && <ResumeNotice run={run} onRestart={onRestart} />}

      <dl className="stats">
        <Stat label="Toko" value={run.stores_done} sub={`dari ${formatNumber(run.stores_total)} target`} />
        <Stat
          label="Daftar final"
          value={run.final_stores}
          sub={`toko multi-brand, ${formatNumber(run.final_products)} produk rajut`}
        />
        <Stat label="Produk" value={run.products} sub="ditemukan" />
        <Stat label="Kontak" value={run.contacts} sub={`dari ${formatNumber(run.pages)} halaman`} />
        <Stat label="Diblokir" value={count("blocked")} sub="toko menolak akses" alert={count("blocked") > 0} />
        <Stat label="Gagal" value={count("error")} sub="galat saat mengambil" alert={count("error") > 0} />
      </dl>

      {needsLook.length > 0 && (
        <section className="card" aria-label="Perlu dilihat">
          <div className="card-head">
            <span className="label">Perlu dilihat</span>
            <span className="tag solid">{formatNumber(needsLook.length)} toko</span>
          </div>
          <ul className="look-list">
            {needsLook.map((s) => (
              <li key={s.domain}>
                <div>
                  <strong title={s.domain}>{s.domain}</strong>
                  {s.error && <small title={s.error}>{s.error}</small>}
                </div>
                {badge(s.status, storeStatus(s.status))}
              </li>
            ))}
          </ul>
        </section>
      )}

      <ResultCard run={run} />

      {finished && run.downloads.length > 0 && <Downloads run={run} />}
    </div>
  );
}

function StopButton({ run }: { run: Run }) {
  const [asked, setAsked] = useState(false);
  return (
    <button
      type="button"
      className="button ghost"
      disabled={asked}
      onClick={() => {
        setAsked(true);
        api.stopRun(run.run_id).catch(() => setAsked(false));
      }}
    >
      <Square size={13} /> {asked ? "Menghentikan…" : "Hentikan"}
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
      <button type="button" className="button" onClick={resume} disabled={busy}>
        <RotateCw size={14} /> {busy ? "Melanjutkan…" : "Lanjutkan"}
      </button>
      {error && <span role="alert">{error}</span>}
    </div>
  );
}

function Stat({ label, value, sub, alert = false }: { label: string; value: number; sub: string; alert?: boolean }) {
  return (
    <div className={`stat ${alert ? "alert" : ""}`}>
      <dt>{label}</dt>
      <dd>{formatNumber(value)}</dd>
      <p className="sub">{sub}</p>
    </div>
  );
}

const FILE_ICONS: Record<string, ReactNode> = {
  xlsx: <FileSpreadsheet size={18} />,
  json: <Braces size={18} />,
  jsonl: <Braces size={18} />,
  parquet: <Database size={18} />,
  sqlite: <Database size={18} />,
  duckdb: <Database size={18} />,
};

function Downloads({ run }: { run: Run }) {
  return (
    <section className="card" aria-label="Unduh hasil">
      <div className="card-head">
        <h2>Unduh hasil</h2>
        <p>File hasil run ini, sama dengan isi foldernya di komputer ini.</p>
      </div>
      <ul className="download-list">
        {run.downloads.map((d) => (
          <li key={d.key}>
            <a
              className="download-row"
              href={api.downloadUrl(run.run_id, d.key)}
              download={d.filename}
              aria-label={`Unduh ${d.label}`}
            >
              {FILE_ICONS[d.key] ?? <FileText size={18} />}
              <span>
                <strong>{d.filename}</strong>
                <small>{d.label}</small>
              </span>
              <span className="icon-button" aria-hidden="true">
                <Download size={16} />
              </span>
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}

type View = "table" | "response" | "params";

function ResultCard({ run }: { run: Run }) {
  const [table, setTable] = useState<PreviewTable>("final_stores");
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
        <h2>Data hasil</h2>
        <span className="muted small result-title">{run.source_name}</span>
        <span className="spacer" />
        {run.writers.map((w) => (
          <span key={w} className="tag">
            {writerLabel(w)}
          </span>
        ))}
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
              {t.label} <small>({formatNumber(t.count(run))})</small>
            </button>
          ))}
        </div>
        <span className="spacer" />
        <div className="segmented" role="tablist" aria-label="Tampilan">
          {VIEWS.map((v) => (
            <button key={v.key} type="button" role="tab" aria-selected={view === v.key} onClick={() => setView(v.key)}>
              {v.label}
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
