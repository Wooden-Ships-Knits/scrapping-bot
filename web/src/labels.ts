// Every code the API returns, in the operator's language. Unknown codes fall back to the code.

const STORE_STATUS: Record<string, string> = {
  ok: "Ada produk",
  no_products: "Tanpa katalog",
  js_required: "Perlu browser",
  blocked: "Diblokir",
  error: "Gagal",
};

const SKIP_REASON: Record<string, string> = {
  duplicate: "Duplikat domain",
  over_limit: "Di luar mode uji",
  no_website: "Tanpa situs",
  invalid_url: "URL tidak valid",
  social_only: "Media sosial",
  marketplace: "Marketplace",
};

const RUN_STATE: Record<string, string> = {
  queued: "Menunggu",
  running: "Berjalan",
  stopped: "Dihentikan",
  done: "Selesai",
  failed: "Gagal",
  interrupted: "Terhenti",
};

const SOURCE: Record<string, string> = {
  shopify_feed: "Feed Shopify",
  bigcartel_feed: "Feed Big Cartel",
  woocommerce_feed: "Feed WooCommerce",
  squarespace_feed: "Feed Squarespace",
  lightspeed_feed: "Feed Lightspeed",
  sitemap: "Sitemap",
  crawl: "Crawl tautan",
  llm: "LLM",
  none: "—",
};

const WRITER: Record<string, string> = {
  xlsx: "Excel",
  csv: "CSV",
  tsv: "TSV",
  parquet: "Parquet",
  json: "JSON",
  jsonl: "JSONL",
  sqlite: "SQLite",
  duckdb: "DuckDB",
};

const pick = (table: Record<string, string>) => (code: string) => table[code] ?? code;

export const storeStatus = pick(STORE_STATUS);
export const skipReason = pick(SKIP_REASON);
export const runState = pick(RUN_STATE);
export const sourceLabel = pick(SOURCE);
export const writerLabel = pick(WRITER);

/** Tone for a status badge: good, warn, bad or neutral. */
export function tone(code: string): "good" | "warn" | "bad" | "neutral" {
  if (code === "ok" || code === "done") return "good";
  if (["no_products", "js_required", "interrupted", "stopped"].includes(code)) return "warn";
  if (code === "blocked" || code === "error" || code === "failed") return "bad";
  return "neutral";
}

const numberFormat = new Intl.NumberFormat("id-ID");
export const formatNumber = (n: number) => numberFormat.format(n);

export function formatTime(iso: string): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" });
}
