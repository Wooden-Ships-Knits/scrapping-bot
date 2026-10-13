import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Discovery } from "../api/client";
import { DiscoveryCard } from "./FindStores";
import { Scrape } from "./Scrape";

const OPTIONS = {
  writers: ["json", "csv", "xlsx", "parquet"],
  default_writers: ["xlsx", "csv"],
  suffixes: [".txt", ".csv"],
  max_links: 1000,
  max_upload_mb: 20,
};

function preview(overrides = {}) {
  return {
    links: 3,
    stores: 2,
    duplicates: 0,
    skipped: { social_only: 1 },
    skipped_examples: [{ raw: "https://instagram.com/x", reason: "social_only" }],
    store_examples: ["a.com", "b.com"],
    max_links: 1000,
    too_many: false,
    ...overrides,
  };
}

const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));

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

describe("Scrape", () => {
  it("previews pasted links, then starts the scrape", async () => {
    mockApi();
    const user = userEvent.setup();
    render(<Scrape />);

    const run = await screen.findByRole("button", { name: "Start scraping" });
    expect(run).toBeDisabled();

    await user.type(screen.getByRole("textbox", { name: "Store links" }), "a.com b.com");
    const card = await screen.findByTestId("preview");
    expect(card).toHaveTextContent("3 links");
    expect(card).toHaveTextContent("https://a.com");
    expect(card).toHaveTextContent("Skipped: Social media");
    expect(screen.getByTestId("link-count")).toHaveTextContent("3 links · 2 stores");

    await waitFor(() => expect(run).toBeEnabled());
    await user.click(run);

    await waitFor(() => expect(window.location.hash).toBe("#/runs/R1"));
    expect(calls.find((c) => c.url === "/api/runs")?.body).toEqual({
      source: { text: "a.com b.com" },
      url_column: "auto",
      writers: ["xlsx", "csv"],
    });
  });

  it("blocks lists over the limit and needs at least one format", async () => {
    mockApi(preview({ too_many: true, links: 1500 }));
    const user = userEvent.setup();
    render(<Scrape />);
    await user.type(await screen.findByRole("textbox", { name: "Store links" }), "a.com");
    expect(await screen.findByText(/Too many/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start scraping" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Output formats" }));
    await user.click(screen.getByRole("checkbox", { name: "Excel" }));
    await user.click(screen.getByRole("checkbox", { name: "CSV" }));
    expect(screen.getByText("Choose at least one output format.")).toBeInTheDocument();
  });

  it("shows the equivalent command line", async () => {
    mockApi();
    const user = userEvent.setup();
    render(<Scrape />);
    await screen.findByRole("button", { name: "Start scraping" });
    await user.click(screen.getByText("Equivalent command (CLI)"));
    expect(screen.getByText("uv run scrapebot run links.txt -f xlsx,csv")).toBeInTheDocument();
  });

  it("shows the server's explanation when a run cannot start", async () => {
    mockApi(preview(), () => reply({ detail: { code: "bad_input", message: "The input holds no links" } }, 422));
    const user = userEvent.setup();
    render(<Scrape />);
    await user.type(await screen.findByRole("textbox", { name: "Store links" }), "a.com");
    const run = screen.getByRole("button", { name: "Start scraping" });
    await waitFor(() => expect(run).toBeEnabled());
    await user.click(run);
    expect(await screen.findByRole("alert")).toHaveTextContent("The input holds no links");
  });
});

const FIND_OPTIONS = {
  regions: ["north_america", "europe"],
  default_region: "north_america",
  items: ["knitwear", "cashmere_wool", "fall_winter", "spring_summer", "other"],
  default_items: ["knitwear"],
  max_count: 500,
  agent_model: "openai/gpt-5-search-api",
  agent_fallbacks: [] as string[],
  sources: { google_places: false, web_search: false, social_search: false, ai_agent: true },
};

function discovery(overrides = {}) {
  return {
    discovery_id: "D1",
    state: "searching",
    count: 30,
    step: "ai_agent",
    found: 12,
    stores_to_visit: 0,
    sources: [],
    cost_usd: 0,
    run_id: null,
    error: "",
    ...overrides,
  };
}

