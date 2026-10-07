# 0002 — Camoufox for browser compatibility and rendering; no challenge bypass

**Date:** 2026-10-05
**Status:** Accepted
**Updated:** 2026-10-06

## Context

Some sites build their catalogue in JavaScript, so plain HTTP sees incomplete or
empty content. Some sites may also reject obvious headless-browser automation
even though the requested pages are public.

Botasaurus and Camoufox were considered for browser-based acquisition.
Camoufox was selected because it provides a realistic Firefox browser environment
with a Playwright-compatible API, while fitting the existing Fetcher architecture.

Recon on 67 domains found no meaningful prospect coverage lost to bot detection.
The only HTTP 403 responses came from three national chains (H&M, Macy's and
Four Seasons), which are not target prospects. Two other failures were TLS
handshake failures rather than bot detection.

The main problem is therefore catalogue coverage and JavaScript rendering, not
challenge bypass.

## Decision

- **Camoufox is the browser transport for pages that require rendering or normal
  browser compatibility.**

- Camoufox may use its normal browser behaviour, realistic fingerprint and
  persistent browser session to avoid false positives caused by obvious
  headless-browser automation.

- **Using a realistic browser fingerprint is considered browser compatibility,
  not challenge bypass.**

- Plain HTTP remains the preferred acquisition path. Camoufox is used when:
  - the page requires JavaScript;
  - the HTTP response does not contain enough usable content;
  - product data is loaded through browser-visible XHR/fetch requests; or
  - an otherwise public page fails specifically because of obvious headless
    browser characteristics.

- Only pages that require browser rendering are opened in Camoufox. The crawler
  keeps a per-store browser-page limit to prevent uncontrolled browser usage.

- Browser requests use the same domain-level request policy as HTTP:
  - request throttling;
  - bounded concurrency;
  - cache/reuse where applicable;
  - limited retry with exponential backoff;
  - public pages only.

- Camoufox may capture JSON/XHR responses loaded normally by the public page.
  When those responses expose structured product data, they are preferred over
  extracting the same information from rendered HTML.

- HTTP `429`, temporary `5xx`, network failures and timeouts may receive a small
  number of retries with backoff.

- A persistent `401` or `403`, CAPTCHA, explicit Cloudflare challenge, login
  requirement, or similar explicit access challenge is recorded as `blocked`.

- Explicit challenges are not solved automatically and the crawler does not
  rotate proxies or identities in order to evade a persistent block.

- When a browser path is blocked, the crawler may still use independent public
  acquisition paths that are available without the blocked page, such as:
  - public sitemaps;
  - public platform feeds;
  - documented or publicly accessible product APIs;
  - previously discovered public product URLs;
  - cached data.

- Browser locale defaults to `en-US`, but **currency is always detected and
  recorded from the actual source data** rather than inferred from locale alone.

## Acquisition behaviour

The expected order is:

```text
HTTP
 ↓
usable content?
 ├─ yes → structured extraction
 └─ no
      ↓
   Camoufox
      ↓
 rendered HTML + public XHR/JSON
      ↓
 usable content?
 ├─ yes → structured extraction
 └─ no
      ↓
 explicit challenge/block?
 ├─ yes → blocked
 └─ no  → extraction fallback / no_products
