"""Shared test setup. Runs before any test module is imported."""

import os

# Keep LiteLLM offline: use its bundled price list instead of fetching one.
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"


import pytest


@pytest.fixture(autouse=True)
def _no_browser(monkeypatch):
    """No test opens a real browser: runs see Camoufox as not installed. Tests of the
    render stage pass a fake renderer."""
    monkeypatch.setattr("scrapebot.render.camoufox_available", lambda: False)


@pytest.fixture(autouse=True)
def _no_real_keys(monkeypatch):
    """No test sees a developer's real provider keys. LiteLLM loads the project's .env
    into the environment when it is imported, so they would otherwise leak in."""
    from scrapebot.keys import SEARCH_KEY_VARIABLES
    from scrapebot.llm.gateway import KEY_VARIABLES

    for variable in (*KEY_VARIABLES.values(), *SEARCH_KEY_VARIABLES.values()):
        monkeypatch.delenv(variable, raising=False)
