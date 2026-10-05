import {
  AlertTriangle,
  ChevronDown,
  Columns3,
  FileSpreadsheet,
  FlaskConical,
  Link2,
  Terminal,
  Upload as UploadIcon,
  X,
} from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { api, ApiError, type Options, type Preview, type Source, type Upload } from "../api/client";
import { Menu } from "../components/ui/Menu";
import { formatNumber, skipReason, writerLabel } from "../labels";
import { navigate } from "../router";

const PREVIEW_DELAY_MS = 400;

export function Scrape() {
  const [options, setOptions] = useState<Options | null>(null);
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

  const source: Source | null = upload ? { upload_id: upload.upload_id } : text.trim() ? { text } : null;
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
    setWriters((current) => (current.includes(name) ? current.filter((w) => w !== name) : [...current, name]));

  const cli = [
    "uv run scrapebot run",
    upload ? upload.filename : "links.txt",
    testMode ? `--limit ${testLimit}` : "",
    writers.length ? `-f ${writers.join(",")}` : "",
    urlColumn.trim() ? `--url-column ${urlColumn.trim()}` : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="page">
      <header className="page-head">
        <h1>Scrape</h1>
        <p className="mono muted">Tempel atau unggah banyak tautan toko; data produk, harga dan kontak dikumpulkan dari setiap toko.</p>
      </header>

      <form className="card composer" onSubmit={onSubmit}>
        {upload ? (
          <div className="upload-row">
            <FileSpreadsheet size={18} />
            <span className="mono">{upload.filename}</span>
            <span className="muted mono small">terunggah</span>
            <span className="spacer" />
            <button type="button" className="icon-button" aria-label="Hapus file" onClick={() => setUpload(null)}>
              <X size={16} />
            </button>
          </div>
        ) : (
          <label className="composer-input">
            <span className="sr-only">Tautan toko</span>
            <textarea
              rows={4}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                if (e.dataTransfer.files[0]) {
                  e.preventDefault();
                  void onFile(e.dataTransfer.files[0]);
                }
              }}
              placeholder="https://monkeesofnaples.com  https://saracampbell.com  … tempel tautan atau teks apa pun, atau seret file ke sini"
            />
          </label>
        )}

        <div className="toolbar">
          <button type="button" className="chip" onClick={() => fileInput.current?.click()}>
            <UploadIcon size={14} /> {upload ? "GANTI FILE" : "UNGGAH"}
          </button>
          <input
            ref={fileInput}
            type="file"
            hidden
            data-testid="file-input"
            accept={options?.suffixes.join(",")}
            onChange={(e) => void onFile(e.target.files?.[0])}
          />

          <Menu
            ariaLabel="Format keluaran"
            label={
              <>
                {writers.length ? writers.map((w) => writerLabel(w).toUpperCase()).join(" · ") : "PILIH FORMAT"}
                <ChevronDown size={14} />
              </>
            }
          >
            <p className="menu-title">Format keluaran</p>
            {options?.writers.map((name) => (
              <label key={name} className="menu-check">
                <input type="checkbox" checked={writers.includes(name)} onChange={() => toggleWriter(name)} />
                {writerLabel(name)}
              </label>
            ))}
            <p className="menu-note">Laporan dan ringkasan CSV selalu dibuat.</p>
          </Menu>

          <Menu
            ariaLabel="Mode uji"
            icon={<FlaskConical size={14} />}
            label={testMode ? `UJI · ${testLimit} TOKO` : "SEMUA TOKO"}
          >
            <p className="menu-title">Mode uji</p>
            <label className="menu-check">
              <input type="checkbox" checked={testMode} onChange={(e) => setTestMode(e.target.checked)} />
              Jalankan beberapa toko pertama dulu
            </label>
            {testMode && (
              <label className="menu-field">
                Jumlah toko
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={testLimit}
                  onChange={(e) => setTestLimit(Math.max(1, Math.min(50, Number(e.target.value) || 1)))}
                />
              </label>
            )}
          </Menu>

          {upload && (
            <Menu ariaLabel="Kolom URL" icon={<Columns3 size={14} />} label={urlColumn.trim() ? urlColumn.toUpperCase() : "KOLOM URL · OTOMATIS"}>
              <p className="menu-title">Kolom yang berisi tautan</p>
              <label className="menu-field">
                Nama kolom
                <input value={urlColumn} onChange={(e) => setUrlColumn(e.target.value)} placeholder="otomatis" />
              </label>
            </Menu>
          )}

          <span className="spacer" />

          <span className="chip static" title="Tautan dan toko unik yang terdeteksi" data-testid="link-count">
            <Link2 size={14} />
            {preview ? `${formatNumber(preview.links)} tautan · ${formatNumber(preview.stores)} toko` : previewing ? "membaca…" : "0 tautan"}
          </span>

          <Menu className="button ghost" align="right" icon={<Terminal size={14} />} label="GET CLI">
            <p className="menu-title">Perintah yang setara</p>
            <pre className="cli">{cli}</pre>
            <p className="menu-note">Simpan tautan ke file dulu bila tidak memakai unggahan.</p>
          </Menu>

          <button type="submit" className="button primary" disabled={!canRun}>
            {busy ? "MEMULAI…" : testMode ? "START RUN UJI" : "START RUN"}
          </button>
        </div>

        {needsSkipConfirm && (
          <div className="notice warn">
            <AlertTriangle size={16} />
            <span>Daftar ini belum pernah diuji. Sebaiknya jalankan mode uji dulu dan periksa hasilnya.</span>
            <label className="menu-check">
              <input type="checkbox" checked={skipTest} onChange={(e) => setSkipTest(e.target.checked)} />
              Saya sengaja melewati mode uji
            </label>
          </div>
        )}
        {writers.length === 0 && options && <div className="notice bad">Pilih minimal satu format keluaran.</div>}
        {error && (
          <div className="notice bad" role="alert">
            {error}
          </div>
        )}
      </form>

      <PreviewCard preview={preview} loading={previewing} />
    </div>
  );
}

