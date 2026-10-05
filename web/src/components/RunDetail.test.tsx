import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Run } from "../api/client";
import { RunDetail } from "./RunView";

function run(overrides: Partial<Run> = {}): Run {
  return {
    run_id: "20261005T085253123Z-56162b",
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
    stores: [
      { domain: "monkees.com", url: "https://monkees.com", status: "ok", error: "", platform: "shopify", currency: "USD", source_used: "shopify_feed", product_count: 780, page_count: 1, contact_count: 8, ssl_bypassed: false },
      { domain: "blocked.com", url: "https://blocked.com", status: "blocked", error: "HTTP 403", platform: "", currency: "", source_used: "none", product_count: 0, page_count: 0, contact_count: 0, ssl_bypassed: true },
    ],
    downloads: [
      { key: "report", label: "Laporan run (.md)", filename: "report.md" },
      { key: "xlsx", label: "Excel (.xlsx)", filename: "tables.xlsx" },
    ],
    error: "",
    ...overrides,
  };
}

describe("RunDetail", () => {
  it("shows the reconciliation, the stores and what needs a look", () => {
    render(<RunDetail run={run()} />);
    expect(screen.getByTestId("reconciliation")).toHaveTextContent(
      "Tautan masuk 4 = diproses 2 + dilewati 2 ✓ seimbang",
    );
    expect(screen.getByText("Di luar mode uji: 1")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "2");
    expect(screen.getByRole("link", { name: "monkees.com" })).toHaveAttribute("href", "https://monkees.com");
    expect(screen.getByText("TLS")).toBeInTheDocument();
    expect(screen.getByText("(HTTP 403)")).toBeInTheDocument();
  });

  it("offers the full run and the downloads once a test run is done", () => {
    render(<RunDetail run={run()} />);
    expect(screen.getByRole("button", { name: "Jalankan seluruh daftar (4 tautan)" })).toBeEnabled();
    expect(screen.getByRole("link", { name: "Excel (.xlsx)" })).toHaveAttribute(
      "href",
      "/api/runs/20261005T085253123Z-56162b/download/xlsx",
    );
  });

  it("hides downloads and the full run while running", () => {
    render(<RunDetail run={run({ state: "running", stores_done: 1, downloads: [] })} />);
    expect(screen.queryByText("Unduh hasil")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /seluruh daftar/ })).not.toBeInTheDocument();
  });

  it("does not offer a full run after a full run", () => {
    render(<RunDetail run={run({ mode: "full", limit: null })} />);
    expect(screen.queryByRole("button", { name: /seluruh daftar/ })).not.toBeInTheDocument();
  });

  it("says when a run failed", () => {
    render(<RunDetail run={run({ state: "failed", error: "RuntimeError: disk full" })} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Run gagal: RuntimeError: disk full");
  });
});
