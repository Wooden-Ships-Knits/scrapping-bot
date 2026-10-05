import { useEffect, useRef, useState, type FormEvent } from "react";

import { api, ApiError, type Options, type Preview, type Source, type Upload } from "../api/client";
import { writerLabel } from "../labels";
import { navigate } from "../router";
import { PreviewPanel } from "./PreviewPanel";

const PREVIEW_DELAY_MS = 400;

type Mode = "text" | "file";

export function NewRun() {
  const [options, setOptions] = useState<Options | null>(null);
  const [mode, setMode] = useState<Mode>("text");
  const [text, setText] = useState("");
  const [upload, setUpload] = useState<Upload | null>(null);
  const [urlColumn, setUrlColumn] = useState("");
  const [writers, setWriters] = useState<string[]>([]);
  const [testMode, setTestMode] = useState(true);
  const [testLimit, setTestLimit] = useState(2);
  const [skipTest, setSkipTest] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api
      .options()
      .then((o) => {
        setOptions(o);
        setWriters(o.default_writers);
        setTestLimit(o.default_test_limit);
      })
      .catch(() => setError("Server tidak bisa dihubungi. Jalankan `make serve` lalu muat ulang."));
  }, []);

  const source: Source | null =
    mode === "text" ? (text.trim() ? { text } : null) : upload ? { upload_id: upload.upload_id } : null;
  const sourceKey = JSON.stringify([source, urlColumn]);

  // Preview the links as they change, before anything is fetched.
  useEffect(() => {
    if (!source) {
      setPreview(null);
      return;
    }
    let cancelled = false;
    setPreviewing(true);
    const timer = setTimeout(() => {
      api
        .preview(source, urlColumn.trim() || "auto")
        .then((p) => !cancelled && (setPreview(p), setError("")))
        .catch((e) => !cancelled && (setPreview(null), setError(message(e))))
        .finally(() => !cancelled && setPreviewing(false));
    }, PREVIEW_DELAY_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // `sourceKey` captures every input of the preview.
  }, [sourceKey]);

  async function onFile(file: File | undefined) {
    if (!file) return;
    setError("");
    setUpload(null);
    setBusy(true);
    try {
      setUpload(await api.upload(file));
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  const needsSkipConfirm = !testMode && preview !== null && !preview.tested;
  const canRun =
    source !== null &&
    preview !== null &&
    preview.stores > 0 &&
    !preview.too_many &&
    writers.length > 0 &&
    (!needsSkipConfirm || skipTest) &&
    !busy &&
    !previewing;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!canRun || !source) return;
    setBusy(true);
    setError("");
    try {
      const run = await api.startRun({
        source,
        url_column: urlColumn.trim() || "auto",
        writers,
        test_mode: testMode,
        test_limit: testLimit,
        skip_test_run: skipTest,
      });
      navigate(`/runs/${run.run_id}`);
    } catch (e) {
      setError(message(e));
      setBusy(false);
    }
  }

  const toggleWriter = (name: string) =>
    setWriters((current) =>
      current.includes(name) ? current.filter((w) => w !== name) : [...current, name],
    );

  return (
    <form className="layout" onSubmit={onSubmit}>
      <aside className="panel settings" aria-label="Pengaturan">
        <h2>Keluaran</h2>
        <fieldset className="checks">
          <legend className="sr-only">Format keluaran</legend>
          {options?.writers.map((name) => (
            <label key={name} className="check">
              <input
                type="checkbox"
                checked={writers.includes(name)}
                onChange={() => toggleWriter(name)}
              />
              {writerLabel(name)}
            </label>
          ))}
        </fieldset>
        {writers.length === 0 && <p className="field-note bad">Pilih minimal satu format.</p>}
        <p className="field-note">
          Laporan run dan ringkasan per tautan (CSV) selalu dibuat.
        </p>

        <h2>Mode uji</h2>
        <label className="check">
          <input type="checkbox" checked={testMode} onChange={(e) => setTestMode(e.target.checked)} />
          Jalankan beberapa toko pertama dulu
        </label>
        {testMode ? (
          <label className="field">
            Jumlah toko
            <input
              type="number"
              min={1}
              max={50}
              value={testLimit}
              onChange={(e) => setTestLimit(Math.max(1, Math.min(50, Number(e.target.value) || 1)))}
            />
          </label>
        ) : (
          <p className="field-note">Semua toko dalam daftar akan dikunjungi.</p>
        )}
        {needsSkipConfirm && (
          <div className="alert alert-warn">
            <p>Daftar ini belum pernah diuji. Sebaiknya jalankan mode uji dulu dan periksa hasilnya.</p>
            <label className="check">
              <input type="checkbox" checked={skipTest} onChange={(e) => setSkipTest(e.target.checked)} />
              Saya sengaja melewati mode uji
            </label>
          </div>
        )}
      </aside>

      <section className="panel main" aria-label="Tautan toko">
        <div className="tabs" role="tablist">
          <button type="button" role="tab" aria-selected={mode === "text"} onClick={() => setMode("text")}>
            Tempel tautan
          </button>
          <button type="button" role="tab" aria-selected={mode === "file"} onClick={() => setMode("file")}>
            Unggah file
          </button>
        </div>

        {mode === "text" ? (
          <label className="field">
            <span className="sr-only">Tautan toko</span>
            <textarea
              rows={10}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Tempel tautan atau teks apa pun di sini, misalnya: cek monkeesofnaples.com dan https://saracampbell.com"
            />
          </label>
        ) : (
          <div
            className="dropzone"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              void onFile(e.dataTransfer.files[0]);
            }}
          >
            <p>
              {upload ? (
                <>
                  <strong>{upload.filename}</strong> terunggah.
                </>
              ) : (
                "Seret file ke sini, atau"
              )}
            </p>
            <button type="button" className="secondary" onClick={() => fileInput.current?.click()}>
              {upload ? "Ganti file" : "Pilih file"}
            </button>
            <input
              ref={fileInput}
              type="file"
              hidden
              data-testid="file-input"
              accept={options?.suffixes.join(",")}
              onChange={(e) => void onFile(e.target.files?.[0])}
            />
            <p className="muted small">
              {options?.suffixes.join(" ")} · maks {options?.max_upload_mb ?? 20} MB
            </p>
            <label className="field inline">
              Kolom URL
              <input
                value={urlColumn}
                onChange={(e) => setUrlColumn(e.target.value)}
                placeholder="otomatis"
              />
            </label>
          </div>
        )}

        <PreviewPanel preview={preview} loading={previewing} />
        {error && (
          <p className="alert alert-bad" role="alert">
            {error}
          </p>
        )}

        <div className="actions">
          <button type="submit" disabled={!canRun}>
            {busy ? "Memulai…" : testMode ? `Jalankan uji (${testLimit} toko)` : "Jalankan semua"}
          </button>
        </div>
      </section>
    </form>
  );
}

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : "Server tidak bisa dihubungi.";
}
