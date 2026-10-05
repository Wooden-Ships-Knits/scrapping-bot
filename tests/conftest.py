"""Shared test setup. Runs before any test module is imported."""

import os

# Keep LiteLLM offline: use its bundled price list instead of fetching one.
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
