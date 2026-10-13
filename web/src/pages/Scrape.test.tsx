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
    read_before: 0,
    read_before_latest: "",
    reuse_days: 30,
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
      rescrape: false,
    });
    expect(screen.queryByTestId("read-before")).not.toBeInTheDocument();
  });

  it("says which stores were scraped before, and scrapes them again when asked", async () => {
    mockApi(preview({ read_before: 1, read_before_latest: "2026-10-09T03:00:00+00:00" }));
    const user = userEvent.setup();
    render(<Scrape />);
    await user.type(await screen.findByRole("textbox", { name: "Store links" }), "a.com b.com");

    const notice = await screen.findByTestId("read-before");
    expect(notice).toHaveTextContent("1 of 2 stores already scraped in the last 30 days (latest Oct 9, 2026");
    expect(notice).toHaveTextContent("Their data will be loaded from that run, not scraped again");

    await user.click(screen.getByRole("checkbox", { name: "Scrape them again anyway" }));
    expect(notice).toHaveTextContent("They will be scraped again.");
    expect(screen.getByText(/uv run scrapebot run/)).toHaveTextContent("--rescrape");
    const run = screen.getByRole("button", { name: "Start scraping" });
    await waitFor(() => expect(run).toBeEnabled());
    await user.click(run);
    await waitFor(() => expect(calls.find((c) => c.url === "/api/runs")?.body).toMatchObject({ rescrape: true }));
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
  reuse_days: 30,
  prompt_model: "openai/gpt-4o-mini",
  max_prompt_chars: 300,
  sources: { google_places: false, web_search: false, social_search: false, ai_agent: true },
};

const ESTIMATE = {
  count: 20,
  lines: [
    { name: "ai_agent", max_usd: 0.48, note: "nothing while Gemini's free tier lasts" },
    { name: "resolve", max_usd: 0.16, note: "" },
    { name: "llm", max_usd: 0.02, note: "" },
  ],
  max_usd: 0.66,
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

const OUT_OF_SCOPE =
  "This request is outside the scope of Scrapebot. Please provide a store, brand, product, or wholesale research request.";

function mockFind(findOptions = FIND_OPTIONS, interpreted: object | null = null) {
  calls = [];
  let polls = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (url === "/api/options") return reply(OPTIONS);
      if (url === "/api/discover/options") return reply(findOptions);
      if (url.startsWith("/api/discover/estimate")) return reply(ESTIMATE);
      if (url === "/api/discover/interpret")
        return interpreted
          ? reply(interpreted)
          : reply({ detail: { code: "out_of_scope", message: OUT_OF_SCOPE } }, 422);
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
      rescrape: false,
      place: "",
      country: "",
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
            sources: [{ name: "ai_agent", status: "ok", found: 12, error: "", notes: [note], cost_usd: 0.31 }],
            cost_usd: 0.326,
          }) as Discovery
        }
      />,
    );
    expect(screen.getByTestId("discovery-notes")).toHaveTextContent(`AI agent: ${note}`);
    expect(screen.getByTestId("discovery-cost")).toHaveTextContent("Estimated API cost of this search: US$0.33");
  });

  it("says what a search can cost before it starts", async () => {
    mockFind();
    render(<Scrape />);
    const estimate = await screen.findByTestId("find-estimate");
    expect(estimate).toHaveTextContent("Estimated cost for 20 stores: up to US$0.66");
    expect(estimate).toHaveTextContent("AI agent up to US$0.48 (nothing while Gemini's free tier lasts)");
    expect(estimate).toHaveTextContent("Website lookup up to US$0.16 · Reading stores (LLM) up to US$0.020");
    expect(calls.some((c) => c.url === "/api/discover/estimate?count=20&region=north_america")).toBe(true);
  });

  it("fills in the form from a search written in words, and searches only on start", async () => {
    mockFind(FIND_OPTIONS, {
      items: ["cashmere_wool", "knitwear"],
      terms: [],
      region: "",
      place: "Las Vegas, NV",
      country: "US",
      count: null,
      cost_usd: 0.0001,
      cached: false,
    });
    const user = userEvent.setup();
    render(<Scrape />);
    const find = await screen.findByRole("button", { name: "Find stores & start scraping" });

    const box = screen.getByRole("textbox", { name: "Describe the search (optional)" });
    await user.type(box, "seaf=rch data for cashmere/knitewaer in las vegasa{Enter}");
    expect(await screen.findByTestId("prompt-note")).toHaveTextContent(
      "Understood: Cashmere / wool, Knitwear · Las Vegas, NV (US). Check the fields below, then start.",
    );
    expect(calls.some((c) => c.url === "/api/discover"), "Enter never starts the paid search").toBe(false);
    expect(screen.getByTestId("find-place")).toHaveTextContent("Las Vegas, NV (US)");
    expect(screen.getByRole("checkbox", { name: "Cashmere / wool" })).toBeChecked();
    expect(screen.queryByRole("combobox", { name: "Region" })).not.toBeInTheDocument();

    await waitFor(() => expect(find).toBeEnabled());
    await user.click(find);
    await waitFor(() =>
      expect(calls.find((c) => c.url === "/api/discover")?.body).toMatchObject({
        count: 20,
        items: ["cashmere_wool", "knitwear"],
        place: "Las Vegas, NV",
        country: "US",
      }),
    );
  });

  it("refuses a request that is not a store search and leaves the form alone", async () => {
    mockFind();
    const user = userEvent.setup();
    render(<Scrape />);
    await screen.findByRole("button", { name: "Find stores & start scraping" });
    await user.type(screen.getByRole("textbox", { name: "Describe the search (optional)" }), "best casinos in vegas");
    await user.click(screen.getByRole("button", { name: "Fill in the form" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(OUT_OF_SCOPE);
    expect(screen.getByRole("combobox", { name: "Region" })).toHaveValue("north_america");
    expect(screen.getByRole("checkbox", { name: "Knitwear" })).toBeChecked();
    expect(calls.some((c) => c.url === "/api/discover")).toBe(false);
  });

  it("can scrape again the stores a run read recently", async () => {
    mockFind();
    const user = userEvent.setup();
    render(<Scrape />);
    const find = await screen.findByRole("button", { name: "Find stores & start scraping" });
    await user.click(screen.getByRole("checkbox", { name: /Scrape again stores already read in the last 30 days/ }));
    await waitFor(() => expect(find).toBeEnabled());
    await user.click(find);
    await waitFor(() => expect(calls.find((c) => c.url === "/api/discover")?.body).toMatchObject({ rescrape: true }));
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