function mockFind(findOptions = FIND_OPTIONS) {
  calls = [];
  let polls = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (url === "/api/options") return reply(OPTIONS);
      if (url === "/api/discover/options") return reply(findOptions);
      if (url === "/api/discover") return reply(discovery(), 202);
      if (url === "/api/discover/D1") {
        polls += 1;
        return reply(polls < 2 ? discovery({ found: 25 }) : discovery({ state: "done", found: 31, stores_to_visit: 30, run_id: "R9" }));
      }
      return reply({}, 404);
    }),
  );
}

describe("Scrape: find stores", () => {
  it("finds stores by count, region and items, then opens the run", async () => {
    mockFind();
    const user = userEvent.setup();
    render(<Scrape />);

    const find = await screen.findByRole("button", { name: "Find stores & start scraping" });
    expect(screen.getByRole("tab", { name: "Find stores automatically" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("find-sources")).toHaveTextContent("AI agent (openai/gpt-5-search-api)");

    const count = screen.getByRole("spinbutton", { name: /Number of stores/ });
    await user.clear(count);
    await user.type(count, "30");
    await user.selectOptions(screen.getByRole("combobox", { name: "Region" }), "europe");
    await user.click(screen.getByRole("checkbox", { name: "Fall/Winter season" }));
    await user.click(screen.getByRole("checkbox", { name: "Other" }));
    expect(find).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Keywords for other items" }), "poncho, cape");
    await waitFor(() => expect(find).toBeEnabled());
    await user.click(find);

    expect(await screen.findByTestId("discovery")).toHaveTextContent("12 stores found");
    expect(calls.find((c) => c.url === "/api/discover")?.body).toEqual({
      count: 30,
      region: "europe",
      items: ["knitwear", "fall_winter", "other"],
      terms: ["poncho", "cape"],
      writers: ["xlsx", "csv"],
    });
    await waitFor(() => expect(window.location.hash).toBe("#/runs/R9"), { timeout: 4000 });
  });

  it("names the model that takes over, and shows the agent's notes", async () => {
    mockFind({ ...FIND_OPTIONS, agent_model: "gemini/gemini-2.5-flash", agent_fallbacks: ["openai/gpt-5-search-api"] });
    render(<Scrape />);
    await screen.findByRole("button", { name: "Find stores & start scraping" });
    expect(screen.getByTestId("find-sources")).toHaveTextContent(
      "AI agent (gemini/gemini-2.5-flash, then openai/gpt-5-search-api)",
    );

    const note = "gemini/gemini-2.5-flash: The provider's usage limit was reached (rate limit or quota). Continued with openai/gpt-5-search-api.";
    render(
      <DiscoveryCard
        discovery={
          discovery({
            state: "done",
            sources: [{ name: "ai_agent", status: "ok", found: 12, error: "", notes: [note] }],
          }) as Discovery
        }
      />,
    );
    expect(screen.getByTestId("discovery-notes")).toHaveTextContent(`AI agent: ${note}`);
  });

  it("refuses a count that is not a whole number in range", async () => {
    mockFind();
    const user = userEvent.setup();
    render(<Scrape />);
    const find = await screen.findByRole("button", { name: "Find stores & start scraping" });
    const count = screen.getByRole("spinbutton", { name: /Number of stores/ });
    await user.clear(count);
    await user.type(count, "0");
    expect(find).toBeDisabled();
    await user.clear(count);
    await user.type(count, "501");
    expect(find).toBeDisabled();
  });

  it("opens on pasted links when no search source has a key", async () => {
    mockFind({ ...FIND_OPTIONS, agent_model: "", sources: { ...FIND_OPTIONS.sources, ai_agent: false } });
    const user = userEvent.setup();
    render(<Scrape />);
    expect(await screen.findByRole("textbox", { name: "Store links" })).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Find stores automatically" }));
    expect(screen.getByTestId("find-sources")).toHaveTextContent("Active sources: none");
    expect(screen.getByRole("button", { name: "Find stores & start scraping" })).toBeDisabled();
  });
});
