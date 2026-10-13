// Every code the API returns, in English. Unknown codes fall back to the code.

const STORE_STATUS: Record<string, string> = {
  ok: "Has products",
  no_products: "No catalogue",
  js_required: "Needs a browser",
  blocked: "Blocked",
  rate_limited: "Rate limited",
  error: "Error",
};

const SKIP_REASON: Record<string, string> = {
  duplicate: "Duplicate domain",
  over_limit: "Over the store limit",
  no_website: "No website",
  invalid_url: "Invalid URL",
  social_only: "Social media",
  marketplace: "Marketplace",
};

const RUN_STATE: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  stopped: "Stopped",
  done: "Finished",
  failed: "Failed",
  interrupted: "Interrupted",
};

const SOURCE: Record<string, string> = {
  shopify_feed: "Shopify feed",
  bigcartel_feed: "Big Cartel feed",
  woocommerce_feed: "WooCommerce feed",
  squarespace_feed: "Squarespace feed",
  lightspeed_feed: "Lightspeed feed",
  magento_feed: "Magento API",
  sitemap: "Sitemap",
  crawl: "Link crawl",
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
  north_america: "North America (US & Canada)",
  united_states: "United States",
  canada: "Canada",
  europe: "Europe",
  united_kingdom: "UK & Ireland",
  oceania: "Australia & New Zealand",
  asia: "East & Southeast Asia",
};

const ITEM: Record<string, string> = {
  knitwear: "Knitwear",
  cashmere_wool: "Cashmere / wool",
  fall_winter: "Fall/Winter season",
  spring_summer: "Spring/Summer season",
  other: "Other",
};

const DISCOVERY_SOURCE: Record<string, string> = {
  google_places: "Google Maps",
  web_search: "Web search",
  social_search: "Instagram/Facebook",
  ai_agent: "AI agent",
};

// What a discovery pays for: its sources, the website lookup and the run's LLM stage.
const COST_LINE: Record<string, string> = {
  ...DISCOVERY_SOURCE,
  resolve: "Website lookup",
  llm: "Reading stores (LLM)",
};

const CACHE_KIND: Record<string, string> = {
  pages: "Saved store pages",
  search: "Search answers",
  llm: "LLM answers",
};

// What deleting each cache costs: said before the operator confirms.
const CACHE_LOSS: Record<string, string> = {
  pages: "The next run fetches these pages from the stores again.",
  search: "Repeating a search asks the search services and the AI agent again, and is paid for again.",
  llm: "Text the LLM has read before is sent, and paid for, again.",
  all: "Pages are fetched again; search and LLM answers are asked, and paid for, again.",
};

const DISCOVERY_STATE: Record<string, string> = {
  searching: "Finding stores",
  starting_run: "Starting the run",
  done: "Finished",
  failed: "Failed",
};

const SOURCE_STATUS: Record<string, string> = {
  ok: "Succeeded",
  disabled: "Not used",
  no_api_key: "No API key",
  budget_reached: "Limit reached",
  error: "Failed",
};

const BLOCK_METHOD: Record<string, string> = {
  cloudflare: "Cloudflare",
  akamai: "Akamai",
  datadome: "DataDome",
  perimeterx: "PerimeterX",
  incapsula: "Imperva (Incapsula)",
  sucuri: "Sucuri",
  http_401: "HTTP 401 (login required)",
  http_403: "HTTP 403 (refused)",
  http_429: "HTTP 429 (too many requests)",
  other: "Other",
};

const BLOCK_STATE: Record<string, string> = {
  always: "Always",
  sometimes: "Sometimes",
  recovered: "Recovered",
};

const TRAFFIC_CITY_KIND: Record<string, string> = {
  data_center: "Data center city",
  own_team: "Own team?",
  other: "",
};

const TRAFFIC_SOURCE: Record<string, string> = {
  direct: "Direct",
  social: "Social media",
  search: "Search",
  email: "Email",
  unknown: "Unknown",
  "": "No data",
};

const TRAFFIC_DEVICE: Record<string, string> = {
  mobile: "Mobile",
  desktop: "Desktop",
  tablet: "Tablet",
  other: "Other",
  "": "No data",
};

