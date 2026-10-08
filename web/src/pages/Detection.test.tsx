import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Detection } from "./Detection";

const DATA = {
  visits: 20,
  blocked: 5,
  stores: 12,
  stores_blocked: 3,
  by_method: { cloudflare: 3, http_403: 2 },
  runs: [
    { run_id: "20261008T005200803Z-9cd674", started_at: "2026-10-08T00:52:00+00:00", visits: 10, blocked: 1 },
    { run_id: "20261005T101540000Z-aaaaaa", started_at: "2026-10-05T10:15:40+00:00", visits: 10, blocked: 4 },
  ],
  blocked_stores: [
    {
      domain: "dior.com",
      platform: "other",
      visits: 2,
      blocked: 2,
      state: "always",
      last_method: "http_403",
      last_run_id: "20261008T005200803Z-9cd674",
      last_seen: "2026-10-08T00:52:00+00:00",
    },
    {
      domain: "wooden-ships.com",
      platform: "shopify",
      visits: 2,
      blocked: 1,
      state: "recovered",
      last_method: "cloudflare",
      last_run_id: "20261008T005200803Z-9cd674",
      last_seen: "2026-10-08T00:52:00+00:00",
    },
  ],
};

function mockApi(body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Detection", () => {
  it("shows the block rate, how stores block, and which stores to skip", async () => {
    mockApi(DATA);
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    render(<Detection />);

    expect(await screen.findByText("25%")).toBeInTheDocument();
    expect(screen.getByText("5 dari 20 kunjungan")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Cara memblokir" })).toHaveTextContent("Cloudflare: 3");

    const stores = screen.getByRole("region", { name: "Toko yang memblokir" });
    const dior = within(stores).getByRole("row", { name: /dior\.com/ });
    expect(within(dior).getByText("Selalu")).toHaveClass("badge-bad");
    expect(dior).toHaveTextContent("2 / 2");
    expect(dior).toHaveTextContent("HTTP 403 (ditolak)");
    expect(within(stores).getByRole("row", { name: /wooden-ships\.com/ })).toHaveTextContent("Pulih");

    await user.click(within(stores).getByRole("button", { name: "Salin 1 toko yang selalu memblokir" }));
    expect(writeText).toHaveBeenCalledWith("dior.com");

    const runs = screen.getByRole("region", { name: "Diblokir per run" });
    expect(within(runs).getByRole("row", { name: /#aaaaaa/ })).toHaveTextContent("40%");
  });

  it("says so when nothing was visited yet", async () => {
    mockApi({ ...DATA, visits: 0, blocked: 0, stores: 0, stores_blocked: 0, by_method: {}, runs: [], blocked_stores: [] });
    render(<Detection />);
    expect(await screen.findByText(/Belum ada toko yang dikunjungi/)).toBeInTheDocument();
  });
});
