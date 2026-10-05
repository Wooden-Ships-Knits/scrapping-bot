# 0002 — Camoufox for rendering only; no anti-bot bypass

**Date:** 2026-10-05
**Status:** Proposed

## Context

Some sites build their catalogue in JavaScript, so plain HTTP sees an empty
page. Botasaurus and Camoufox were proposed so the bot would not be detected
as a bot.

Recon on 67 domains found no real prospect lost to bot detection. The only 403
responses came from three national chains (H&M, Macy's, Four Seasons), which
are not prospects. The two other failures were broken TLS certificates.

## Decision

- **Camoufox is the browser for layer 4.** Its Playwright-compatible API makes
  network interception (capturing the product JSON a page loads) easy. Its
  realistic fingerprint stops a plain headless-browser flag from blocking
  normal page loads.
- **Every browser request goes through the existing `Fetcher` robots check and
  per-domain delay.**
- **Challenge pages (Cloudflare, CAPTCHA) and 401/403/429 responses are
  recorded as `blocked`.** They are not bypassed. No proxy rotation is used.
- **Browser locale is fixed to `en-US`, and price currency is always
  recorded.**

## Rejected alternatives

- **Botasaurus.** Its `@request` duplicates `Fetcher` (cache, retry, throttle),
  and its `@browser` overlaps with Camoufox. Running two browser stacks adds
  maintenance cost and no coverage.
- **Playwright-Chromium (ScrapeGraph's default loader).** Headless Chromium is
  easy to flag. Camoufox runs on Playwright with the same API.
- **Bypassing challenges.** A challenge or 403 is the owner explicitly refusing
  automated access. The v1 spec commits to "bypasses no access control".
  The stores are future wholesale partners, so the reputational risk is not
  worth it. The data also shows the need is close to zero.

## Consequences

- Sites that block us stay visible in the run report as `blocked`.
- If a future city list shows many blocked boutiques (not chains), revisit this
  decision. Check the request rate and the IP type (datacenter or residential)
  first, before looking at fingerprinting.
