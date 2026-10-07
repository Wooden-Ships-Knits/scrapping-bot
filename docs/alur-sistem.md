# Alur Sistem Scrapebot

Panduan belajar: bagaimana satu daftar link toko berubah menjadi tabel data, tahap
demi tahap, dan alat apa yang dipakai di setiap tahap. Untuk detail teknis lengkap,
lihat [architecture/overview.md](architecture/overview.md). Untuk alasan di balik
setiap keputusan, lihat [decisions/](decisions/).

> Dokumen ini mengikuti kode di branch `fix/eu-prices-and-page-kinds` (7 Okt 2026):
> harga hanya diekspor sebagai `price_raw`, tanpa konversi.

---

## 1. Gambaran besar

```
Daftar link  ──►  Baca & rapikan  ──►  Kunjungi tiap toko  ──►  Tabel mentah  ──►  Ekspor + laporan
(format apa saja)   (inputs/)          (acquire/, 7 tahap)      (JSONL per run)    (xlsx, csv, ...)
```

Prinsip yang perlu diingat sepanjang alur:

1. **Sumber termurah dan paling pasti dulu.** Feed platform → data terstruktur →
   browser → LLM. LLM selalu terakhir karena mahal dan bisa salah.
2. **Setiap link tercatat.** Link masuk = diproses + dilewati. Tidak ada yang hilang diam-diam.
3. **Mentah tetap mentah.** Nilai disimpan persis seperti ditemukan (harga `€ 63,95` tetap
   `€ 63,95`), lengkap dengan sumber dan URL bukti. Konversi dikerjakan sistem berikutnya.
4. **Tidak menembus proteksi.** Patuh `robots.txt`, ada jeda per domain, tanpa login dan
   tanpa memecahkan CAPTCHA. Situs yang menolak dicatat `blocked`.
5. **Test tidak pernah menyentuh jaringan.** Semua test memakai respons rekaman.

---

## 2. Dua pintu masuk, satu mesin

| Pintu | Perintah | Untuk siapa |
|---|---|---|
| **Web** | `make serve` → http://127.0.0.1:8765 | Operator: tempel link, pratinjau, mode tes, unduh hasil |
| **CLI** | `uv run scrapebot run <input> --limit 2` | Developer, otomasi (n8n, cron) |

Keduanya membangun objek yang sama, `RunConfig` ([config.py](../src/scrapebot/config.py)),
lalu memanggil pipeline yang sama ([pipeline.py](../src/scrapebot/pipeline.py)). Pipeline
tidak pernah mengimpor kode API atau UI.

```
Browser (React)  ──HTTP──►  FastAPI (api/app.py)  ──┐
                                                    ├──►  RunConfig  ──►  pipeline.prepare()  ──►  pipeline.execute()
Terminal (cli.py)  ─────────────────────────────────┘
```

- `prepare`: membaca input, membuat folder run `data/runs/<run_id>/`, dan menulis `config.json`
  serta tabel `inputs`.
- `execute`: mengunjungi toko, menulis tabel, mengekspor, dan menulis `report.md` paling
  akhir. Adanya `report.md` menandakan run selesai.

---

## 3. Alur langkah demi langkah

### Langkah 1. Membaca input ([inputs/](../src/scrapebot/inputs/))

| Yang terjadi | Alat |
|---|---|
| Membaca teks tempel, `.txt`, `.csv`, `.tsv`, `.xlsx`, `.json`, `.jsonl`, `.parquet` | `openpyxl`, `pyarrow`, standard library |
| Menemukan URL di teks bebas | `urlextract` |
| Mengelompokkan per domain (`a.myshopify.com` ≠ `b.myshopify.com`) | `tldextract` (Public Suffix List bawaan, tanpa jaringan) |
| Menandai link yang dilewati: `duplicate`, `invalid_url`, `social_only`, `marketplace`, `no_website`, `over_limit` | [resolve.py](../src/scrapebot/inputs/resolve.py) |

