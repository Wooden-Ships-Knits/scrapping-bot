import { expect, test, type Page } from "@playwright/test";

async function waitDone(page: Page) {
  await expect(page.getByText("Finished", { exact: true })).toBeVisible({ timeout: 20_000 });
}

test("main scenario: paste, preview, scrape, check the data, download", async ({ page }) => {
  await page.goto("/");
  await page
    .getByRole("textbox", { name: "Store links" })
    .fill("Cek monkees.com, https://boutique.com dan https://blocked.com. IG: https://instagram.com/x");

  await expect(page.getByTestId("link-count")).toHaveText("4 links · 3 stores");
  await expect(page.getByTestId("preview")).toContainText("https://monkees.com");
  await expect(page.getByTestId("preview")).toContainText("Skipped: Social media");
  await page.getByRole("button", { name: "Start scraping" }).click();

  await expect(page).toHaveURL(/#\/runs\//);
  await expect(page.getByRole("heading", { name: /Full run/ })).toBeVisible();
  await waitDone(page);
  await expect(page.getByText("Stores visited: 3 of 3")).toBeVisible();
  await expect(page.getByTestId("reconciliation")).toContainText("Links in 4 = processed 3 + skipped 1 ✓ balanced");
  await expect(page.getByRole("region", { name: "Needs a look" }).getByText("HTTP 403")).toBeVisible();

  const result = page.getByRole("region", { name: "Results" });
  await expect(result.getByRole("tab", { name: /Final: stores/ })).toHaveAttribute("aria-selected", "true");
  await result.getByRole("tab", { name: /^Stores/ }).click();
  await expect(result.getByRole("row", { name: /monkees\.com.*Has products/ })).toBeVisible();
  await expect(result.getByRole("row", { name: /boutique\.com.*No catalogue/ })).toBeVisible();

  await result.getByRole("tab", { name: /^Products/ }).click();
  await expect(result.getByRole("cell", { name: "Cher Sweater in Eggnog" })).toBeVisible();
  await result.getByRole("tab", { name: "JSON" }).click();
  await expect(result.getByTestId("json-view")).toContainText('"price_raw": "139.00"');

  const download = page.waitForEvent("download");
  await page.getByRole("region", { name: "Download results" }).getByRole("link", { name: "Download Excel (.xlsx)" }).click();
  expect((await download).suggestedFilename()).toBe("tables.xlsx");

  await page.goto("/#/runs");
  await expect(page.getByRole("heading", { name: "Run history" })).toBeVisible();
  await expect(page.getByRole("row", { name: /Full/ }).first()).toBeVisible();

  await page.goto("/#/detection");
  await expect(page.getByRole("heading", { name: "Detection" })).toBeVisible();
  const blockedRow = page.getByRole("region", { name: "Stores that block" }).getByRole("row", { name: /blocked\.com/ });
  await expect(blockedRow).toContainText("Always");
  await expect(blockedRow).toContainText("HTTP 403 (refused)");
});

test("an uploaded spreadsheet keeps its columns and runs", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("file-input").setInputFiles({
    name: "prospects.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("store_name,website\nKnit Shop,https://knitshop.com\nNo Site Shop,\n"),
  });
  await expect(page.getByText("prospects.csv", { exact: true })).toBeVisible();
  await expect(page.getByTestId("link-count")).toHaveText("2 links · 1 store");
  await expect(page.getByTestId("preview")).toContainText("No website 1");

  await page.getByRole("button", { name: "Start scraping" }).click();
  await waitDone(page);
  await expect(page.getByText(/prospects\.csv · started/)).toBeVisible();
  const result = page.getByRole("region", { name: "Results" });
  await result.getByRole("tab", { name: /^Inputs/ }).click();
  await expect(result.getByRole("row", { name: /No Site Shop/ })).toBeVisible();
});

test("overview and theme switch", async ({ page }) => {
  await page.goto("/#/overview");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-theme", "light");
  await page.getByRole("switch", { name: "Dark theme" }).click();
  await expect(html).toHaveAttribute("data-theme", "dark");
});
