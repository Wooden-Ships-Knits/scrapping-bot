// Typed calls to the local API. Types come from the generated OpenAPI schema
// (`pnpm gen:api`), so a change on the Python side breaks the build here.
import type { components } from "./schema";

type Schemas = components["schemas"];
export type Options = Schemas["OptionsOut"];
export type Preview = Schemas["PreviewOut"];
export type Run = Schemas["RunOut"];
export type RunListItem = Schemas["RunListItem"];
export type RunState = Run["state"];
export type Store = Schemas["StoreOut"];
export type Source = Schemas["SourceIn"];
export type RunRequest = Schemas["RunIn"];
export type Upload = Schemas["UploadOut"];
export type Rows = Schemas["RowsOut"];
export type Overview = Schemas["OverviewOut"];
export type DiscoverOptions = Schemas["DiscoverOptionsOut"];
export type Discovery = Schemas["DiscoveryOut"];
export type DiscoverRequest = Schemas["DiscoverIn"];
export type DiscoverEstimate = Schemas["DiscoverEstimateOut"];
export type Interpreted = Schemas["InterpretOut"];
export type Scorecard = Schemas["Scorecard"];
export type Cache = Schemas["CacheOut"];
export type Detection = Schemas["DetectionOut"];
export type Traffic = Schemas["TrafficSnapshot"];
export type TrafficPeriod = Traffic["period"];
export type RetailerMap = Schemas["RetailerMapOut"];
export type PreviewTable =
  | "final_stores"
  | "final_products"
  | "knit_products"
  | "stores"
  | "products"
  | "contacts"
  | "pages"
  | "inputs";

export const FINISHED: readonly RunState[] = ["done", "failed", "interrupted", "stopped"];

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

/** The server answered, but does not know the request: it was started before the code
 *  this page was built from. It loads its code once, so it has to be started again. */
export const SERVER_OUTDATED =
  "The server is running older code than this page. Stop it and start it again (make serve), then reload.";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, init);
  if (resp.ok) return (await resp.json()) as T;
  let code = "http_error";
  let message = `The request failed (HTTP ${resp.status}).`;
  try {
    const body = await resp.json();
    const detail = body?.detail;
    if (detail && typeof detail === "object" && "code" in detail) {
      code = detail.code;
      message = detail.message;
    } else if (Array.isArray(detail) && detail[0]?.msg) {
      message = detail[0].msg;
    } else if (resp.status === 405 || (resp.status === 404 && detail === "Not Found")) {
      // The framework's own answer for a route or method it does not have. Every
      // "not found" of the API itself carries a code.
      code = "server_outdated";
      message = SERVER_OUTDATED;
    }
  } catch {
    // keep the generic message
  }
  throw new ApiError(resp.status, code, message);
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  options: () => request<Options>("/api/options"),
  preview: (source: Source, urlColumn: string) =>
    request<Preview>("/api/preview", json({ source, url_column: urlColumn })),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Upload>("/api/uploads", { method: "POST", body: form });
  },
  startRun: (body: RunRequest) => request<Run>("/api/runs", json(body)),
  discoverOptions: () => request<DiscoverOptions>("/api/discover/options"),
  discoverEstimate: (count: number, region: string, place = "", rescrape = false) =>
    request<DiscoverEstimate>(
      `/api/discover/estimate?count=${count}&region=${encodeURIComponent(region)}` +
        (place ? `&place=${encodeURIComponent(place)}` : "") +
        (rescrape ? "&rescrape=true" : ""),
    ),
  interpret: (prompt: string) => request<Interpreted>("/api/discover/interpret", json({ prompt })),
  startDiscovery: (body: DiscoverRequest) => request<Discovery>("/api/discover", json(body)),
  discovery: (discoveryId: string) => request<Discovery>(`/api/discover/${discoveryId}`),
  stopRun: (runId: string) => request<Run>(`/api/runs/${runId}/stop`, { method: "POST" }),
  resumeRun: (runId: string) => request<Run>(`/api/runs/${runId}/resume`, { method: "POST" }),
  runs: () => request<RunListItem[]>("/api/runs"),
  run: (runId: string) => request<Run>(`/api/runs/${runId}`),
  runQuality: (runId: string) => request<Scorecard>(`/api/runs/${runId}/quality`),
  deleteRun: (runId: string) => request<Schemas["DeletedOut"]>(`/api/runs/${runId}`, { method: "DELETE" }),
  cache: () => request<Cache>("/api/cache"),
  clearCache: (kind: string) => request<Cache>(`/api/cache/${kind}`, { method: "DELETE" }),
  overview: () => request<Overview>("/api/overview"),
  detection: () => request<Detection>("/api/detection"),
  retailerMap: () => request<RetailerMap>("/api/retailer-map"),
  traffic: (period: TrafficPeriod) => request<Traffic>(`/api/traffic?period=${period}`),
  rows: (runId: string, table: PreviewTable, offset = 0, limit = 50) =>
    request<Rows>(`/api/runs/${runId}/rows/${table}?offset=${offset}&limit=${limit}`),
  eventsUrl: (runId: string) => `/api/runs/${runId}/events`,
  downloadUrl: (runId: string, key: string) => `/api/runs/${runId}/download/${key}`,
};
