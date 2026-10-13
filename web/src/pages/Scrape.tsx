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
  type DiscoverEstimate,
  type DiscoverOptions,
  type Discovery,
  type Options,
  type Preview,
  type Source,
  type Upload,
} from "../api/client";
import { Menu } from "../components/ui/Menu";
import { formatNumber, formatTime, itemLabel, plural, regionLabel, skipReason, writerLabel } from "../labels";
import { navigate } from "../router";
import {
  DiscoveryCard,
  FindStoresFields,
  OTHER,
  parseCount,
  parseTerms,
  type FindForm,
  type PromptNote,
} from "./FindStores";

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
  const [form, setForm] = useState<FindForm>({
    count: "20",
    region: "",
    items: [],
    terms: "",
    rescrape: false,
    prompt: "",
    place: "",
    country: "",
  });
  const [interpreting, setInterpreting] = useState(false);
  const [promptNote, setPromptNote] = useState<PromptNote | null>(null);
  const [discovery, setDiscovery] = useState<Discovery | null>(null);
  const [estimate, setEstimate] = useState<DiscoverEstimate | null>(null);

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

  // What the search can cost, asked again as the count or the region changes.
  const estimateCount = findOptions ? parseCount(form.count, findOptions.max_count) : null;
  useEffect(() => {
    if (mode !== "find" || estimateCount === null || !form.region) {
      setEstimate(null);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      api
        .discoverEstimate(estimateCount, form.region, form.place)
        .then((e) => !cancelled && setEstimate(e))
        .catch(() => !cancelled && setEstimate(null));
    }, PREVIEW_DELAY_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [mode, estimateCount, form.region, form.place]);

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
      .catch(() => setError("The server cannot be reached. Run `make serve`, then reload."));
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

  // Read the described search and fill in the form. Nothing is searched here: the
  // operator checks the fields, then starts.
  async function onInterpret() {
    if (!findOptions || !form.prompt.trim()) return;
    setInterpreting(true);
    setPromptNote(null);
    try {
      const got = await api.interpret(form.prompt);
      const count = got.count ? Math.min(got.count, findOptions.max_count) : null;
      setForm((f) => ({
        ...f,
        count: count ? String(count) : f.count,
        items: got.items.length ? got.items : f.items,
        terms: got.terms.length ? got.terms.join(", ") : f.terms,
        region: got.region || f.region,
        place: got.region ? "" : got.place || f.place,
        country: got.region ? "" : got.place ? got.country : f.country,
      }));
      const parts = [
        got.items.map((i) => (i === OTHER ? got.terms.join(", ") : itemLabel(i))).join(", "),
        got.place ? `${got.place} (${got.country})` : got.region ? regionLabel(got.region) : "",
        count ? plural(count, "store") : "",
      ].filter(Boolean);
      setPromptNote({ ok: true, text: `Understood: ${parts.join(" · ")}. Check the fields below, then start.` });
    } catch (e) {
      setPromptNote({ ok: false, text: message(e) });
    } finally {
      setInterpreting(false);
    }
  }

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
          rescrape: form.rescrape,
          place: form.place,
          country: form.country,
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
        rescrape: form.rescrape,
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
    form.rescrape ? "--rescrape" : "",
  ]
    .filter(Boolean)
    .join(" ");

  const outputLabel = writers.length
    ? writers.slice(0, 2).map(writerLabel).join(", ") + (writers.length > 2 ? ` (+${writers.length - 2})` : "")
    : "choose a format";

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Scrape</h1>
          <p>Paste or upload many store links; products, prices and contacts are collected from each store.</p>
        </div>
      </header>

      <form className="card composer" onSubmit={onSubmit}>
        {findOptions && (
          <div className="tabs-row">
            <div className="tabs" role="tablist" aria-label="Store source">
              <button type="button" role="tab" aria-selected={mode === "find"} onClick={() => setMode("find")}>
                Find stores automatically
              </button>
              <button type="button" role="tab" aria-selected={mode === "links"} onClick={() => setMode("links")}>
                Paste links
              </button>
            </div>
          </div>
        )}
        {mode === "find" && findOptions ? (
          <FindStoresFields
            options={findOptions}
            form={form}
            estimate={estimate}
            onChange={setForm}
            onInterpret={onInterpret}
            interpreting={interpreting}
            promptNote={promptNote}
          />
        ) : (
          <>
            <div className="card-head">
              <span className="label">
                <Link2 size={14} /> Store link list
              </span>
              <span className="spacer" />
              <span className="muted small" title="Links and unique stores detected" data-testid="link-count">
                {preview ? `${plural(preview.links, "link")} · ${plural(preview.stores, "store")}` : previewing ? "reading…" : "0 links"}
              </span>
              {options && <span className="muted small">max. {formatNumber(options.max_links)}</span>}
            </div>

            {upload ? (
              <div className="upload-row">
                <FileSpreadsheet size={18} />
                <span className="mono">{upload.filename}</span>
                <span className="muted small">uploaded</span>
                <span className="spacer" />
                <button type="button" className="icon-button" aria-label="Remove file" onClick={() => setUpload(null)}>
                  <X size={16} />
                </button>
              </div>
            ) : (
              <label className="composer-input">
                <span className="sr-only">Store links</span>
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
                  placeholder={"https://monkeesofnaples.com\nhttps://saracampbell.com\n… paste links or any text, or drop a file here"}
                />
              </label>
            )}
          </>
        )}

        <div className="toolbar">
          {mode === "links" && (
            <button type="button" className="chip" onClick={() => fileInput.current?.click()}>
              <UploadIcon size={15} /> {upload ? "Replace file" : "Upload"}
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
            ariaLabel="Output formats"
            label={
              <>
                <span className="muted">Output:</span> {outputLabel}
                <ChevronDown size={14} />
              </>
            }
          >
            <p className="menu-title">Output formats</p>
            {options?.writers.map((name) => (
              <label key={name} className="menu-check">
                <input type="checkbox" checked={writers.includes(name)} onChange={() => toggleWriter(name)} />
                {writerLabel(name)}
              </label>
            ))}
            <p className="menu-note">The report and the summary CSV are always written.</p>
          </Menu>

          {mode === "links" && upload && (
            <Menu
              ariaLabel="URL column"
              icon={<Columns3 size={14} />}
              label={urlColumn.trim() ? `Column: ${urlColumn.trim()}` : "URL column: auto"}
            >
              <p className="menu-title">Column that holds the links</p>
              <label className="menu-field">
                Column name
                <input value={urlColumn} onChange={(e) => setUrlColumn(e.target.value)} placeholder="auto" />
              </label>
            </Menu>
          )}

          <span className="spacer" />

          {mode === "find" ? (
            <button type="submit" className="button primary" disabled={!canFind}>
              {busy ? "Starting…" : discovering ? "Searching…" : "Find stores & start scraping"}
              {!busy && !discovering && <Search size={14} />}
            </button>
          ) : (
            <button type="submit" className="button primary" disabled={!canRun}>
              {busy ? "Starting…" : "Start scraping"}
              {!busy && <Play size={14} />}
            </button>
          )}
        </div>
      </form>

      {writers.length === 0 && options && <div className="notice bad">Choose at least one output format.</div>}
      {error && (
        <div className="notice bad" role="alert">
          {error}
        </div>
      )}

      {mode === "find" ? (
        discovery && <DiscoveryCard discovery={discovery} />
      ) : (
        <PreviewCard
          preview={preview}
          loading={previewing}
          rescrape={form.rescrape}
          onRescrape={(rescrape) => setForm((f) => ({ ...f, rescrape }))}
        />
      )}

      {mode === "links" && (
        <details className="cli-details">
          <summary>
            <ChevronRight size={16} /> Equivalent command (CLI)
          </summary>
          <pre className="cli">{cli}</pre>
          <p className="muted small">Save the links to a file first when you are not using an upload.</p>
        </details>
      )}
    </div>
  );
}

