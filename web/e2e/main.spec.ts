import { expect, test, type Page } from "@playwright/test";

async function waitDone(page: Page) {
  await expect(page.getByText("Selesai", { exact: true })).toBeVisible({ timeout: 20_000 });
}

test("main scenario: paste, preview, scrape, check the data, download", async ({ page }) => {
  await page.goto("/");
  await page
    .getByRole("textbox", { name: "Tautan toko" })
    .fill("Cek monkees.com, https://boutique.com dan https://blocked.com. IG: https://instagram.com/x");

  await expect(page.getByTestId("link-count")).toHaveText("4 tautan · 3 toko");
  await expect(page.getByTestId("preview")).toContainText("https://monkees.com");
  await expect(page.getByTestId("preview")).toContainText("Dilewati: Media sosial");
  await page.getByRole("button", { name: "Mulai scrape" }).click();

  await expect(page).toHaveURL(/#\/runs\//);
  await expect(page.getByRole("heading", { name: /Run penuh/ })).toBeVisible();
  await waitDone(page);
  await expect(page.getByText("Toko dikunjungi: 3 dari 3")).toBeVisible();
  await expect(page.getByTestId("reconciliation")).toContainText("Tautan masuk 4 = diproses 3 + dilewati 1 ✓ seimbang");
  await expect(page.getByRole("region", { name: "Perlu dilihat" }).getByText("HTTP 403")).toBeVisible();

  const result = page.getByRole("region", { name: "Hasil" });
  await expect(result.getByRole("row", { name: /monkees\.com.*Ada produk/ })).toBeVisible();
  await expect(result.getByRole("row", { name: /boutique\.com.*Tanpa katalog/ })).toBeVisible();

  await result.getByRole("tab", { name: /Produk/ }).click();
  await expect(result.getByRole("cell", { name: "Cher Sweater in Eggnog" })).toBeVisible();
  await result.getByRole("tab", { name: "JSON" }).click();
  await expect(result.getByTestId("json-view")).toContainText('"price_raw": "139.00"');

  const download = page.waitForEvent("download");
  await page.getByRole("region", { name: "Unduh hasil" }).getByRole("link", { name: "Unduh Excel (.xlsx)" }).click();
  expect((await download).suggestedFilename()).toBe("tables.xlsx");

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
  await expect(page.getByText("prospek.csv", { exact: true })).toBeVisible();
  await expect(page.getByTestId("link-count")).toHaveText("2 tautan · 1 toko");
  await expect(page.getByTestId("preview")).toContainText("Tanpa situs 1");

  await page.getByRole("button", { name: "Mulai scrape" }).click();
  await waitDone(page);
  await expect(page.getByText(/prospek\.csv · dimulai/)).toBeVisible();
  const result = page.getByRole("region", { name: "Hasil" });
  await result.getByRole("tab", { name: /Masukan/ }).click();
  await expect(result.getByRole("row", { name: /Tanpa situs/ })).toBeVisible();
});

test("overview and theme switch", async ({ page }) => {
  await page.goto("/#/overview");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-theme", "light");
  await page.getByRole("switch", { name: "Tema gelap" }).click();
  await expect(html).toHaveAttribute("data-theme", "dark");
});