const TRAFFIC_PERIOD: Record<string, string> = {
  "1h": "1 hour",
  "24h": "24 hours",
  "7d": "7 days",
};

const TRAFFIC_PROBLEM: Record<string, string> = {
  quota_low: "The Shopify Analytics quota is almost used up; the tables show the last data until it recovers.",
  unreachable: "Shopify cannot be reached right now; this is the last data received.",
  auth_failed: "Shopify refused access; check the Shopify credentials in .env.",
  query_failed: "Shopify rejected one of the queries; this is the last data received.",
  not_configured: "The Shopify credentials are not set in .env yet.",
};

// What kind of shop a store is (ADR 0010); the final list keeps multi-brand stores.
const STORE_TYPE: Record<string, string> = {
  multi_brand: "Multi-brand",
  own_brand: "Own label",
  unknown: "Unclear",
  "": "—",
};

const STORE_TYPE_SOURCE: Record<string, string> = {
  vendors: "From product vendors",
  llm: "Judged by the LLM",
  "": "—",
};

const KNIT_KIND: Record<string, string> = {
  garment: "Knitted garment",
  accessory: "Knitted accessory",
  "": "Not knitwear",
};

// Retailer map: codes written by the process (process/build_dashboard.py).
const TERRITORY: Record<string, string> = {
  open: "Open territory",
  near: "Stockist nearby",
  unknown: "Location unknown",
};

const BRAND_KIND: Record<string, string> = {
  rival: "Knitwear rival",
  marker: "Marker brand",
};

const LOCATOR_STATUS: Record<string, string> = {
  full: "Full list",
  area: "Area search only",
  robots: "robots.txt disallows",
  own: "Own shops only",
  none: "No list",
};

const MATCH_GROUP: Record<string, string> = {
  same: "Same store as a stockist",
  check: "Same name, to check by hand",
  near: "Not ours, stockist nearby",
  open: "Not ours, open territory",
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
export const costLine = pick(COST_LINE);
export const cacheKind = pick(CACHE_KIND);
export const cacheLoss = pick(CACHE_LOSS);
export const discoveryState = pick(DISCOVERY_STATE);
export const sourceStatus = pick(SOURCE_STATUS);
export const blockMethod = pick(BLOCK_METHOD);
export const blockState = pick(BLOCK_STATE);
export const trafficCityKind = pick(TRAFFIC_CITY_KIND);
export const trafficSource = pick(TRAFFIC_SOURCE);
export const trafficDevice = pick(TRAFFIC_DEVICE);
export const trafficPeriod = pick(TRAFFIC_PERIOD);
export const trafficProblem = pick(TRAFFIC_PROBLEM);
export const storeType = pick(STORE_TYPE);
export const storeTypeSource = pick(STORE_TYPE_SOURCE);
export const knitKind = pick(KNIT_KIND);
export const territoryLabel = pick(TERRITORY);
export const brandKind = pick(BRAND_KIND);
export const locatorStatus = pick(LOCATOR_STATUS);
export const matchGroup = pick(MATCH_GROUP);

/** Tone for a status badge: good, warn, bad or neutral. */
export function tone(code: string): "good" | "warn" | "bad" | "neutral" {
  if (code === "ok" || code === "done" || code === "multi_brand") return "good";
  if (["no_products", "js_required", "rate_limited", "interrupted", "stopped"].includes(code)) return "warn";
  if (code === "blocked" || code === "error" || code === "failed") return "bad";
  return "neutral";
}

export const LOCALE = "en-US";

const numberFormat = new Intl.NumberFormat(LOCALE);
export const formatNumber = (n: number) => numberFormat.format(n);

/** A cost in US dollars: "US$1.55", and three decimals below ten cents ("US$0.016"). */
export const formatUsd = (usd: number) => `US$${usd.toFixed(usd > 0 && usd < 0.1 ? 3 : 2)}`;

/** A size on disk: "0 B", "840 KB", "1.2 GB". */
export function formatBytes(bytes: number): string {
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${unit === 0 || value >= 100 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

/** A count with its noun: "1 store", "2 stores". */
export const plural = (n: number, one: string, many = `${one}s`) => `${formatNumber(n)} ${n === 1 ? one : many}`;

export function formatTime(iso: string): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(LOCALE, { dateStyle: "medium", timeStyle: "short" });
}
