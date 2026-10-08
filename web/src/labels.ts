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
  over_limit: "Di luar batas jumlah toko",
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
  magento_feed: "API Magento",
  sitemap: "Sitemap",
  crawl: "Crawl tautan",
  render: "Browser (Camoufox)",
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

const REGION: Record<string, string> = {
  north_america: "Amerika Utara (AS & Kanada)",
  united_states: "Amerika Serikat",
  canada: "Kanada",
  europe: "Eropa",
  united_kingdom: "Inggris & Irlandia",
  oceania: "Australia & Selandia Baru",
  asia: "Asia Timur & Tenggara",
};

const ITEM: Record<string, string> = {
  knitwear: "Knitwear",
  cashmere_wool: "Cashmere / wol",
  fall_winter: "Musim Fall/Winter",
  spring_summer: "Musim Spring/Summer",
  other: "Lainnya",
};

const DISCOVERY_SOURCE: Record<string, string> = {
  google_places: "Google Maps",
  web_search: "Pencarian web",
  social_search: "Instagram/Facebook",
  ai_agent: "Agen AI",
};

const DISCOVERY_STATE: Record<string, string> = {
  searching: "Mencari toko",
  starting_run: "Memulai run",
  done: "Selesai",
  failed: "Gagal",
};

const SOURCE_STATUS: Record<string, string> = {
  ok: "Berhasil",
  disabled: "Tidak dipakai",
  no_api_key: "Tanpa API key",
  budget_reached: "Batas tercapai",
  error: "Gagal",
};

const BLOCK_METHOD: Record<string, string> = {
  cloudflare: "Cloudflare",
  akamai: "Akamai",
  datadome: "DataDome",
  perimeterx: "PerimeterX",
  incapsula: "Imperva (Incapsula)",
  sucuri: "Sucuri",
  http_401: "HTTP 401 (perlu login)",
  http_403: "HTTP 403 (ditolak)",
  http_429: "HTTP 429 (terlalu sering)",
  other: "Lainnya",
};

const BLOCK_STATE: Record<string, string> = {
  always: "Selalu",
  sometimes: "Kadang",
  recovered: "Pulih",
};

const TRAFFIC_CITY_KIND: Record<string, string> = {
  data_center: "Kota data center",
  own_team: "Tim sendiri?",
  other: "",
};

const TRAFFIC_SOURCE: Record<string, string> = {
  direct: "Langsung",
  social: "Media sosial",
  search: "Pencarian",
  email: "Email",
  unknown: "Tidak diketahui",
  "": "Tanpa data",
};

const TRAFFIC_DEVICE: Record<string, string> = {
  mobile: "HP",
  desktop: "Desktop",
  tablet: "Tablet",
  other: "Lainnya",
  "": "Tanpa data",
};

const TRAFFIC_PERIOD: Record<string, string> = {
  "1h": "1 jam",
  "24h": "24 jam",
  "7d": "7 hari",
};

const TRAFFIC_PROBLEM: Record<string, string> = {
  quota_low: "Kuota Analytics Shopify hampir habis; tabel memakai data terakhir sampai kuota pulih.",
  unreachable: "Shopify sedang tidak bisa dihubungi; yang tampil adalah data terakhir.",
  auth_failed: "Shopify menolak akses; periksa kredensial Shopify di .env.",
  query_failed: "Shopify menolak salah satu query; yang tampil adalah data terakhir.",
  not_configured: "Kredensial Shopify belum diisi di .env.",
};

const pick = (table: Record<string, string>) => (code: string) => table[code] ?? code;

export const storeStatus = pick(STORE_STATUS);
export const skipReason = pick(SKIP_REASON);
export const runState = pick(RUN_STATE);
export const sourceLabel = pick(SOURCE);
export const writerLabel = pick(WRITER);
export const regionLabel = pick(REGION);
export const itemLabel = pick(ITEM);
export const discoverySourceLabel = pick(DISCOVERY_SOURCE);
export const discoveryState = pick(DISCOVERY_STATE);
export const sourceStatus = pick(SOURCE_STATUS);
export const blockMethod = pick(BLOCK_METHOD);
export const blockState = pick(BLOCK_STATE);
export const trafficCityKind = pick(TRAFFIC_CITY_KIND);
export const trafficSource = pick(TRAFFIC_SOURCE);
export const trafficDevice = pick(TRAFFIC_DEVICE);
export const trafficPeriod = pick(TRAFFIC_PERIOD);
export const trafficProblem = pick(TRAFFIC_PROBLEM);

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
