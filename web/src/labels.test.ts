import { describe, expect, it } from "vitest";

import { parseRoute } from "./router";
import { skipReason, storeStatus, tone } from "./labels";

describe("labels", () => {
  it("translates known codes and passes unknown ones through", () => {
    expect(storeStatus("no_products")).toBe("Tanpa katalog");
    expect(skipReason("over_limit")).toBe("Di luar mode uji");
    expect(storeStatus("something_new")).toBe("something_new");
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
    expect(parseRoute("#/runs/20261005T085253123Z-56162b")).toEqual({
      page: "run",
      runId: "20261005T085253123Z-56162b",
    });
    expect(parseRoute("#/nonsense")).toEqual({ page: "new" });
  });
});