function PreviewCard({
  preview,
  loading,
  rescrape,
  onRescrape,
}: {
  preview: Preview | null;
  loading: boolean;
  rescrape: boolean;
  onRescrape: (rescrape: boolean) => void;
}) {
  if (!preview) {
    return (
      <section className="card empty-card">
        <p className="muted">{loading ? "Reading links…" : "Detected links appear here before the run starts."}</p>
      </section>
    );
  }
  const skipped = Object.entries(preview.skipped);
  const skippedTotal = skipped.reduce((sum, [, n]) => sum + n, 0);
  const moreStores = preview.stores - preview.store_examples.length;
  return (
    <section className="card" data-testid="preview" aria-live="polite">
      <div className="card-head">
        <h2>Input preview</h2>
        <span className="muted small">· {plural(preview.links, "link")} detected</span>
        <span className="spacer" />
        <span className="small">
          <strong>{plural(preview.stores, "unique store")}</strong>
          <span className="muted"> / {formatNumber(skippedTotal)} skipped</span>
        </span>
      </div>
      {preview.too_many && (
        <div className="notice bad">Too many: at most {formatNumber(preview.max_links)} links per run. Split the list.</div>
      )}
      {preview.read_before > 0 && (
        <div className="notice info" role="status" data-testid="read-before">
          <strong>
            {formatNumber(preview.read_before)} of {plural(preview.stores, "store")} already scraped
          </strong>{" "}
          in the last {formatNumber(preview.reuse_days)} days (latest {formatTime(preview.read_before_latest)}).{" "}
          {rescrape
            ? "They will be scraped again."
            : "Their data will be loaded from that run, not scraped again: no requests, no LLM cost."}
          <label className="menu-check">
            <input type="checkbox" checked={rescrape} onChange={(e) => onRescrape(e.target.checked)} />
            Scrape them again anyway
          </label>
        </div>
      )}
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Link</th>
              <th className="end">Status</th>
            </tr>
          </thead>
          <tbody>
            {preview.store_examples.map((d) => (
              <tr key={d}>
                <td className="mono">https://{d}</td>
                <td className="end">
                  <span className="badge badge-neutral">Ready</span>
                </td>
              </tr>
            ))}
            {preview.skipped_examples.map((s) => (
              <tr key={s.raw + s.reason} className="skipped">
                <td className="mono">
                  <s>{s.raw || "(empty)"}</s>
                </td>
                <td className="end">
                  <span className="badge badge-bad">Skipped: {skipReason(s.reason)}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {(moreStores > 0 || skipped.length > 0 || preview.duplicates > 0) && (
        <div className="card-foot">
          {moreStores > 0 && <span>… and {plural(moreStores, "more store")}</span>}
          {preview.duplicates > 0 && <span>{plural(preview.duplicates, "duplicate")} merged</span>}
          {skipped.length > 0 && <span>Skipped: {skipped.map(([reason, n]) => `${skipReason(reason)} ${n}`).join(", ")}</span>}
        </div>
      )}
    </section>
  );
}

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : "The server cannot be reached.";
}
