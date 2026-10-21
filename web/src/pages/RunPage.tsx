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

import { api, ApiError, FINISHED, type PreviewTable, type Rows, type Run, type Scorecard } from "../api/client";
import { useRun } from "../api/useRun";
import { DataTable, type Renderers } from "../components/ui/DataTable";
import { JsonView } from "../components/ui/JsonView";
import {
  formatNumber,
  formatTime,
  formatUsd,
  knitKind,
  plural,
  runState,
  skipReason,
  storeStatus,
  storeType,
  storeTypeSource,
  tone,
  writerLabel,
} from "../labels";

const LOOK_AT = ["no_products", "js_required", "blocked", "rate_limited", "error"];
const TABLES: { key: PreviewTable; label: string; count: (run: Run) => number }[] = [
  { key: "final_stores", label: "Final: stores", count: (r) => r.final_stores },
  { key: "final_products", label: "Final: knitwear products", count: (r) => r.final_products },
  { key: "knit_products", label: "Knitwear (all stores)", count: (r) => r.knit_products },
  { key: "stores", label: "Stores", count: (r) => r.stores_done },
  { key: "products", label: "Products", count: (r) => r.products },
  { key: "contacts", label: "Contacts", count: (r) => r.contacts },
  { key: "pages", label: "Pages", count: (r) => r.pages },
  { key: "inputs", label: "Inputs", count: (r) => r.links_in },
];
const VIEWS: { key: View; label: string }[] = [
  { key: "table", label: "TABLE" },
  { key: "response", label: "JSON" },
  { key: "params", label: "PARAMETERS" },
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
  knit_products: {
    knit_kind: (v) => knitKind(String(v)),
    store_type: (v) => storeType(String(v ?? "")),
  },
  stores: {
    status: (v) => badge(String(v), storeStatus(String(v))),
    store_type: (v) => storeType(String(v ?? "")),
  },
  products: { knit_kind: (v) => knitKind(String(v ?? "")) },
  inputs: {
    status: (v) => (v === "processed" ? badge("ok", "Processed") : badge("neutral", skipReason(String(v)))),
  },
};

