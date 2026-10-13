# 0013 — A store read recently is loaded, not visited again

**Date:** 2026-10-13
**Status:** Accepted

## Context

Every run visited every store in its input, whether or not an earlier run had just read
it. The page cache made the second visit fast for a week, but the store was still
processed again, the LLM stage was paid again for the same text, and nothing told the
operator that the data was already there. Lists overlap: a discovery in the same region
returns many of the stores the last one did.

[ADR 0003](0003-plain-python-orchestration-file-output.md) kept output as files and said
to revisit once history across runs was needed, starting with SQLite.

## Decision

- **A ledger of visits.** `data/runs/ledger.sqlite` holds one row per store per run:
  domain, run, when it was read, status, product count (`ledger.py`). It is derived from
  the run folders: deleting it rebuilds it from every `stores` table on disk.
- **Reuse within a window.** A store whose newest visit in the last `fetch.reuse_days`
  days (default 30) ended `ok` or `no_products` is not visited. Its products, pages and
  contacts are loaded from that run's tables and written under the new run's id, so the
  run is complete on its own: exports, final list, summary and report need no special
  case. `stores.reused_from` names the run the rows came from and `fetched_at` stays the
  day the store was really read. Focus items are matched again with the new run's
  settings. A store that was blocked, rate-limited or failed is always visited.
- **A search is for new stores (added 2026-10-13).** Asking a search for 100 stores
  means 100 stores no run has an answer about yet. Stores visited in the window (read,
  blocked, or needing a browser; not an error or a rate limit, which say nothing) are
  left out of the visit list and do not count toward the number asked for; the agent
  is given their websites and asked for others, and may ask half as often again. They
  stay in `stores.csv`, and the search says how many it left out. Ticking "Include
  stores already scraped" counts them and scrapes them again. Loading applies to a run
  on links the operator supplies, where the list is the operator's choice.
- **The newest visit decides, and an unfinished one does not count (added 2026-10-13).**
  What is known about a store is its newest visit in the window: a store that was read
  and later blocked or failed is visited again. A visit is *unfinished* when it left a
  question the LLM stage answers (no catalogue found, or a store type nothing decided)
  and that stage did not work for it: switched off, no key, or every call failed. Such
  a store is loaded, and left out of a search, only by a run whose LLM stage cannot work
  either; a run that has one reads it again. On 2026-10-12 six runs read 251 stores with
  a rejected key and left 185 of them open; they had counted as done.
- **A store is visited when the input asks for its product or page links**, which the
  earlier run may not have read.
- **The ledger knows whether it was built.** Its schema version is written after the
  build, so one whose first build was cut short, or of an older version, is built again.
  A broken last line in a run's table is passed over.
- **The operator is told and can refuse.** The preview says how many stores were read
  before and when; the run page and the report say how many were loaded. "Scrape them
  again anyway" in the interface, `--rescrape` on the command line and
  `fetch.reuse_days: 0` visit everything.
- **The same text is never paid for twice.** The LLM stage keeps each answer in
  `data/.cache/llm`, keyed on a hash of the model, the prompt version and the exact
  messages. When a store is visited again and its text has not changed, the answer is
  read back: no call, no tokens (`llm_calls.cached`). The hash can only be known after
  the page is fetched, so it saves the model call, not the visit; the ledger saves the
  visit.

## Rejected alternatives

- **Skip the store and write nothing.** The run would then lack stores it was asked
  for, and every reader of a run (final list, analysis, map) would need to join other
  runs.
- **Scan every run folder each time instead of a ledger.** Correct, but the preview asks
  on every keystroke pause and the scan grows with every run.
- **Decide reuse by a hash of the homepage.** It needs the visit it is meant to avoid.
- **Postgres.** Still one operator and one machine (ADR 0003).

## Consequences

- A loaded store costs no request and no LLM call, and is not counted as a visit on the
  Detection page.
- Data can be up to `reuse_days` old without the operator asking for it; `fetched_at`
  and `reused_from` say so on every row, and the notices say so before and after.
- The summary row of a loaded store is the earlier run's: it was computed from page HTML,
  which is never stored (ADR 0006).
- Model calls of a loaded store are not copied: `llm_used` is false and the cost stays
  with the run that paid for it.
- Deleting a run folder removes its stores from reuse and from what a search leaves out;
  the next run visits them.
- A search for new stores asks the agent afresh each time: the websites it is told to
  avoid are part of the question, so its cached answers, which name stores already read,
  are not reused. Repeating such a search is paid for again.
