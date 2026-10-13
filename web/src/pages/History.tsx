import { Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { api, ApiError, type Cache, type RunListItem } from "../api/client";
import { cacheKind, cacheLoss, formatBytes, formatNumber, formatTime, plural, runState, tone } from "../labels";

/** The short, readable end of a run id ("20261005T085253123Z-56162b" → "56162b"). */
export const shortId = (runId: string) => runId.split("-").pop() ?? runId;

/** A run that is queued or running cannot be deleted: it has to be stopped first. */
const active = (r: RunListItem) => r.state === "queued" || r.state === "running";

/** Ticking and deleting runs. Without it the table only lists them. */
export type RunSelection = {
  selected: ReadonlySet<string>;
  onToggle: (runId: string) => void;
  onToggleAll: () => void;
  onDelete: (runId: string) => void;
};

export function RunsTable({ runs, selection }: { runs: RunListItem[]; selection?: RunSelection }) {
  const deletable = runs.filter((r) => !active(r));
  const allTicked = deletable.length > 0 && deletable.every((r) => selection?.selected.has(r.run_id));
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {selection && (
              <th className="tick">
                <input
                  type="checkbox"
                  aria-label="Select all runs"
                  checked={allTicked}
                  disabled={deletable.length === 0}
                  onChange={selection.onToggleAll}
                />
              </th>
            )}
            <th>Run ID</th>
            <th>Input</th>
            <th>Started</th>
            <th className="num">Stores</th>
            <th className="num">Products</th>
            <th>Status</th>
            <th className="end">Action</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.run_id}>
              {selection && (
                <td className="tick">
                  <input
                    type="checkbox"
                    aria-label={`Select run ${shortId(r.run_id)}`}
                    checked={selection.selected.has(r.run_id)}
                    disabled={active(r)}
                    onChange={() => selection.onToggle(r.run_id)}
                  />
                </td>
              )}
              <td className="mono" title={r.run_id}>
                <strong>#{shortId(r.run_id)}</strong>
              </td>
              <td>
                {r.source_name}
                <span className="sub">
                  {r.mode === "test" ? "Limited" : "Full"} · {plural(r.links_in, "link")}
                </span>
              </td>
              <td className="mono small">{formatTime(r.started_at)}</td>
              <td className="num">
                {formatNumber(r.stores_done)} / {formatNumber(r.stores_total)}
              </td>
              <td className="num">
                <strong>{formatNumber(r.products)}</strong>
              </td>
              <td>
                <span className={`badge badge-${tone(r.state)}`}>{runState(r.state)}</span>
              </td>
              <td className="end">
                <a className="button ghost small-button" href={`#/runs/${r.run_id}`}>
                  Details
                </a>
                {selection && (
                  <button
                    type="button"
                    className="icon-button"
                    aria-label={`Delete run ${shortId(r.run_id)}`}
                    title={active(r) ? "Stop the run before deleting it" : "Delete this run"}
                    disabled={active(r)}
                    onClick={() => selection.onDelete(r.run_id)}
                  >
                    <Trash2 size={15} />
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const message = (e: unknown) => (e instanceof ApiError ? e.message : "The server cannot be reached.");

/** Asked before anything is deleted: what goes, and what that costs. */
function Confirm({
  title,
  detail,
  action,
  busy,
  onConfirm,
  onCancel,
}: {
  title: string;
  detail: string;
  action: string;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="notice warn confirm" role="alertdialog" aria-label={title} data-testid="confirm">
      <strong>{title}</strong> {detail} This cannot be undone.
      <span className="confirm-actions">
        <button type="button" className="button danger small-button" disabled={busy} onClick={onConfirm}>
          {busy ? "Deleting…" : action}
        </button>
        <button type="button" className="button ghost small-button" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </span>
    </div>
  );
}

/** The caches: what each holds, and a way to delete one or all of them. */
function CacheCard() {
  const [cache, setCache] = useState<Cache | null>(null);
  const [asking, setAsking] = useState<string | null>(null); // the kind about to be deleted, or "all"
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .cache()
      .then(setCache)
      .catch(() => setCache(null));
  }, []);

  if (!cache) return null;
  const total = cache.kinds.reduce((sum, k) => sum + k.bytes, 0);

  async function clear(kind: string) {
    setBusy(true);
    setError("");
    try {
      setCache(await api.clearCache(kind));
      setAsking(null);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" data-testid="cache" aria-label="Cache">
      <div className="card-head">
        <h2>Cache</h2>
        <span className="muted small">· saves a second request or a second payment; no run depends on it</span>
        <span className="spacer" />
        <button
          type="button"
          className="button ghost small-button"
          disabled={cache.busy || total === 0}
          onClick={() => setAsking("all")}
        >
          Delete all caches
        </button>
      </div>
      {cache.busy && (
        <div className="notice info">A run or a search is under way: the caches can be deleted when it is done.</div>
      )}
      {error && (
        <div className="notice bad" role="alert">
          {error}
        </div>
      )}
      {asking && (
        <Confirm
          title={asking === "all" ? "Delete every cache?" : `Delete the cache "${cacheKind(asking)}"?`}
          detail={cacheLoss(asking)}
          action="Delete"
          busy={busy}
          onConfirm={() => void clear(asking)}
          onCancel={() => setAsking(null)}
        />
      )}
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Cache</th>
              <th className="num">Files</th>
              <th className="num">Size</th>
              <th className="end">Action</th>
            </tr>
          </thead>
          <tbody>
            {cache.kinds.map((k) => (
              <tr key={k.name}>
                <td>
                  {cacheKind(k.name)}
                  <span className="sub">{cacheLoss(k.name)}</span>
                </td>
                <td className="num">{formatNumber(k.files)}</td>
                <td className="num">{formatBytes(k.bytes)}</td>
                <td className="end">
                  <button
                    type="button"
                    className="button ghost small-button"
                    disabled={cache.busy || k.files === 0}
                    onClick={() => setAsking(k.name)}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function History() {
  const [runs, setRuns] = useState<RunListItem[] | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [asking, setAsking] = useState<string[] | null>(null); // the runs about to be deleted
  const [busy, setBusy] = useState(false);

  const load = () =>
    api
      .runs()
      .then(setRuns)
      .catch(() => setError("The server cannot be reached."));

  useEffect(() => {
    void load();
  }, []);

  const deletable = (runs ?? []).filter((r) => !active(r)).map((r) => r.run_id);
  const toggle = (runId: string) =>
    setSelected((now) => {
      const next = new Set(now);
      if (!next.delete(runId)) next.add(runId);
      return next;
    });
  const toggleAll = () => setSelected((now) => (deletable.every((id) => now.has(id)) ? new Set() : new Set(deletable)));

  // One at a time, so a run that cannot be deleted is named and the rest still go.
  async function remove(runIds: string[]) {
    setBusy(true);
    setError("");
    const failed: string[] = [];
    for (const runId of runIds) {
      try {
        await api.deleteRun(runId);
      } catch (e) {
        failed.push(`#${shortId(runId)}: ${message(e)}`);
      }
    }
    setBusy(false);
    setAsking(null);
    setSelected(new Set());
    if (failed.length) setError(`Not deleted: ${failed.join("; ")}`);
    await load();
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Run history</h1>
          <p>Every run has its own folder; nothing is overwritten.</p>
        </div>
      </header>
      {error && (
        <div className="notice bad" role="alert">
          {error}
        </div>
      )}
      {!runs && !error && <p className="muted">Loading the history…</p>}
      {runs && runs.length === 0 && (
        <section className="card empty-card">
          <p className="muted">
            No runs yet. <a href="#/">Start a new run</a>.
          </p>
        </section>
      )}
      {runs && runs.length > 0 && (
        <section className="card">
          <div className="card-head">
            <span className="muted small">
              {selected.size > 0 ? `${plural(selected.size, "run")} selected` : plural(runs.length, "run")}
            </span>
            <span className="spacer" />
            <button
              type="button"
              className="button ghost small-button"
              disabled={selected.size === 0 || busy}
              onClick={() => setAsking([...selected])}
            >
              <Trash2 size={14} /> Delete selected
            </button>
          </div>
          {asking && (
            <Confirm
              title={`Delete ${plural(asking.length, "run")}?`}
              detail={
                "Their tables, exports and reports are removed, and their stores count as not read: " +
                "a later search can find them again and a later run visits them again."
              }
              action={`Delete ${plural(asking.length, "run")}`}
              busy={busy}
              onConfirm={() => void remove(asking)}
              onCancel={() => setAsking(null)}
            />
          )}
          <RunsTable
            runs={runs}
            selection={{ selected, onToggle: toggle, onToggleAll: toggleAll, onDelete: (id) => setAsking([id]) }}
          />
        </section>
      )}
      <CacheCard />
    </div>
  );
}
