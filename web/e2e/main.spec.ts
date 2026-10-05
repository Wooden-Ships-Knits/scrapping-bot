import { expect, test } from "@playwright/test";

// Each test uses its own links, so the "already tested" state never leaks between tests.

test("main scenario: paste, test run, check, full run, download", async ({ page }) => {
  await page.goto("/");
  await page
    .getByRole("textbox", { name: "Tautan toko" })
    .fill("Cek monkees.com, https://boutique.com dan https://blocked.com. IG: https://instagram.com/x");

  await expect(page.getByTestId("preview")).toContainText("Terdeteksi 4 tautan · 3 toko unik");
  await page.getByRole("button", { name: "Jalankan uji (2 toko)" }).click();

  await expect(page).toHaveURL(/#\/runs\//);
  await expect(page.getByRole("heading", { name: /Run uji: 2 toko pertama/ })).toBeVisible();
  await expect(page.getByText("Selesai")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("reconciliation")).toContainText(
    "Tautan masuk 4 = diproses 2 + dilewati 2 ✓ seimbang",
  );
  await expect(page.getByRole("row", { name: /monkees\.com.*Ada produk.*Feed Shopify/ })).toBeVisible();
  await expect(page.getByRole("row", { name: /boutique\.com.*Tanpa katalog/ })).toBeVisible();

  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Excel (.xlsx)" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe("tables.xlsx");
  expect((await file.createReadStream()).readable).toBe(true);

  await page.getByRole("button", { name: /Jalankan seluruh daftar/ }).click();
  await expect(page.getByRole("heading", { name: /Run penuh/ })).toBeVisible();
  await expect(page.getByText("Selesai")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Toko dikunjungi: 3 dari 3")).toBeVisible();
  await expect(page.getByRole("row", { name: /blocked\.com.*Diblokir/ })).toBeVisible();
  await expect(page.getByText("blocked.com: Diblokir (HTTP 403)")).toBeVisible();

  await page.getByRole("link", { name: "Riwayat" }).click();
  await expect(page.getByRole("heading", { name: "Riwayat run" })).toBeVisible();
  await expect(page.getByRole("row", { name: /Penuh/ }).first()).toBeVisible();
});

test("an uploaded spreadsheet keeps its columns and runs", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("tab", { name: "Unggah file" }).click();
  await page.getByTestId("file-input").setInputFiles({
    name: "prospek.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("store_name,website\nKnit Shop,https://knitshop.com\nTanpa situs,\n"),
  });
  await expect(page.getByText("prospek.csv terunggah.")).toBeVisible();
  await expect(page.getByTestId("preview")).toContainText("Terdeteksi 2 tautan · 1 toko unik");
  await expect(page.getByTestId("preview")).toContainText("Tanpa situs 1");

  await page.getByRole("button", { name: /Jalankan uji/ }).click();
  await expect(page.getByText("Selesai")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/prospek\.csv · dimulai/)).toBeVisible();
  await expect(page.getByRole("row", { name: /knitshop\.com.*Ada produk/ })).toBeVisible();
});

test("a full run of an untested list needs a deliberate confirmation", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("textbox", { name: "Tautan toko" }).fill("https://knitshop.com https://boutique.com/new");
  await page.getByRole("checkbox", { name: "Jalankan beberapa toko pertama dulu" }).uncheck();

  const runAll = page.getByRole("button", { name: "Jalankan semua" });
  await expect(page.getByText(/belum pernah diuji/)).toBeVisible();
  await expect(runAll).toBeDisabled();
  await page.getByRole("checkbox", { name: "Saya sengaja melewati mode uji" }).check();
  await expect(runAll).toBeEnabled();
  await runAll.click();
  await expect(page.getByRole("heading", { name: /Run penuh/ })).toBeVisible();
  await expect(page.getByText("Selesai")).toBeVisible({ timeout: 20_000 });
});