Contoh: `shopee.co.id/...` dilewati sebagai `marketplace`, dan dua link ke toko yang sama
digabung menjadi satu (`duplicate`). Link dalam seperti `/shop/womens/knitwear` tetap
diingat dan nanti diambil sebagai halaman prioritas.

### Langkah 2. Mengunjungi toko secara paralel ([pipeline.py](../src/scrapebot/pipeline.py))

Beberapa toko diproses bersamaan (`fetch.concurrency`, bawaannya 6), tapi setiap server
tetap hanya menerima satu permintaan dalam satu waktu, dengan jeda 1,5 detik.

Semua akses jaringan lewat satu pintu: `HttpFetcher` di [fetch.py](../src/scrapebot/fetch.py).

| Tugas fetcher | Alat |
|---|---|
| Permintaan HTTP | `requests` |
| Patuh `robots.txt` | `urllib.robotparser` (standard library) |
| Cache respons sukses di `data/.cache/` (run ulang jadi cepat; yang gagal dicoba lagi) | file JSON per URL |
| Deteksi halaman tantangan: Cloudflare, DataDome, PerimeterX, Incapsula, Sucuri, Akamai | `CHALLENGE_MARKERS` |
| Tanpa header `Accept-Language` | supaya Shopify tidak menerjemahkan harga ke mata uang lokal |

### Langkah 3. Tujuh tahap akuisisi per toko ([acquire/\_\_init\_\_.py](../src/scrapebot/acquire/__init__.py))

Ini inti sistem. Satu toko melewati tahap-tahap berikut, berhenti mencari produk begitu
satu tahap berhasil. Setiap tahap yang dicoba dicatat di kolom `layers_tried`.

```
 1. Beranda ──── gagal/diblokir? ──► status error / blocked (selesai)
      │
      ▼  deteksi platform + mata uang
 2. Feed platform ──── ada produk? ──► lewati tahap 4
      │
 3. Halaman prioritas (kontak, about, grosir, stockist, link dari input) ← SELALU diambil
      │
 4. Discovery: sitemap, atau link internal sampai 2 tingkat (maks. 25 halaman)
      │
 5. Data terstruktur di setiap halaman
      │
      ▼  masih 0 produk?
 6. Browser (Camoufox) ──── render halaman yang butuh JavaScript
      │
      ▼  masih 0 produk?
 7. LLM ──── baca teks halaman, hanya simpan produk yang lolos aturan bukti
      │
      ▼
   ok (≥1 produk)  atau  no_products
```

**Tahap 1: Beranda.** Ambil halaman depan. Kalau dijawab 401/403/429 atau halaman
tantangan, toko dicatat `blocked` dan selesai. Kalau tidak, deteksi platform dan mata
uang dari penanda di HTML ([extract/profile.py](../src/scrapebot/extract/profile.py)).
Mata uang hanya diambil dari sumber yang tegas (`Shopify.currency.active`,
`og:price:currency`, JSON-LD `priceCurrency`), tidak pernah dari simbol "$" saja.

**Tahap 2: Feed platform** ([acquire/feeds.py](../src/scrapebot/acquire/feeds.py),
[extract/feeds.py](../src/scrapebot/extract/feeds.py)). Banyak platform punya endpoint
yang langsung memberi daftar produk:

| Platform | Endpoint |
|---|---|
| Shopify | `/products.json` (250 per halaman, maks. 20 halaman) |
| Big Cartel | `/products.json` |
| WooCommerce | `/wp-json/wc/store/v1/products` (harga dalam satuan terkecil, mis. `22900`) |
| Squarespace | `?format=json` |
| Lightspeed | `/collection/?format=json` |
| Magento 2 | `/graphql` |

**Tahap 3: Halaman prioritas.** Kontak, about, grosir, dan stockist selalu diambil,
ada feed atau tidak, supaya kontak tidak pernah terlewat.

