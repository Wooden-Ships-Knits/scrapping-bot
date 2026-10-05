import { expect, test, type Page } from "@playwright/test";

// Each test uses its own links, so the "already tested" state never leaks between tests.

async function waitDone(page: Page) {
  await expect(page.getByText("Selesai", { exact: true })).toBeVisible({ timeout: 20_000 });
}

test("main scenario: paste, preview, test run, check the data, full run, download", async ({ page }) => {
  await page.goto("/");
  await page
    .getByRole("textbox", { name: "Tautan toko" })
    .fill("Cek monkees.com, https://boutique.com dan https://blocked.com. IG: https://instagram.com/x");

  await expect(page.getByTestId("link-count")).toHaveText("4 tautan · 3 toko");
  await expect(page.getByTestId("preview")).toContainText('"https://monkees.com"');
  await expect(page.getByTestId("preview")).toContainText("dilewati: Media sosial");
  await page.getByRole("button", { name: "START RUN UJI" }).click();

  await expect(page).toHaveURL(/#\/runs\//);
  await expect(page.getByRole("heading", { name: /Run uji: 2 toko pertama/ })).toBeVisible();
  await waitDone(page);
  await expect(page.getByTestId("reconciliation")).toContainText("Tautan masuk 4 = diproses 2 + dilewati 2 ✓ seimbang");

  const result = page.getByRole("region", { name: "Hasil" });
  await expect(result.getByRole("row", { name: /monkees\.com.*Ada produk/ })).toBeVisible();
  await expect(result.getByRole("row", { name: /boutique\.com.*Tanpa katalog/ })).toBeVisible();

  await result.getByRole("tab", { name: "PRODUCTS" }).click();
  await expect(result.getByRole("cell", { name: "Cher Sweater in Eggnog" })).toBeVisible();
  await result.getByRole("tab", { name: "RESPONSE" }).click();
  await expect(result.getByTestId("json-view")).toContainText('"price_raw": "139.00"');

  await result.getByRole("button", { name: "Unduh hasil" }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Excel (.xlsx)" }).click();
  expect((await download).suggestedFilename()).toBe("tables.xlsx");

  await page.getByRole("button", { name: /Jalankan seluruh daftar/ }).click();
  await expect(page.getByRole("heading", { name: /Run penuh/ })).toBeVisible();
  await waitDone(page);
  await expect(page.getByText("Toko dikunjungi: 3 dari 3")).toBeVisible();
  await expect(page.getByText("(HTTP 403)")).toBeVisible();

  await page.goto("/#/runs");
  await expect(page.getByRole("heading", { name: "Riwayat run" })).toBeVisible();
  await expect(page.getByRole("row", { name: /Penuh/ }).first()).toBeVisible();
});

test("an uploaded spreadsheet keeps its columns and runs", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("file-input").setInputFiles({
    name: "prospek.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("store_name,website\nKnit Shop,https://knitshop.com\nTanpa situs,\n"),
  });
  await expect(page.getByText("prospek.csv")).toBeVisible();
  await expect(page.getByTestId("link-count")).toHaveText("2 tautan · 1 toko");
  await expect(page.getByTestId("preview")).toContainText("Tanpa situs 1");

  await page.getByRole("button", { name: /START RUN/ }).click();
  await waitDone(page);
  await expect(page.getByText(/prospek\.csv · dimulai/)).toBeVisible();
  const result = page.getByRole("region", { name: "Hasil" });
  await result.getByRole("tab", { name: "INPUTS" }).click();
  await expect(result.getByRole("row", { name: /Tanpa situs/ })).toBeVisible();
});

test("a full run of an untested list needs a deliberate confirmation", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("textbox", { name: "Tautan toko" }).fill("https://knitshop.com https://boutique.com/new");
  await page.getByRole("button", { name: "Mode uji" }).click();
  await page.getByRole("checkbox", { name: "Jalankan beberapa toko pertama dulu" }).uncheck();
  await page.keyboard.press("Escape");

  const runAll = page.getByRole("button", { name: "START RUN", exact: true });
  await expect(page.getByText(/belum pernah diuji/)).toBeVisible();
  await expect(runAll).toBeDisabled();
  await page.getByRole("checkbox", { name: "Saya sengaja melewati mode uji" }).check();
  await expect(runAll).toBeEnabled();
  await runAll.click();
  await expect(page.getByRole("heading", { name: /Run penuh/ })).toBeVisible();
  await waitDone(page);
});

test("overview and theme switch", async ({ page }) => {
  await page.goto("/#/overview");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-theme", "dark");
  await page.getByRole("switch", { name: "Tema terang" }).click();
  await expect(html).toHaveAttribute("data-theme", "light");
});
