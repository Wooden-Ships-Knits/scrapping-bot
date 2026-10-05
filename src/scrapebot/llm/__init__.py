"""The LLM stage (ADR 0004): read products from page text when nothing structured
exists. Needs the `llm` extra: `uv sync --extra llm`."""

import os

# LiteLLM downloads its model price list from GitHub on first use unless told to use
# the copy bundled with the installed version. Use the bundled copy: no hidden
# network call, and costs that match the pinned version.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
