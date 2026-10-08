import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Traffic } from "./Traffic";

function snapshot(period = "24h", overrides = {}) {
  return {
    shop: "example-store.myshopify.com",
    period,
    minutes: [
      { minute: "2026-10-08T03:59:00Z", sessions: 3 },
      { minute: "2026-10-08T04:00:00Z", sessions: 1 },
    ],
    minutes_at: new Date().toISOString(),
    series: [
      { at: "2026-10-08T03:00:00Z", sessions: 40 },
      { at: "2026-10-08T04:00:00Z", sessions: 2 },
    ],
    series_grain: period === "1h" ? "minute" : "hour",
    totals: { sessions: 120, cart_sessions: 9, checkout_sessions: 4 },
    data_center_sessions: 40,
    cities: [
      { city: "Council Bluffs", country: "United States", sessions: 60, cart_sessions: 0, kind: "data_center" },
      { city: "Denpasar", country: "Indonesia", sessions: 80, cart_sessions: 0, kind: "own_team" },
      { city: "Naples", country: "United States", sessions: 20, cart_sessions: 0, kind: "other" },
    ],
    pages: [{ path: "/collections/all", sessions: 60, cart_sessions: 5 }],
    sources: [{ name: "social", sessions: 70 }],
    devices: [{ name: "mobile", sessions: 80 }],
    breakdown_at: new Date().toISOString(),
    quota: { available: 900, maximum: 1000, resets_at: "2026-10-08T05:00:00+00:00" },
    problem: "",
    ...overrides,
  };
}

const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));

function mockApi(answer: (url: string) => Promise<Response>) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      calls.push(url);
      return answer(url);
    }),
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("Traffic", () => {
  it("shows totals, marks data-centre cities and labels sources", async () => {
    mockApi((url) => reply(snapshot(new URL(url, "http://x").searchParams.get("period") ?? "24h")));
    render(<Traffic />);
    expect(await screen.findByText("Council Bluffs")).toBeInTheDocument();
    expect(screen.getByText("Kota data center")).toBeInTheDocument();
    expect(screen.getByText("Tim sendiri?")).toBeInTheDocument();
    // 60 sessions and no cart: flagged. Denpasar is the team; 20 sessions is too few to tell.
    expect(screen.getAllByText("Banyak sesi, 0 keranjang")).toHaveLength(1);
    expect(screen.getByText("Media sosial")).toBeInTheDocument();
    expect(screen.getByText("/collections/all")).toBeInTheDocument();
    expect(screen.getByText(/^Live ·/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sesi per jam" })).toBeInTheDocument();
  });

  it("asks for the chosen period and remembers it", async () => {
    const calls = mockApi((url) => reply(snapshot(new URL(url, "http://x").searchParams.get("period") ?? "24h")));
    render(<Traffic />);
    await screen.findByText("Council Bluffs");
    await userEvent.click(screen.getByRole("tab", { name: "7 hari" }));
    await waitFor(() => expect(calls).toContain("/api/traffic?period=7d"));
    expect(localStorage.getItem("traffic-period")).toBe("7d");
    await userEvent.click(screen.getByRole("tab", { name: "1 jam" }));
    expect(await screen.findByRole("heading", { name: "Sesi per menit" })).toBeInTheDocument();
  });

  it("explains what to set when Shopify is not configured", async () => {
    mockApi(() =>
      reply({ detail: { code: "not_configured", message: "Isi SHOPIFY_STORE_DOMAIN di .env." } }, 422),
    );
    render(<Traffic />);
    expect(await screen.findByText("Isi SHOPIFY_STORE_DOMAIN di .env.")).toBeInTheDocument();
  });

  it("says when the tables are older because the quota is low", async () => {
    mockApi(() => reply(snapshot("24h", { problem: "quota_low" })));
    render(<Traffic />);
    expect(await screen.findByText(/Kuota Analytics Shopify hampir habis/)).toBeInTheDocument();
  });
});
