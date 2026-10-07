"""Store discovery (ADR 0008): find knitwear stores to scrape, before a run.

Sources are paid search APIs (Google Places, Tavily) and an LLM that searches the
web. Their answers are leads, merged into one row per store and written as a
links file that `scrapebot run` reads like any other input. Nothing here opens a
store's website: judging a store is left to the data a run collects.
"""

from .config import DiscoverConfig, load_discover_config
from .run import DiscoverResult, run_discover

__all__ = ["DiscoverConfig", "DiscoverResult", "load_discover_config", "run_discover"]