**Tahap 4: Discovery** ([acquire/discovery.py](../src/scrapebot/acquire/discovery.py)).
Mencari halaman produk dan koleksi lewat `sitemap.xml`, atau mengikuti link internal.
Setiap URL diberi peran (`priority`, `product`, `collection`, `other`, `skip`) dari
pola path-nya, misalnya `/collections/`, `/shop/`, `/women/` atau `/knitwear/`. Pola yang
sama dipakai `page_kind` di [extract/pages.py](../src/scrapebot/extract/pages.py) untuk
memberi jenis halaman yang tersimpan.

**Tahap 5: Data terstruktur** ([extract/structured.py](../src/scrapebot/extract/structured.py),
[extract/json_products.py](../src/scrapebot/extract/json_products.py)).

| Format | Alat |
|---|---|
| JSON-LD, Microdata, RDFa `Product` | `extruct` |
| OpenGraph (`og:price:amount`) | `extruct` |
| State aplikasi (`__NEXT_DATA__`, Wix `wix-warmup-data`, `window.__INITIAL_STATE__`) | `chompjs`, `json` |
| Kartu produk BigCommerce | `beautifulsoup4` + `lxml` |

**Tahap 6: Browser** ([render.py](../src/scrapebot/render.py)). Hanya untuk toko yang
masih 0 produk. Camoufox (Firefox yang dikendalikan lewat Playwright) merender halaman
yang isinya baru muncul lewat JavaScript, lalu menangkap JSON yang dimuat halaman
(XHR/fetch). Aturannya sama dengan HTTP: patuh `robots.txt`, ada jeda, dan gambar, media
serta font tidak dimuat. Camoufox **tidak** dipakai untuk menembus tantangan.