export function RunPage({ runId }: { runId: string }) {
  const [nonce, setNonce] = useState(0); // bumped to reconnect after a resume
  const { run, error } = useRun(runId, nonce);
  const [quality, setQuality] = useState<Scorecard | null>(null);
  // For a run on stores the bot found itself: how far to trust that search. Asked once
  // the run has stopped; a run started from links has none (404), which is not an error.
  const settled = run ? FINISHED.includes(run.state) : false;
  useEffect(() => {
    setQuality(null);
    if (!settled) return;
    let cancelled = false;
    api
      .runQuality(runId)
      .then((q) => !cancelled && setQuality(q))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [runId, settled]);
  if (!run) {
    return (
      <div className="page">
        <p className={error ? "notice bad" : "mono muted"}>{error || "Loading the run…"}</p>
      </div>
    );
  }
  return <RunDetail run={run} quality={quality} connectionError={error} onRestart={() => setNonce((n) => n + 1)} />;
}

export function RunDetail({
  run,
  quality,
  connectionError,
  onRestart,
}: {
  run: Run;
  quality?: Scorecard | null; // only for a run whose stores came from a search
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
              <h1>{run.mode === "test" ? `Limited run: first ${run.limit} stores` : "Full run"}</h1>
              <p className="run-meta">
                <span className={`badge badge-${tone(run.state)}`}>{runState(run.state)}</span>
                <span>
                  {run.source_name} · started {formatTime(run.started_at)}
                  {run.finished_at && <> · finished {formatTime(run.finished_at)}</>}
                </span>
              </p>
              <p className="run-id">{run.run_id}</p>
            </div>
            {live && <StopButton run={run} />}
          </div>

          <div className="progress-head">
            <span>
              Stores visited: <strong>{formatNumber(run.stores_done)}</strong> of {formatNumber(run.stores_total)}
            </span>
            <span className="mono">{percent}%</span>
          </div>
          <div
            className="progress"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={run.stores_total}
            aria-valuenow={run.stores_done}
            aria-label="Run progress"
          >
            <div className={`progress-bar ${live ? "live" : ""}`} style={{ width: `${percent}%` }} />
          </div>
          <p className={`reconcile mono ${balanced ? "good" : "bad"}`} data-testid="reconciliation">
            Links in <strong>{formatNumber(run.links_in)}</strong> = processed <strong>{formatNumber(run.processed)}</strong> +
            skipped <strong>{formatNumber(run.skipped)}</strong> {balanced ? "✓ balanced" : "✗ not balanced"}
          </p>
          {(run.skipped_by_reason.over_limit ?? 0) > 0 && (
            <div className="notice warn" role="status" data-testid="limited">
              <strong>
                Only the first {plural(run.limit ?? run.stores_total, "store")} of this list were visited, on purpose.
              </strong>{" "}
              This run was started from the command line with a limit (<code>--limit {run.limit}</code>), so the other{" "}
              {plural(run.skipped_by_reason.over_limit ?? 0, "link")} were left out: nothing went wrong with them. Runs
              started from this interface have no limit and process every link. To read the rest, start a run on the same
              list without the limit.
            </div>
          )}
          {Object.keys(run.skipped_by_reason).length > 0 && (
            <ul className="chips" aria-label="Skipped links">
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
          The run failed: {run.error || "see the server log"}.
        </div>
      )}
      {(run.state === "interrupted" || run.state === "stopped") && <ResumeNotice run={run} onRestart={onRestart} />}

      <dl className="stats">
        <Stat label="Stores" value={run.stores_done} sub={`of ${formatNumber(run.stores_total)} targeted`} />
        <Stat
          label="Final list"
          value={run.final_stores}
          sub={`multi-brand stores, ${formatNumber(run.final_products)} knitwear products`}
        />
        <Stat label="Products" value={run.products} sub="found" />
        <Stat label="Contacts" value={run.contacts} sub={`from ${formatNumber(run.pages)} pages`} />
        <Stat label="Blocked" value={count("blocked")} sub="stores refused access" alert={count("blocked") > 0} />
        <Stat label="Failed" value={count("error")} sub="errors while fetching" alert={count("error") > 0} />
      </dl>

      {run.reused_stores > 0 && (
        <div className="notice info" role="status" data-testid="reused">
          <strong>
            {formatNumber(run.reused_stores)} of {plural(run.stores_total, "store")} loaded, not scraped again:
          </strong>{" "}
          a run read them in the last {formatNumber(run.reuse_days)} days, so their data comes from that run (no
          requests, no LLM cost). To refresh them, start a new run with "Scrape them again anyway".
        </div>
      )}

      {run.llm_model && (
        <p className="muted small" data-testid="llm-cost">
          LLM: {run.llm_model} read {plural(run.llm_stores, "store")} for about{" "}
          <strong>{formatUsd(run.llm_cost_usd)}</strong> (estimated from token prices).
        </p>
      )}

      {needsLook.length > 0 && (
        <section className="card" aria-label="Needs a look">
          <div className="card-head">
            <span className="label">Needs a look</span>
            <span className="tag solid">{plural(needsLook.length, "store")}</span>
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

      {quality && <QualityCard quality={quality} />}

      <ResultCard run={run} />

      {finished && run.downloads.length > 0 && <Downloads run={run} />}
    </div>
  );
}

const percent = (share: number | null | undefined) => (share == null ? "n/a" : `${Math.round(100 * share)}%`);

/** How far to trust the search that found this run's stores: three checks against
 *  things the bot did not invent. */
function QualityCard({ quality: q }: { quality: Scorecard }) {
  return (
    <section className="card" data-testid="quality" aria-label="Search quality">
      <div className="card-head">
        <h2>Search quality</h2>
        <span className="muted small">· how far to trust the stores this search found</span>
      </div>
      <dl className="stats">
        <Stat
          label="Known stockists found"
          value={q.stockists_found}
          sub={
            q.stockists_known
              ? `of ${formatNumber(q.stockists_known)} in ${q.countries.join(", ")} (${percent(q.recall)})`
              : "no stockist list to check against"
          }
        />
        <Stat
          label="Found twice"
          value={q.confirmed}
          sub={`of ${formatNumber(q.stores)} stores, by two or more sources`}
        />
        <Stat
          label="On the final list"
          value={q.final ?? 0}
          sub={`${percent(q.precision)} of the ${formatNumber(q.read ?? 0)} stores read`}
        />
        <Stat
          label="No such website"
          value={q.missing ?? 0}
          sub="invented or closed"
          alert={(q.missing ?? 0) > 0}
        />
      </dl>
      <p className="muted small card-note">
        {q.stockists_known > 0 &&
          `${percent(q.stockist_share)} of the stores found already carry Wooden Ships: the higher, the closer the search came to stores like our stockists. `}
        A store that is not a stockist is not wrong: it is the prospect the search is for.
        {(q.read_before ?? 0) > 0 &&
          ` ${plural(q.read_before ?? 0, "store")} the search found had been scraped before and were left out.`}
        {(q.missing_examples ?? []).length > 0 && ` No website at: ${(q.missing_examples ?? []).join(", ")}.`}
        {q.cost_per_final_store != null && ` Search cost per final store: ${formatUsd(q.cost_per_final_store)}.`}
      </p>
    </section>
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
      <Square size={13} /> {asked ? "Stopping…" : "Stop"}
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
      setError(e instanceof ApiError ? e.message : "The server cannot be reached.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="notice warn">
      <span>
        {run.state === "stopped" ? "The run was stopped" : "The run ended before it finished (server shut down?)"}:{" "}
        {formatNumber(run.stores_done)} of {formatNumber(run.stores_total)} stores are done and saved.
      </span>
      <span className="spacer" />
      <button type="button" className="button" onClick={resume} disabled={busy}>
        <RotateCw size={14} /> {busy ? "Resuming…" : "Resume"}
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
    <section className="card" aria-label="Download results">
      <div className="card-head">
        <h2>Download results</h2>
        <p>The files of this run, the same as its folder on this computer.</p>
      </div>
      <ul className="download-list">
        {run.downloads.map((d) => (
          <li key={d.key}>
            <a
              className="download-row"
              href={api.downloadUrl(run.run_id, d.key)}
              download={d.filename}
              aria-label={`Download ${d.label}`}
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
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e.message : "The data could not be loaded."));
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
    <section className="card result" aria-label="Results">
      <div className="card-head">
        <h2>Result data</h2>
        <span className="muted small result-title">{run.source_name}</span>
        <span className="spacer" />
        {run.writers.map((w) => (
          <span key={w} className="tag">
            {writerLabel(w)}
          </span>
        ))}
      </div>

      <div className="tabs-row">
        <div className="tabs" role="tablist" aria-label="Tables">
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
        <div className="segmented" role="tablist" aria-label="View">
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
          <p className="empty mono">Loading…</p>
        ) : view === "table" ? (
          <DataTable columns={rows.columns} rows={rows.rows} renderers={RENDERERS[table]} hidden={["run_id"]} />
        ) : (
          <JsonView
            value={rows.rows}
            filename={`${run.run_id}-${table}-${from}-${to}.json`}
            note={rows.truncated_fields ? "long text is cut in the preview; the downloaded file has all of it" : undefined}
          />
        )}
      </div>

      {view !== "params" && rows && rows.total > 0 && (
        <div className="pager mono">
          <span>
            {formatNumber(from)}–{formatNumber(to)} of {formatNumber(rows.total)}
          </span>
          <button
            type="button"
            className="icon-button"
            aria-label="Previous page"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            <ChevronLeft size={16} />
          </button>
          <button
            type="button"
            className="icon-button"
            aria-label="Next page"
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
