# 0002 — Camoufox for rendering only; no anti-bot bypass

**Date:** 2026-10-05
**Status:** Accepted

## Context

Some sites build their catalogue in JavaScript, so plain HTTP sees an empty
page. Botasaurus and Camoufox were proposed so the bot would not be detected as
a bot. Removing the "no anti-bot bypass" rule was also discussed.

Recon on 67 domains found no real prospect lost to bot detection. The only 403
responses came from three national chains (H&M, Macy's, Four Seasons), which are
not prospects. The two other failures were broken TLS certificates.

## Decision

- **Camoufox is the browser for the render stage.** Its Playwright-compatible
  API makes network interception (capturing the product JSON a page loads) easy.
  Its realistic fingerprint stops a plain headless-browser flag from blocking
  normal page loads.
- **Only pages that fail the content check are rendered**, at most 10 per store.
- **Every browser request goes through the same `robots.txt` check and
  per-domain delay as HTTP.**
- **Challenge pages (Cloudflare, CAPTCHA) and 401/403/429 responses are recorded
  as `blocked`.** They are not bypassed. No proxy rotation is used.
- **Browser locale is fixed to `en-US`, and price currency is always recorded.**

## Rejected alternatives

- **Bypassing challenges** (CAPTCHA solvers, challenge solving, rotating
  proxies, ignoring `robots.txt`). A challenge, a 403 or a `robots.txt` rule is
  the owner explicitly refusing automated access. The stores are future
  wholesale partners, so the reputational and legal risk is not worth it.
  Bypasses also need constant upkeep and paid solvers or proxies. The data shows
  the need is close to zero.
- **Botasaurus.** Its `@request` duplicates `Fetcher` (cache, retry, throttle),
  and its `@browser` overlaps with Camoufox. Two browser stacks add maintenance
  cost and no coverage.
- **Playwright-Chromium.** Headless Chromium is easy to flag. Camoufox runs on
  Playwright with the same API.

## Consequences

- Sites that block us stay visible in the run report as `blocked`.
- If a future city list shows many blocked boutiques (not chains), revisit this
  decision. Check the request rate and the IP type (datacenter or residential)
  first, before looking at fingerprinting.
