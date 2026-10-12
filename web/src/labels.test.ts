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
    expect(storeStatus("no_products")).toBe("No catalogue");
    expect(skipReason("over_limit")).toBe("Over the store limit");
    expect(storeStatus("something_new")).toBe("something_new");
    expect(sourceLabel("bigcartel_feed")).toBe("Big Cartel feed");
    expect(sourceLabel("render")).toBe("Browser (Camoufox)");
    expect(blockMethod("http_403")).toBe("HTTP 403 (refused)");
    expect(blockState("recovered")).toBe("Recovered");
    expect(trafficCityKind("data_center")).toBe("Data center city");
    expect(trafficSource("social")).toBe("Social media");
    expect(trafficProblem("quota_low")).toContain("quota");
    expect(storeType("multi_brand")).toBe("Multi-brand");
    expect(knitKind("accessory")).toBe("Knitted accessory");
    expect(storeStatus("rate_limited")).toBe("Rate limited");
    expect(tone("rate_limited")).toBe("warn");
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
    expect(parseRoute("#/retailer-map")).toEqual({ page: "retailer" });
    expect(parseRoute("#/runs/20261005T085253123Z-56162b")).toEqual({
      page: "run",
      runId: "20261005T085253123Z-56162b",
    });
    expect(parseRoute("#/nonsense")).toEqual({ page: "new" });
  });
});
