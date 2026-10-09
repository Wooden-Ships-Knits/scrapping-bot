import { describe, expect, it } from "vitest";

import { parseRoute } from "./router";
import {
  blockMethod,
  blockState,
  knitKind,
  skipReason,
  sourceLabel,
  storeStatus,
  storeType,
  tone,
  trafficCityKind,
  trafficProblem,
  trafficSource,
} from "./labels";

describe("labels", () => {
  it("translates known codes and passes unknown ones through", () => {
    expect(storeStatus("no_products")).toBe("Tanpa katalog");
    expect(skipReason("over_limit")).toBe("Di luar batas jumlah toko");
    expect(storeStatus("something_new")).toBe("something_new");
    expect(sourceLabel("bigcartel_feed")).toBe("Feed Big Cartel");
    expect(sourceLabel("render")).toBe("Browser (Camoufox)");
    expect(blockMethod("http_403")).toBe("HTTP 403 (ditolak)");
    expect(blockState("recovered")).toBe("Pulih");
    expect(trafficCityKind("data_center")).toBe("Kota data center");
    expect(trafficSource("social")).toBe("Media sosial");
    expect(trafficProblem("quota_low")).toContain("Kuota");
    expect(storeType("multi_brand")).toBe("Multi-brand");
    expect(knitKind("accessory")).toBe("Aksesori rajut");
  });

  it("gives every store status a tone", () => {
    expect(tone("ok")).toBe("good");
    expect(tone("js_required")).toBe("warn");
    expect(tone("blocked")).toBe("bad");
    expect(tone("queued")).toBe("neutral");
  });
});

describe("parseRoute", () => {
  it("maps hashes to pages", () => {
    expect(parseRoute("")).toEqual({ page: "new" });
    expect(parseRoute("#/runs")).toEqual({ page: "history" });
    expect(parseRoute("#/detection")).toEqual({ page: "detection" });
    expect(parseRoute("#/traffic")).toEqual({ page: "traffic" });
    expect(parseRoute("#/runs/20261005T085253123Z-56162b")).toEqual({
      page: "run",
      runId: "20261005T085253123Z-56162b",
    });
    expect(parseRoute("#/nonsense")).toEqual({ page: "new" });
  });
});
