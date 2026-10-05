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
export type PreviewTable = "stores" | "products" | "contacts" | "pages" | "inputs";

export const FINISHED: readonly RunState[] = ["done", "failed", "interrupted"];

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, init);
  if (resp.ok) return (await resp.json()) as T;
  let code = "http_error";
  let message = `Permintaan gagal (HTTP ${resp.status}).`;
  try {
    const body = await resp.json();
    const detail = body?.detail;
    if (detail && typeof detail === "object" && "code" in detail) {
      code = detail.code;
      message = detail.message;
    } else if (Array.isArray(detail) && detail[0]?.msg) {
      message = detail[0].msg;
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
  startFullRun: (testRunId: string) =>
    request<Run>(`/api/runs/${testRunId}/full`, { method: "POST" }),
  runs: () => request<RunListItem[]>("/api/runs"),
  run: (runId: string) => request<Run>(`/api/runs/${runId}`),
  overview: () => request<Overview>("/api/overview"),
  rows: (runId: string, table: PreviewTable, offset = 0, limit = 50) =>
    request<Rows>(`/api/runs/${runId}/rows/${table}?offset=${offset}&limit=${limit}`),
  eventsUrl: (runId: string) => `/api/runs/${runId}/events`,
  downloadUrl: (runId: string, key: string) => `/api/runs/${runId}/download/${key}`,
};