function PreviewCard({ preview, loading }: { preview: Preview | null; loading: boolean }) {
  if (!preview) {
    return (
      <section className="card empty-card">
        <p className="mono muted">{loading ? "Membaca tautan…" : "Tautan yang terdeteksi akan tampil di sini sebelum run dimulai."}</p>
      </section>
    );
  }
  const skipped = Object.entries(preview.skipped);
  return (
    <section className="card" data-testid="preview" aria-live="polite">
      <div className="card-head">
        <span className="mono">Pratinjau masukan</span>
        <span className="spacer" />
        <span className="tag">{formatNumber(preview.links)} tautan</span>
        <span className="tag">{formatNumber(preview.stores)} toko unik</span>
        {preview.duplicates > 0 && <span className="tag">{formatNumber(preview.duplicates)} duplikat</span>}
      </div>
      <p className="sr-only">
        Terdeteksi {preview.links} tautan · {preview.stores} toko unik
      </p>
      {preview.too_many && (
        <div className="notice bad">Terlalu banyak: maksimal {formatNumber(preview.max_links)} tautan per run. Pecah daftarnya.</div>
      )}
      <pre className="json-body compact">
        <code>
          {preview.store_examples.map((d) => (
            <span key={d} className="json-string">
              {`"https://${d}",\n`}
            </span>
          ))}
          {preview.stores > preview.store_examples.length && (
            <span className="muted">{`… dan ${formatNumber(preview.stores - preview.store_examples.length)} toko lainnya\n`}</span>
          )}
          {preview.skipped_examples.map((s) => (
            <span key={s.raw + s.reason} className="json-skip">
              {`"${s.raw || "(kosong)"}"  // dilewati: ${skipReason(s.reason)}\n`}
            </span>
          ))}
        </code>
      </pre>
      {skipped.length > 0 && (
        <p className="mono muted small pad">Dilewati: {skipped.map(([reason, n]) => `${skipReason(reason)} ${n}`).join(", ")}</p>
      )}
    </section>
  );
}

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : "Server tidak bisa dihubungi.";
}