**Tahap 7: LLM** ([llm/](../src/scrapebot/llm/)). Hanya untuk toko yang masih 0
produk, dan hanya kalau LLM dinyalakan (`--llm openai/gpt-4o-mini`, atau
`serve -c data/llm.yaml`). Rinciannya ada di [bagian 4](#4-tahap-llm-lebih-dekat).

### Langkah 4. Kontak ([extract/contacts.py](../src/scrapebot/extract/contacts.py))

Dari setiap halaman yang terbaca:
- Email diambil dari link `mailto:` dan teks.
- Telepon diambil dari link `tel:`, dan dari nomor yang tertulis di teks yang terlihat
  (bukan dari markup, karena angka di path SVG bisa terlihat seperti nomor telepon).
- Instagram, Facebook, TikTok, LinkedIn dan Pinterest diambil dari link profil.

Setiap kontak menyimpan `source_url`, yaitu halaman tempat ia ditemukan.

### Langkah 5. Tabel mentah ([tables.py](../src/scrapebot/tables.py), [store.py](../src/scrapebot/store.py))

Setelah satu toko selesai, barisnya langsung ditambahkan ke file JSONL per tabel di
`data/runs/<run_id>/tables/`. Kalau run terputus, toko yang sudah selesai tidak hilang.

| Tabel | Satu baris = | Kolom penting |
|---|---|---|
| `runs` | satu run | config, versi, mode |
| `inputs` | satu link input | link asli, status atau alasan dilewati, baris input utuh |
| `stores` | satu toko | `status`, `platform`, `currency`, `source_used`, `layers_tried`, `llm_used` |
| `products` | satu produk | `title`, `price_raw`, `currency`, `vendor`, `url`, `source`, `evidence_url`, `needs_review`, `raw` |
| `pages` | satu halaman | `page_kind`, `http_status`, `via` (http/browser), `text` (tanpa HTML) |
| `contacts` | satu kontak | `type`, `value`, `source_url` |
| `llm_calls` | satu panggilan LLM | model, versi prompt, token, biaya |
| `changes` | perubahan antarrun | belum diisi (direncanakan di M5) |

Semua tabel bisa digabung lewat `run_id` dan `domain`. HTML tidak pernah disimpan;
yang disimpan hanya teks halamannya (ADR 0006).

### Langkah 6. Ekspor dan laporan ([outputs/](../src/scrapebot/outputs/), [report.py](../src/scrapebot/report.py))

| Format | Alat |
|---|---|
| JSON, JSONL, CSV, TSV | standard library |
| Excel | `openpyxl` (satu sheet per tabel) |
| Parquet | `pyarrow` |
| SQLite, DuckDB | `sqlite3`, `duckdb` |

Isi folder run:

```
data/runs/20261007T012357237Z-1eb499/
├── config.json      ← pengaturan run (tanpa API key)
├── tables/*.jsonl   ← tabel mentah (sumber kebenaran)
├── export/          ← file yang kamu pilih: xlsx, csv, ...
├── summary.csv      ← satu baris per link: knit_share, contoh produk, kontak
├── manifest.json    ← versi paket, durasi, jumlah baris
└── report.md        ← ringkasan: status toko, sumber produk, bagian LLM (biaya, token)
```

---

## 4. Tahap LLM lebih dekat

Ini tahap yang paling banyak dibahas hari ini, jadi alurnya ditulis lengkap:

```
Halaman yang sudah terbaca
   │  urutkan: collection → product → home → other   (maks. 6 halaman)
   ▼
condensed_text()  ── per halaman maks. 6.000 karakter
   │  trafilatura (konten utama) kalau harga ikut terbawa,
   │  kalau tidak: potongan teks yang paling banyak harganya
   ▼
Prompt extract_v3.md  ── "salin judul & harga persis, jangan terjemahkan"
   ▼
LiteLLM ── kirim ke penyedia (OpenAI, Gemini, Anthropic, Ollama, ...)
   │  gagal sementara? coba lagi 3 dtk & 10 dtk, lalu model cadangan
   │  budget habis? berhenti memanggil
   ▼
instructor + Pydantic ── paksa jawaban berbentuk StoreExtraction (llm/schemas.py)
   ▼
Aturan bukti (llm/evidence.py) ── produk DIBUANG kecuali:
   │   • source_url salah satu halaman yang dikirim
   │   • judulnya ada di teks halaman itu
   │   • harganya ada di halaman itu (dibandingkan sebagai angka: 41.95 = € 41,95)
   ▼
Produk lolos → source = "llm", needs_review = true
```

| Bagian | Alat | File |
|---|---|---|
| Satu antarmuka untuk semua penyedia | `litellm` | [gateway.py](../src/scrapebot/llm/gateway.py) |
| Keluaran terstruktur dan tervalidasi | `instructor` + `pydantic` | [schemas.py](../src/scrapebot/llm/schemas.py) |
| Mengambil konten utama halaman | `trafilatura` | [gateway.py](../src/scrapebot/llm/gateway.py) |
| Membaca API key dari `.env` | `python-dotenv` | [keys.py](../src/scrapebot/keys.py) |
| Menyamarkan key di log | `RedactingFilter` | [keys.py](../src/scrapebot/keys.py) |

**Contoh nyata (knitfactory.com, 7 Okt 2026).** Awalnya LLM tidak menemukan apa pun. Ada
tiga penyebab berantai:
1. Halaman kategori tidak dikenali sebagai `collection`, jadi yang dikirim malah halaman
   customer service.
2. trafilatura membuang grid produknya.
3. Harga `€ 41,95` terbaca 4195.

Setelah ketiganya diperbaiki, hasilnya 21–25 produk. Pelajarannya: kalau LLM "tidak
menemukan apa-apa", periksa dulu **apa yang dikirim** ke LLM, baru curigai modelnya.

---

## 5. Status akhir toko

| Status | Arti |
|---|---|
| `ok` | Minimal satu produk ditemukan |
| `no_products` | Situs terbaca, tapi tidak ada tahap yang menemukan katalog |
| `js_required` | Butuh JavaScript, dan browser tidak tersedia atau gagal |
| `blocked` | 401/403/429 atau halaman tantangan; tidak ditembus |
| `error` | Gagal jaringan, HTTP error lain, atau dilarang `robots.txt` |

Kolom yang membantu membaca hasil:
- `source_used`: tahap yang menemukan produk.
- `layers_tried`: semua tahap yang dicoba.
- `failed_page_count`: jumlah halaman yang gagal. Contohnya next.co.uk: 23 dari 27
  halaman dibalas 403.

---

## 6. Peta alat (ringkas)

**Bot (Python 3.11+, dikelola `uv`)**

| Alat | Untuk apa |
|---|---|
| `pydantic` | Model data: config, produk, baris tabel |
| `pyyaml` | Membaca file config `.yaml` |
| `requests` | HTTP |
| `beautifulsoup4`, `lxml` | Parsing HTML, link, teks halaman |
| `extruct` | JSON-LD, Microdata, RDFa, OpenGraph |
| `chompjs` | Membaca objek JavaScript di halaman |
| `urlextract`, `tldextract` | Menemukan URL dan domain di input |
| `camoufox` | Browser untuk halaman yang butuh JavaScript |
| `openpyxl`, `pyarrow`, `duckdb` | Ekspor Excel, Parquet, DuckDB |
| `litellm`, `instructor`, `trafilatura`, `python-dotenv` | Tahap LLM (extra `llm`) |
| `fastapi`, `uvicorn`, `python-multipart` | API lokal untuk web (extra `ui`) |

**Web (`web/`, dikelola `pnpm`)**

| Alat | Untuk apa |
|---|---|
| React + TypeScript | Antarmuka |
| Vite | Server dev dan build |
| `openapi-typescript` | Tipe TypeScript dibuat otomatis dari API (`make api-types`) |
| `lucide-react` | Ikon |
| Vitest + Testing Library | Unit test UI |
| Playwright | Test end-to-end, offline, desktop dan mobile (`make e2e`) |

**Kualitas kode**

| Alat | Untuk apa |
|---|---|
| `pytest` | Test Python (offline; HTTP dari fixture rekaman) |
| `ruff` | Lint dan format |
| `pyright` | Cek tipe |
| `pre-commit` | Menjalankan semua cek sebelum commit |
| `make check` | Semua cek di atas sekaligus; harus lulus sebelum commit |

---

## 7. Cara belajar sambil praktik

1. **Jalankan run kecil dan baca hasilnya:**
   ```bash
   uv run scrapebot run data/llm-test.txt --limit 2
   ```
   Buka `report.md` di folder run, lalu `tables/stores.jsonl`. Lihat `layers_tried` untuk
   setiap toko.
2. **Ikuti satu toko di kode.** Mulai dari fungsi `acquire()` di
   [acquire/\_\_init\_\_.py](../src/scrapebot/acquire/__init__.py). Docstring di bagian
   atas file adalah urutan tahapnya.
3. **Nyalakan LLM dan bandingkan:**
   ```bash
   uv run scrapebot run data/llm-test.txt --llm openai/gpt-4o-mini --llm-budget 0.2
   ```
   Toko yang tadinya `no_products` sekarang mungkin `ok` dengan `source_used = llm`.
   Lihat `llm_calls.jsonl` untuk biayanya.
4. **Baca test-nya.** Test di [tests/unit/](../tests/unit/) adalah contoh pemakaian
   setiap modul yang paling ringkas. Contohnya `test_llm.py` untuk aturan bukti dan
   `test_acquire.py` untuk urutan tahap.
5. **Baca keputusannya.** [decisions/0001](decisions/0001-layered-acquisition-llm-last.md)
   (kenapa LLM terakhir) dan [0002](decisions/0002-camoufox-for-rendering-only.md)
   (kenapa browser tidak menembus proteksi).
