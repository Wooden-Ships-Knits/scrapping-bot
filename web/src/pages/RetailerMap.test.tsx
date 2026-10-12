import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RetailerMap } from "./RetailerMap";

const store = (domain: string, overrides = {}) => ({
  domain,
  name: null,
  city: null,
  state: null,
  score: 30,
  knit: 100,
  price: 120,
  currency: "USD",
  miles: null,
  territory: "unknown",
  email: false,
  watched: [],
  relevant: [],
  ...overrides,
});

// Made-up stores; the shape is RetailerMapOut.
const MAP = {
  run_id: "20261009T073717823Z-e4d60c",
  stores: 808,
  readable: 287,
  radius_miles: 15,
  watched: [
    { key: "zsupply", brand: "Z Supply", stores: 36 },
    { key: "rails", brand: "Rails", stores: 29 },
  ],
  watched_stores: 67,
  watched_customers: 3,
  watched_not_ours: 2,
  watched_email: 1,
  watched_territory: { open: 1, near: 1 },
  located: 2,
  opportunities: [
    store("near-boutique.com", {
      city: "Naples",
      state: "FL",
      miles: 2.5,
      territory: "near",
      watched: ["zsupply"],
      relevant: ["Alpha Knits", "Beta Knits", "Gamma Knits"],
    }),
    store("far-boutique.com", {
      city: "Bend",
      state: "OR",
      miles: 140.2,
      territory: "open",
      email: true,
      watched: ["zsupply", "rails"],
    }),
    store("other-boutique.com", { relevant: ["Alpha Knits"] }),
  ],
  brands: [
    { key: "alphaknits", brand: "Alpha Knits", kind: "rival", watched: false, stores: 20, shared: 3, not_ours: 17, open: 3, knit_share: 0.86, price: 0.95, rank: 0.91, full: false },
    { key: "rails", brand: "Rails", kind: "marker", watched: true, stores: 29, shared: 1, not_ours: 28, open: 9, knit_share: 0.12, price: null, rank: 0.6, full: false },
  ],
  regions: [{ state: "OR", opportunities: 4, open_territory: 4, stockists: 3 }],
  survey: [
    { brand: "Z Supply", locator: "Storemapper", status: "robots", locations: null },
    { brand: "Heartloom", locator: "Stockist.co", status: "full", locations: 415 },
  ],
  locator: {
    brand: "Heartloom",
    total: 415,
    groups: { same: 29, check: 2, near: 264, open: 120 },
    states: [{ state: "LA", brand_retailers: 21, stockists: 3, gap: 18 }],
  },
};

const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));
const mockApi = (answer: () => Promise<Response>) => vi.stubGlobal("fetch", vi.fn(answer));
const rows = () => screen.getAllByRole("row").slice(1);

afterEach(() => vi.unstubAllGlobals());

describe("RetailerMap", () => {
  it("leads with the counts and lists the stores that carry a watched brand", async () => {
    mockApi(() => reply(MAP));
    render(<RetailerMap />);
    expect(await screen.findByText("287 of 808 stores were readable.", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("Z Supply 36 · Rails 29")).toBeInTheDocument();
    expect(screen.getByText(/No stockist within 15 miles/)).toBeInTheDocument();
    // "Any watched brand" is the default: the store that carries none is left out.
    expect(rows().map((r) => within(r).getByRole("link").textContent)).toEqual(["near-boutique.com", "far-boutique.com"]);
    expect(screen.getByText("nearest stockist 2.5 mi")).toBeInTheDocument();
    expect(screen.getByText("+1")).toBeInTheDocument(); // three other brands, two named
    expect(screen.getByRole("link", { name: /Run/ })).toHaveAttribute("href", "#/runs/20261009T073717823Z-e4d60c");
  });

  it("narrows by brand, territory, email and search, and sorts by distance", async () => {
    mockApi(() => reply(MAP));
    render(<RetailerMap />);
    await screen.findByText("near-boutique.com");

    await userEvent.click(screen.getByRole("button", { name: "Territory" }));
    expect(rows().map((r) => within(r).getByRole("link").textContent)).toEqual(["far-boutique.com", "near-boutique.com"]);

    await userEvent.click(screen.getByRole("tab", { name: "Rails · 1" }));
    expect(rows()).toHaveLength(1);
    await userEvent.click(screen.getByRole("tab", { name: "All candidates · 3" }));
    expect(rows()).toHaveLength(3);
    await userEvent.click(screen.getByRole("checkbox", { name: "Has an email" }));
    expect(rows()).toHaveLength(1);
    await userEvent.click(screen.getByRole("checkbox", { name: "Has an email" }));

    await userEvent.type(screen.getByRole("searchbox", { name: "Search stores" }), "alpha");
    expect(rows().map((r) => within(r).getByRole("link").textContent)).toEqual(["near-boutique.com", "other-boutique.com"]);
    await userEvent.type(screen.getByRole("searchbox", { name: "Search stores" }), "zzz");
    expect(screen.getByText("No store matches these filters.")).toBeInTheDocument();
  });

  it("keeps the store filters while another tab is open", async () => {
    mockApi(() => reply(MAP));
    render(<RetailerMap />);
    await screen.findByText("near-boutique.com");
    await userEvent.click(screen.getByRole("tab", { name: "Rails · 1" }));

    await userEvent.click(screen.getByRole("tab", { name: /^Brands/ }));
    expect(screen.getByText("Knitwear rival")).toBeInTheDocument();
    expect(screen.getByText("86%")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Watched · 1" }));
    expect(rows()).toHaveLength(1);

    await userEvent.click(screen.getByRole("tab", { name: /^Regions/ }));
    expect(screen.getByText("OR")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: /^Published lists/ }));
    expect(screen.getByText("robots.txt disallows")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Heartloom: 415 published retailers" })).toBeInTheDocument();
    expect(screen.getByText("2 · <1%")).toBeInTheDocument();
    expect(screen.getByText("+18")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: /^Stores to approach/ }));
    expect(rows().map((r) => within(r).getByRole("link").textContent)).toEqual(["far-boutique.com"]);
  });

  it("shows the survey alone when no brand list was read", async () => {
    mockApi(() => reply({ ...MAP, locator: null }));
    render(<RetailerMap />);
    await userEvent.click(await screen.findByRole("tab", { name: /^Published lists/ }));
    expect(screen.getByText("Full list")).toBeInTheDocument();
    expect(screen.queryByText(/published retailers/)).not.toBeInTheDocument();
  });

  it("says how to start the process when no run has been processed", async () => {
    const message = "No run has been processed yet. Run: uv run --group process python process/run_all.py";
    mockApi(() => reply({ detail: { code: "no_process_output", message } }, 404));
    render(<RetailerMap />);
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });
});
