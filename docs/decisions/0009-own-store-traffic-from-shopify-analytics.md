# 0009 — Traffic on our own store from Shopify Analytics

**Date:** 2026-10-08
**Status:** Accepted

## Context

The team wanted to know who scrapes our own Shopify store (Wooden Ships), mainly
through `/products.json`. Shopify gives merchants no request logs, and `/products.json`
cannot be switched off. The only way to see every request is a proxy in front of the
store (Cloudflare "Orange-to-Orange"), which means moving the domain's DNS. The
operator ruled that out for now, because the same DNS carries the office email
(Google Workspace).

What Shopify does give is Analytics: sessions per minute, by city, landing page,
referrer and device, through ShopifyQL. A session is counted only when a page runs
Shopify's JavaScript, so bots that use a real browser show up, while plain HTTP
clients reading `/products.json` do not. In the 30 days to 2026-10-07 about 12,000 of
120,000 sessions came from cloud data-centre towns (Council Bluffs, Ashburn) with no
cart additions.

## Decision

- **A *Traffic toko* page in the web app** shows our store's sessions live: per
  minute for the last hour, totals, cities, landing pages, referrers and devices, for
  1 hour, 24 hours or 7 days. Sessions from known data-centre towns are marked as
  likely bots; that list is a guess and is labelled as one.
- **ShopifyQL through the Admin GraphQL API** (`shopifyqlQuery`), with our store's own
  app credentials: `SHOPIFY_STORE_DOMAIN` plus a Dev Dashboard client ID and secret
  (client-credentials token, renewed before its 24 hours run out), or a fixed Admin
  token. The app needs `read_reports`. Credentials are read from `.env` and masked in
  logs like every other key.
- **The server caches every answer.** Shopify meters ShopifyQL at about 1,000 cost
  points an hour per app. The minute chart costs 2 points and refreshes every 30
  seconds; the five tables cost about 46 points and refresh every 5 minutes. That is
  under 800 points an hour however many pages are open. Below 150 points left the
  tables keep their last answer, and below 20 the chart does too, until the window
  resets.
- **It is separate from the pipeline.** `traffic.py` reads nothing from runs and the
  pipeline never imports it. It is the one place the tool reads a store with
  credentials, and that store is ours.

## Rejected alternatives

- **Cloudflare in front of the store.** Sees and can block every request, including
  `/products.json`, on the free plan. Needs the DNS moved; rejected for now for the
  email risk. It stays the only way to see JSON-only scrapers.
- **A canary product or tracking pixel.** Catches catalogue copiers, not readers; may
  still be added later as its own panel.
- **Shopify Live View.** Real time, but no API and no per-city bot view.

## Consequences

- The page shows browser sessions only, and says so on the page. JSON-only scrapers
  stay invisible until a proxy is in front of the store.
- Sharing the Shopify app's ShopifyQL quota: anything else that queries Analytics with
  the same app eats into the same 1,000 points.
- Tests use a fake Shopify (`tests/fakes.FakeSearchApi`); no Analytics data is
  committed.
