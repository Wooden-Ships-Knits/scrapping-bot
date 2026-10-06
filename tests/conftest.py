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
