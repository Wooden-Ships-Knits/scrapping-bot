import { useState } from "react";

import { api, ApiError, type Run } from "../api/client";
import { useRun } from "../api/useRun";
import {
  formatNumber,
  formatTime,
  runState,
  skipReason,
  sourceLabel,
  storeStatus,
} from "../labels";
import { navigate } from "../router";
import { StatusBadge } from "./StatusBadge";

const LOOK_AT = ["no_products", "js_required", "blocked", "error"];

export function RunView({ runId }: { runId: string }) {
  const { run, error } = useRun(runId);
  if (!run) {
    return <p className={error ? "alert alert-bad" : "muted"}>{error || "Memuat run…"}</p>;
  }
  return <RunDetail run={run} connectionError={error} />;
}

export function RunDetail({ run, connectionError }: { run: Run; connectionError?: string }) {
  const finished = run.state === "done";
  const percent = run.stores_total ? Math.round((100 * run.stores_done) / run.stores_total) : 100;
  const balanced = run.links_in === run.processed + run.skipped;
  const needsLook = run.stores.filter((s) => LOOK_AT.includes(s.status));

  return (
    <div className="run">
      <header className="run-head">
        <div>
          <h1>
            {run.mode === "test" ? `Run uji: ${run.limit} toko pertama` : "Run penuh"}{" "}
            <StatusBadge code={run.state} label={runState(run.state)} />
          </h1>
          <p className="muted">
            {run.source_name} · dimulai {formatTime(run.started_at)}
            {run.finished_at && <> · selesai {formatTime(run.finished_at)}</>} ·{" "}
            <code>{run.run_id}</code>
          </p>
        </div>
      </header>

      {connectionError && <p className="alert alert-warn">{connectionError}</p>}
      {run.state === "failed" && (
        <p className="alert alert-bad" role="alert">
          Run gagal: {run.error || "lihat log server"}.
        </p>
      )}
      {run.state === "interrupted" && (
        <p className="alert alert-warn">
          Run terhenti sebelum selesai (server dimatikan?). Data toko yang sudah selesai tetap ada di
          folder run. Jalankan ulang untuk hasil lengkap.
        </p>
      )}

      <section className="panel">
        <div className="progress-head">
          <span>
            Toko dikunjungi: <strong>{formatNumber(run.stores_done)}</strong> dari{" "}
            {formatNumber(run.stores_total)}
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
          <div className="progress-bar" style={{ width: `${percent}%` }} />
        </div>

        <dl className="stats">
          <Stat label="Produk" value={run.products} />
          <Stat label="Halaman" value={run.pages} />
          <Stat label="Kontak" value={run.contacts} />
        </dl>

        <p className={`reconcile ${balanced ? "good" : "bad"}`} data-testid="reconciliation">
          Tautan masuk <strong>{formatNumber(run.links_in)}</strong> = diproses{" "}
          <strong>{formatNumber(run.processed)}</strong> + dilewati{" "}
          <strong>{formatNumber(run.skipped)}</strong> {balanced ? "✓ seimbang" : "✗ tidak seimbang"}
        </p>
        {Object.keys(run.skipped_by_reason).length > 0 && (
          <ul className="chips" aria-label="Tautan yang dilewati">
            {Object.entries(run.skipped_by_reason).map(([reason, n]) => (
              <li key={reason}>
                {skipReason(reason)}: {formatNumber(n)}
              </li>
            ))}
          </ul>
        )}
      </section>

      {finished && run.mode === "test" && <ContinueFullRun run={run} />}

      {finished && (
        <section className="panel">
          <h2>Unduh hasil</h2>
          <div className="downloads">
            {run.downloads.map((d) => (
              <a
                key={d.key}
                className={`button ${d.key === "report" ? "" : "secondary"}`}
                href={api.downloadUrl(run.run_id, d.key)}
                download={d.filename}
              >
                {d.label}
              </a>
            ))}
          </div>
        </section>
      )}

      {needsLook.length > 0 && finished && (
        <section className="panel">
          <h2>Perlu dilihat</h2>
          <ul className="look">
            {needsLook.map((s) => (
              <li key={s.domain}>
                <strong>{s.domain}</strong>: {storeStatus(s.status)}
                {s.error && <span className="muted"> ({s.error})</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="panel">
        <h2>Toko</h2>
        {run.stores.length === 0 ? (
          <p className="muted">Belum ada toko yang selesai.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Domain</th>
                  <th>Status</th>
                  <th>Sumber</th>
                  <th className="num">Produk</th>
                  <th className="num">Halaman</th>
                  <th className="num">Kontak</th>
                  <th>Mata uang</th>
                </tr>
              </thead>
              <tbody>
                {run.stores.map((s) => (
                  <tr key={s.domain}>
                    <td>
                      <a href={s.url} target="_blank" rel="noreferrer">
                        {s.domain}
                      </a>
                      {s.ssl_bypassed && (
                        <span className="badge badge-warn" title="Sertifikat TLS situs rusak">
                          TLS
                        </span>
                      )}
                    </td>
                    <td>
                      <StatusBadge code={s.status} label={storeStatus(s.status)} />
                    </td>
                    <td>{sourceLabel(s.source_used)}</td>
                    <td className="num">{formatNumber(s.product_count)}</td>
                    <td className="num">{formatNumber(s.page_count)}</td>
                    <td className="num">{formatNumber(s.contact_count)}</td>
                    <td>{s.currency || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="stat">
      <dt>{label}</dt>
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
    <section className="panel callout">
      <h2>Periksa hasil uji, lalu lanjutkan</h2>
      <ol>
        <li>Rekonsiliasi di atas harus seimbang.</li>
        <li>Toko yang Anda tahu punya katalog harus berstatus “Ada produk”.</li>
        <li>Buka file Excel: judul, harga dan mata uang di sheet products harus sama dengan situsnya.</li>
      </ol>
      <button type="button" onClick={start} disabled={busy}>
        {busy ? "Memulai…" : `Jalankan seluruh daftar (${formatNumber(run.links_in)} tautan)`}
      </button>
      {error && (
        <p className="alert alert-bad" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
