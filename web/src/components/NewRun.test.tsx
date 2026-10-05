import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NewRun } from "./NewRun";

const OPTIONS = {
  writers: ["json", "csv", "xlsx", "parquet"],
  default_writers: ["xlsx", "csv"],
  suffixes: [".txt", ".csv"],
  max_links: 1000,
  default_test_limit: 2,
  max_upload_mb: 20,
};

function preview(overrides = {}) {
  return {
    links: 3,
    stores: 2,
    duplicates: 0,
    skipped: { social_only: 1 },
    skipped_examples: [],
    store_examples: ["a.com", "b.com"],
    max_links: 1000,
    too_many: false,
    tested: false,
    ...overrides,
  };
}

const reply = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));

let calls: { url: string; body: unknown }[];

function mockApi(previewBody = preview(), runReply: () => Promise<Response> = () => reply({ run_id: "R1" }, 202)) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (url === "/api/options") return reply(OPTIONS);
      if (url === "/api/preview") return reply(previewBody);
      if (url === "/api/runs") return runReply();
      return reply({}, 404);
    }),
  );
}

beforeEach(() => {
  window.location.hash = "";
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("NewRun", () => {
  it("previews pasted links, then starts a test run", async () => {
    mockApi();
    const user = userEvent.setup();
    render(<NewRun />);

    const run = await screen.findByRole("button", { name: "Jalankan uji (2 toko)" });
    expect(run).toBeDisabled();

    await user.type(screen.getByRole("textbox", { name: "Tautan toko" }), "a.com b.com");
    expect(await screen.findByTestId("preview")).toHaveTextContent("Terdeteksi 3 tautan · 2 toko unik");
    expect(screen.getByTestId("preview")).toHaveTextContent("Media sosial 1");

    await waitFor(() => expect(run).toBeEnabled());
    await user.click(run);

    await waitFor(() => expect(window.location.hash).toBe("#/runs/R1"));
    const started = calls.find((c) => c.url === "/api/runs");
    expect(started?.body).toEqual({
      source: { text: "a.com b.com" },
      url_column: "auto",
      writers: ["xlsx", "csv"],
      test_mode: true,
      test_limit: 2,
      skip_test_run: false,
    });
  });

  it("asks for confirmation before a full run of an untested list", async () => {
    mockApi(preview({ tested: false }));
    const user = userEvent.setup();
    render(<NewRun />);
    await user.type(await screen.findByRole("textbox", { name: "Tautan toko" }), "a.com");
    await user.click(screen.getByRole("checkbox", { name: "Jalankan beberapa toko pertama dulu" }));

    const run = screen.getByRole("button", { name: "Jalankan semua" });
    expect(await screen.findByText(/belum pernah diuji/)).toBeInTheDocument();
    expect(run).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: "Saya sengaja melewati mode uji" }));
    await waitFor(() => expect(run).toBeEnabled());
  });

  it("blocks lists over the limit and needs at least one format", async () => {
    mockApi(preview({ too_many: true, links: 1500 }));
    const user = userEvent.setup();
    render(<NewRun />);
    await user.type(await screen.findByRole("textbox", { name: "Tautan toko" }), "a.com");
    expect(await screen.findByText(/Terlalu banyak/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Jalankan uji/ })).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: "Excel" }));
    await user.click(screen.getByRole("checkbox", { name: "CSV" }));
    expect(screen.getByText("Pilih minimal satu format.")).toBeInTheDocument();
  });

  it("shows the server's explanation when a run cannot start", async () => {
    mockApi(preview(), () =>
      reply({ detail: { code: "bad_input", message: "The input holds no links" } }, 422),
    );
    const user = userEvent.setup();
    render(<NewRun />);
    await user.type(await screen.findByRole("textbox", { name: "Tautan toko" }), "a.com");
    const run = screen.getByRole("button", { name: /Jalankan uji/ });
    await waitFor(() => expect(run).toBeEnabled());
    await user.click(run);
    expect(await screen.findByRole("alert")).toHaveTextContent("The input holds no links");
  });
});
