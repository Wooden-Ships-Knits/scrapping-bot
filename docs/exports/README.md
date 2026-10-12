# Exports

PDF snapshots for reading offline, in Indonesian unless the file name ends in `-en`
(English). **The Markdown documents are the
source of truth.** Where a PDF and the Markdown disagree, the Markdown wins.

| File | Date | Differs from current docs in |
|---|---|---|
| [rancangan-scrapebot-v2.pdf](rancangan-scrapebot-v2.pdf) | 2026-10-05 | Stores full HTML; output is one CSV per run; LLM is Claude or Ollama only; LLM stage gated |
| [alur-kerja-teknis-scrapebot.pdf](alur-kerja-teknis-scrapebot.pdf) | 2026-10-05 | LLM via instructor with a few providers (now LiteLLM + instructor, all providers); no bulk interface; no region settings |
| [cara-kerja-layer-scrapebot.pdf](cara-kerja-layer-scrapebot.pdf) | 2026-10-09 | Describes the final list and the LLM on by default as on branch `feat/final-knitwear-list` (not yet merged) |
| [analisis-pesaing-dan-retailer.pdf](analisis-pesaing-dan-retailer.pdf) | 2026-10-12 | Nothing known: a business reading of the [competitive and retailer analysis PRD](../product/prd-competitive-retailer-analysis.md) (draft, not built): goals, process, first findings, limits, decisions needed |
| [scrapebot-overview-en.pdf](scrapebot-overview-en.pdf) | 2026-10-12 | Nothing known: background, goals, stack and flow as on `main` after PR #9. Says Tavily has run for real (discovery of 2026-10-09), which the roadmap does not yet |
