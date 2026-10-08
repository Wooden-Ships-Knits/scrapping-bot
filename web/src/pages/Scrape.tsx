import {
  ChevronDown,
  ChevronRight,
  Columns3,
  FileSpreadsheet,
  Link2,
  Play,
  Search,
  Upload as UploadIcon,
  X,
} from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  api,
  ApiError,
  type DiscoverOptions,
  type Discovery,
  type Options,
  type Preview,
  type Source,
  type Upload,
} from "../api/client";
import { Menu } from "../components/ui/Menu";
import { formatNumber, skipReason, writerLabel } from "../labels";
import { navigate } from "../router";
import { DiscoveryCard, FindStoresFields, OTHER, parseCount, parseTerms, type FindForm } from "./FindStores";

const PREVIEW_DELAY_MS = 400;
const DISCOVERY_POLL_MS = 1000;

type Mode = "find" | "links";

export function Scrape() {
  const [options, setOptions] = useState<Options | null>(null);
  const [text, setText] = useState("");
  const [upload, setUpload] = useState<Upload | null>(null);
  const [urlColumn, setUrlColumn] = useState("");
  const [writers, setWriters] = useState<string[]>([]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const [mode, setMode] = useState<Mode>("links");
  const [findOptions, setFindOptions] = useState<DiscoverOptions | null>(null);
  const [form, setForm] = useState<FindForm>({ count: "20", region: "", items: [], terms: "" });
  const [discovery, setDiscovery] = useState<Discovery | null>(null);

  // Finding stores is the default when at least one search source has a key.
  useEffect(() => {
    api
      .discoverOptions()
      .then((o) => {
        setFindOptions(o);
        setForm((f) => ({ ...f, region: o.default_region, items: o.default_items }));
        if (Object.values(o.sources).some(Boolean)) setMode("find");
      })
      .catch(() => setFindOptions(null));
  }, []);

  // Follow a discovery until its run starts, then open that run.
  const discoveryId = discovery?.discovery_id;
  const discovering = discovery !== null && (discovery.state === "searching" || discovery.state === "starting_run");
  useEffect(() => {
    if (!discoveryId || !discovering) return;
    const timer = setInterval(() => {
      api
        .discovery(discoveryId)
        .then((d) => {
          setDiscovery(d);
          if (d.state === "done" && d.run_id) navigate(`/runs/${d.run_id}`);
        })
        .catch((e) => setError(message(e)));
    }, DISCOVERY_POLL_MS);
    return () => clearInterval(timer);
  }, [discoveryId, discovering]);

  useEffect(() => {
    api
      .options()
      .then((o) => {
        setOptions(o);
        setWriters(o.default_writers);
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

  const canRun =
    source !== null &&
    preview !== null &&
    preview.stores > 0 &&
    !preview.too_many &&
    writers.length > 0 &&
    !busy &&
    !previewing;

  const findCount = findOptions ? parseCount(form.count, findOptions.max_count) : null;
  const findTerms = parseTerms(form.terms);
  const canFind =
    findOptions !== null &&
    Object.values(findOptions.sources).some(Boolean) &&
    findCount !== null &&
    form.items.length > 0 &&
    (!form.items.includes(OTHER) || findTerms.length > 0) &&
    writers.length > 0 &&
    !busy &&
    !discovering;

  async function onFind() {
    if (!canFind || findCount === null) return;
    setBusy(true);
    setError("");
    try {
      setDiscovery(
        await api.startDiscovery({
          count: findCount,
          region: form.region,
          items: form.items,
          terms: form.items.includes(OTHER) ? findTerms : [],
          writers,
        }),
      );
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (mode === "find") return void onFind();
    if (!canRun || !source) return;
    setBusy(true);
    setError("");
    try {
      const run = await api.startRun({
        source,
        url_column: urlColumn.trim() || "auto",
        writers,
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
    writers.length ? `-f ${writers.join(",")}` : "",
    urlColumn.trim() ? `--url-column ${urlColumn.trim()}` : "",
  ]
    .filter(Boolean)
    .join(" ");

  const outputLabel = writers.length
    ? writers.slice(0, 2).map(writerLabel).join(", ") + (writers.length > 2 ? ` (+${writers.length - 2})` : "")
    : "pilih format";

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Scrape</h1>
          <p>Tempel atau unggah banyak tautan toko; data produk, harga dan kontak dikumpulkan dari setiap toko.</p>
        </div>
      </header>

      <form className="card composer" onSubmit={onSubmit}>
        {findOptions && (
          <div className="tabs-row">
            <div className="tabs" role="tablist" aria-label="Sumber toko">
              <button type="button" role="tab" aria-selected={mode === "find"} onClick={() => setMode("find")}>
                Cari toko otomatis
              </button>
              <button type="button" role="tab" aria-selected={mode === "links"} onClick={() => setMode("links")}>
                Tempel tautan
              </button>
            </div>
          </div>
        )}
        {mode === "find" && findOptions ? (
          <FindStoresFields options={findOptions} form={form} onChange={setForm} />
        ) : (
          <>
            <div className="card-head">
              <span className="label">
                <Link2 size={14} /> Daftar tautan toko
              </span>
              <span className="spacer" />
              <span className="muted small" title="Tautan dan toko unik yang terdeteksi" data-testid="link-count">
                {preview ? `${formatNumber(preview.links)} tautan · ${formatNumber(preview.stores)} toko` : previewing ? "membaca…" : "0 tautan"}
              </span>
              {options && <span className="muted small">maks. {formatNumber(options.max_links)}</span>}
            </div>

            {upload ? (
              <div className="upload-row">
                <FileSpreadsheet size={18} />
                <span className="mono">{upload.filename}</span>
                <span className="muted small">terunggah</span>
                <span className="spacer" />
                <button type="button" className="icon-button" aria-label="Hapus file" onClick={() => setUpload(null)}>
                  <X size={16} />
                </button>
              </div>
            ) : (
              <label className="composer-input">
                <span className="sr-only">Tautan toko</span>
                <textarea
                  rows={6}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    if (e.dataTransfer.files[0]) {
                      e.preventDefault();
                      void onFile(e.dataTransfer.files[0]);
                    }
                  }}
                  placeholder={"https://monkeesofnaples.com\nhttps://saracampbell.com\n… tempel tautan atau teks apa pun, atau seret file ke sini"}
                />
              </label>
            )}
          </>
        )}

        <div className="toolbar">
          {mode === "links" && (
            <button type="button" className="chip" onClick={() => fileInput.current?.click()}>
              <UploadIcon size={15} /> {upload ? "Ganti file" : "Unggah"}
            </button>
          )}
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
                <span className="muted">Keluaran:</span> {outputLabel}
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

          {mode === "links" && upload && (
            <Menu
              ariaLabel="Kolom URL"
              icon={<Columns3 size={14} />}
              label={urlColumn.trim() ? `Kolom: ${urlColumn.trim()}` : "Kolom URL: otomatis"}
            >
              <p className="menu-title">Kolom yang berisi tautan</p>
              <label className="menu-field">
                Nama kolom
                <input value={urlColumn} onChange={(e) => setUrlColumn(e.target.value)} placeholder="otomatis" />
              </label>
            </Menu>
          )}

          <span className="spacer" />

          {mode === "find" ? (
            <button type="submit" className="button primary" disabled={!canFind}>
              {busy ? "Memulai…" : discovering ? "Sedang mencari…" : "Cari toko & mulai scrape"}
              {!busy && !discovering && <Search size={14} />}
            </button>
          ) : (
            <button type="submit" className="button primary" disabled={!canRun}>
              {busy ? "Memulai…" : "Mulai scrape"}
              {!busy && <Play size={14} />}
            </button>
          )}
        </div>
      </form>

      {writers.length === 0 && options && <div className="notice bad">Pilih minimal satu format keluaran.</div>}
      {error && (
        <div className="notice bad" role="alert">
          {error}
        </div>
      )}

      {mode === "find" ? (
        discovery && <DiscoveryCard discovery={discovery} />
      ) : (
        <PreviewCard preview={preview} loading={previewing} />
      )}

      {mode === "links" && (
        <details className="cli-details">
          <summary>
            <ChevronRight size={16} /> Perintah yang setara (CLI)
          </summary>
          <pre className="cli">{cli}</pre>
          <p className="muted small">Simpan tautan ke file dulu bila tidak memakai unggahan.</p>
        </details>
      )}
    </div>
  );
}

function PreviewCard({ preview, loading }: { preview: Preview | null; loading: boolean }) {
  if (!preview) {
    return (
      <section className="card empty-card">
        <p className="muted">{loading ? "Membaca tautan…" : "Tautan yang terdeteksi akan tampil di sini sebelum run dimulai."}</p>
      </section>
    );
  }
  const skipped = Object.entries(preview.skipped);
  const skippedTotal = skipped.reduce((sum, [, n]) => sum + n, 0);
  const moreStores = preview.stores - preview.store_examples.length;
  return (
    <section className="card" data-testid="preview" aria-live="polite">
      <div className="card-head">
        <h2>Pratinjau masukan</h2>
        <span className="muted small">· {formatNumber(preview.links)} tautan terdeteksi</span>
        <span className="spacer" />
        <span className="small">
          <strong>{formatNumber(preview.stores)} toko unik</strong>
          <span className="muted"> / {formatNumber(skippedTotal)} dilewati</span>
        </span>
      </div>
      {preview.too_many && (
        <div className="notice bad">Terlalu banyak: maksimal {formatNumber(preview.max_links)} tautan per run. Pecah daftarnya.</div>
      )}
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Tautan</th>
              <th className="end">Status</th>
            </tr>
          </thead>
          <tbody>
            {preview.store_examples.map((d) => (
              <tr key={d}>
                <td className="mono">https://{d}</td>
                <td className="end">
                  <span className="badge badge-neutral">Siap diproses</span>
                </td>
              </tr>
            ))}
            {preview.skipped_examples.map((s) => (
              <tr key={s.raw + s.reason} className="skipped">
                <td className="mono">
                  <s>{s.raw || "(kosong)"}</s>
                </td>
                <td className="end">
                  <span className="badge badge-bad">Dilewati: {skipReason(s.reason)}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {(moreStores > 0 || skipped.length > 0 || preview.duplicates > 0) && (
        <div className="card-foot">
          {moreStores > 0 && <span>… dan {formatNumber(moreStores)} toko lainnya</span>}
          {preview.duplicates > 0 && <span>{formatNumber(preview.duplicates)} duplikat digabung</span>}
          {skipped.length > 0 && <span>Dilewati: {skipped.map(([reason, n]) => `${skipReason(reason)} ${n}`).join(", ")}</span>}
        </div>
      )}
    </section>
  );
}

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : "Server tidak bisa dihubungi.";
}
