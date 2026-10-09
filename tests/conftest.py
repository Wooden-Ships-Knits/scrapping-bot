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


@pytest.fixture(autouse=True)
def _no_project_env_file(monkeypatch, tmp_path):
    """No test reads the developer's own `.env`: with the LLM on by default, a run
    started by a test would otherwise call a real provider. Tests that need keys write
    their own `.env` in a temporary folder."""
    from pathlib import Path

    from scrapebot import keys

    project_env = Path(".env").resolve()
    original = keys.load_keys

    def load_keys(env_file=".env", given=None):
        if Path(env_file).resolve() == project_env:
            env_file = tmp_path / "no-project-keys.env"
        return original(env_file, given)

    for module in ("scrapebot.keys", "scrapebot.cli", "scrapebot.api.app"):
        monkeypatch.setattr(f"{module}.load_keys", load_keys)
