import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Run } from "../api/client";
import { RunDetail } from "./RunPage";

const RUN_ID = "20261005T085253123Z-56162b";

function run(overrides: Partial<Run> = {}): Run {
  return {
    run_id: RUN_ID,
    state: "done",
    mode: "test",
    limit: 2,
    started_at: "2026-10-05T08:52:53+00:00",
    finished_at: "2026-10-05T08:53:08+00:00",
    source_kind: "text",
    source_name: "Tautan yang ditempel",
    writers: ["xlsx"],
    links_in: 4,
    processed: 2,
    skipped: 2,
    skipped_by_reason: { over_limit: 1, social_only: 1 },
    stores_total: 2,
    stores_done: 2,
    status_counts: { ok: 1, blocked: 1 },
    products: 780,
    pages: 2,
    contacts: 8,
    final_stores: 1,
    final_products: 12,
    knit_products: 20,
    stores: [
      { domain: "monkees.com", url: "https://monkees.com", status: "ok", error: "", platform: "shopify", currency: "USD", source_used: "shopify_feed", product_count: 780, page_count: 1, contact_count: 8, ssl_bypassed: false },
      { domain: "blocked.com", url: "https://blocked.com", status: "blocked", error: "HTTP 403", platform: "", currency: "", source_used: "none", product_count: 0, page_count: 0, contact_count: 0, ssl_bypassed: false },
    ],
    downloads: [
      { key: "report", label: "Laporan run (.md)", filename: "report.md" },
      { key: "xlsx", label: "Excel (.xlsx)", filename: "tables.xlsx" },
    ],
    error: "",
    config: { limit: 2, output: { writers: ["xlsx"] } },
    cli: "uv run scrapebot run links.txt --limit 2 -f xlsx",
    llm_model: "",
    llm_cost_usd: 0,
    llm_stores: 0,
    ...overrides,
  };
}

const ROWS = {
  final_stores: { table: "final_stores", columns: ["run_id", "domain", "store_type", "knit_products"], total: 1, offset: 0, truncated_fields: false,
    rows: [{ run_id: RUN_ID, domain: "monkees.com", store_type: "multi_brand", knit_products: 12 }] },
  stores: { table: "stores", columns: ["run_id", "domain", "status"], total: 2, offset: 0, truncated_fields: false,
    rows: [{ run_id: RUN_ID, domain: "monkees.com", status: "ok" }, { run_id: RUN_ID, domain: "blocked.com", status: "blocked" }] },
  products: { table: "products", columns: ["run_id", "domain", "title", "price"], total: 1, offset: 0, truncated_fields: false,
    rows: [{ run_id: RUN_ID, domain: "monkees.com", title: "Cher Sweater", price: 139 }] },
};

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      const table = url.match(/rows\/(\w+)/)?.[1] as keyof typeof ROWS | undefined;
      const body = table && ROWS[table] ? ROWS[table] : { table, columns: [], total: 0, offset: 0, truncated_fields: false, rows: [] };
      return Promise.resolve(new Response(JSON.stringify(body)));
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("RunDetail", () => {
  it("shows the reconciliation, the progress and what needs a look", () => {
    render(<RunDetail run={run()} />);
    expect(screen.getByTestId("reconciliation")).toHaveTextContent("Tautan masuk 4 = diproses 2 + dilewati 2 ✓ seimbang");
    expect(screen.getByText("Di luar batas jumlah toko: 1")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "2");
    expect(within(screen.getByRole("region", { name: "Perlu dilihat" })).getByText("HTTP 403")).toBeInTheDocument();
  });

  it("opens on the final list: multi-brand stores that sell knitwear", async () => {
    render(<RunDetail run={run()} />);
    expect(screen.getByText("toko multi-brand, 12 produk rajut")).toBeInTheDocument();
    const result = screen.getByRole("region", { name: "Hasil" });
    expect(within(result).getByRole("tab", { name: /Final: toko/ })).toHaveAttribute("aria-selected", "true");
    expect(await within(result).findByText("Multi-brand")).toHaveClass("badge-good");
  });

  it("previews the data: table with status badges, then the raw JSON", async () => {
    const user = userEvent.setup();
    render(<RunDetail run={run()} />);
    const result = screen.getByRole("region", { name: "Hasil" });
    await user.click(within(result).getByRole("tab", { name: /^Toko/ }));
    expect(await within(result).findByText("blocked.com")).toBeInTheDocument();
    expect(within(result).getByText("Diblokir")).toHaveClass("badge-bad");
    expect(within(result).queryByText("run_id")).not.toBeInTheDocument();

    await user.click(within(result).getByRole("tab", { name: /Produk/ }));
    expect(await within(result).findByText("Cher Sweater")).toBeInTheDocument();
    await user.click(within(result).getByRole("tab", { name: "JSON" }));
    expect(within(result).getByTestId("json-view")).toHaveTextContent('"title": "Cher Sweater"');
    await user.click(within(result).getByRole("tab", { name: "PARAMETER" }));
    expect(within(result).getByText("uv run scrapebot run links.txt --limit 2 -f xlsx")).toBeInTheDocument();
  });

  it("offers every download once a run is done", () => {
    render(<RunDetail run={run()} />);
    expect(screen.getByRole("region", { name: "Unduh hasil" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Unduh Excel (.xlsx)" })).toHaveAttribute("href", `/api/runs/${RUN_ID}/download/xlsx`);
  });

  it("has no downloads while running", () => {
    render(<RunDetail run={run({ state: "running", stores_done: 1, downloads: [] })} />);
    expect(screen.queryByRole("region", { name: "Unduh hasil" })).not.toBeInTheDocument();
  });

  it("says when a run failed", () => {
    render(<RunDetail run={run({ state: "failed", error: "RuntimeError: disk full" })} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Run gagal: RuntimeError: disk full");
  });
});

describe("stop and resume", () => {
  it("offers Hentikan while running and Lanjutkan when stopped", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<RunDetail run={run({ state: "running", stores_done: 1, downloads: [] })} />);
    await user.click(screen.getByRole("button", { name: /Hentikan/ }));
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(`/api/runs/${RUN_ID}/stop`, { method: "POST" });
    unmount();

    const onRestart = vi.fn();
    render(<RunDetail run={run({ state: "stopped", stores_done: 1, downloads: [] })} onRestart={onRestart} />);
    expect(screen.getByText(/1 dari 2 toko selesai/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Lanjutkan/ }));
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(`/api/runs/${RUN_ID}/resume`, { method: "POST" });
    expect(onRestart).toHaveBeenCalled();
  });
});
