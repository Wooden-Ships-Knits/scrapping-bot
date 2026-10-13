import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { History } from "./History";

const run = (run_id: string, state = "done") => ({
  run_id,
  state,
  mode: "full",
  started_at: "2026-10-13T04:01:57+00:00",
  source_name: "to_visit.csv",
  links_in: 100,
  stores_total: 100,
  stores_done: state === "running" ? 53 : 100,
  products: 12000,
  contacts: 300,
});

const A = "20261013T040157472Z-aaaaaa";
const B = "20261012T093718738Z-bbbbbb";
const LIVE = "20261013T050000000Z-cccccc";

const cacheBody = (busy = false, searchFiles = 12) => ({
  kinds: [
    { name: "pages", files: 4200, bytes: 3 * 1024 * 1024 * 1024 },
    { name: "search", files: searchFiles, bytes: searchFiles ? 840 * 1024 : 0 },
    { name: "llm", files: 0, bytes: 0 },
  ],
  busy,
});

const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));

let calls: string[];

function mockApi({ busy = false, refuse = "" } = {}) {
  calls = [];
  let runs = [run(LIVE, "running"), run(A), run(B)];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      calls.push(`${method} ${url}`);
      if (method === "DELETE" && url.startsWith("/api/runs/")) {
        const id = url.split("/").pop() ?? "";
        if (id === refuse) return reply({ detail: { code: "run_active", message: "This run is still going. Stop it first." } }, 409);
        runs = runs.filter((r) => r.run_id !== id);
        return reply({ run_id: id });
      }
      if (method === "DELETE" && url.startsWith("/api/cache/")) return reply(cacheBody(busy, 0));
      if (url === "/api/runs") return reply(runs);
      if (url === "/api/cache") return reply(cacheBody(busy));
      return reply({}, 404);
    }),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("History: deleting runs", () => {
  it("deletes one run only after the operator confirms what is lost", async () => {
    mockApi();
    const user = userEvent.setup();
    render(<History />);

    await user.click(await screen.findByRole("button", { name: "Delete run aaaaaa" }));
    const confirm = screen.getByTestId("confirm");
    expect(confirm).toHaveTextContent("Delete 1 run?");
    expect(confirm).toHaveTextContent("their stores count as not read");
    expect(confirm).toHaveTextContent("This cannot be undone.");
    expect(calls.some((c) => c.startsWith("DELETE")), "nothing is deleted before the confirmation").toBe(false);

    await user.click(within(confirm).getByRole("button", { name: "Delete 1 run" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Delete run aaaaaa" })).not.toBeInTheDocument());
    expect(calls).toContain(`DELETE /api/runs/${A}`);
    expect(screen.getByRole("button", { name: "Delete run bbbbbb" })).toBeInTheDocument();
  });

  it("selects every run that is not still going, and can be cancelled", async () => {
    mockApi();
    const user = userEvent.setup();
    render(<History />);

    await user.click(await screen.findByRole("checkbox", { name: "Select all runs" }));
    expect(screen.getByRole("checkbox", { name: "Select run aaaaaa" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select run cccccc" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Delete run cccccc" })).toBeDisabled();
    expect(screen.getByText("2 runs selected")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Delete selected/ }));
    expect(screen.getByTestId("confirm")).toHaveTextContent("Delete 2 runs?");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByTestId("confirm")).not.toBeInTheDocument();
    expect(calls.some((c) => c.startsWith("DELETE"))).toBe(false);

    await user.click(screen.getByRole("button", { name: /Delete selected/ }));
    await user.click(screen.getByRole("button", { name: "Delete 2 runs" }));
    await waitFor(() => expect(calls.filter((c) => c.startsWith("DELETE /api/runs/"))).toHaveLength(2));
  });

  it("names a run that could not be deleted and deletes the rest", async () => {
    mockApi({ refuse: A });
    const user = userEvent.setup();
    render(<History />);
    await user.click(await screen.findByRole("checkbox", { name: "Select all runs" }));
    await user.click(screen.getByRole("button", { name: /Delete selected/ }));
    await user.click(screen.getByRole("button", { name: "Delete 2 runs" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Not deleted: #aaaaaa: This run is still going. Stop it first.",
    );
    expect(calls).toContain(`DELETE /api/runs/${B}`);
  });
});

describe("History: deleting caches", () => {
  it("shows what each cache holds and says what deleting it costs", async () => {
    mockApi();
    const user = userEvent.setup();
    render(<History />);

    const card = await screen.findByTestId("cache");
    expect(card).toHaveTextContent("Saved store pages");
    expect(card).toHaveTextContent("3.0 GB");
    expect(card).toHaveTextContent("840 KB");
    const row = (name: string) => within(card).getByText(name).closest("tr") as HTMLElement;
    expect(
      within(row("LLM answers")).getByRole("button", { name: "Delete" }),
      "an empty cache has nothing to delete",
    ).toBeDisabled();

    await user.click(within(row("Search answers")).getByRole("button", { name: "Delete" }));
    const confirm = within(card).getByTestId("confirm");
    expect(confirm).toHaveTextContent('Delete the cache "Search answers"?');
    expect(confirm).toHaveTextContent("is paid for again");
    await user.click(within(confirm).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(calls).toContain("DELETE /api/cache/search"));

    await user.click(within(card).getByRole("button", { name: "Delete all caches" }));
    expect(within(card).getByTestId("confirm")).toHaveTextContent("Delete every cache?");
    await user.click(within(within(card).getByTestId("confirm")).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(calls).toContain("DELETE /api/cache/all"));
  });

  it("does not offer to delete a cache while a run or a search is under way", async () => {
    mockApi({ busy: true });
    render(<History />);
    const card = await screen.findByTestId("cache");
    expect(card).toHaveTextContent("A run or a search is under way");
    expect(within(card).getByRole("button", { name: "Delete all caches" })).toBeDisabled();
  });
});
