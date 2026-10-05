from pathlib import Path

import pytest
from pydantic import ValidationError

from scrapebot.config import RunConfig, load_config

ROOT = Path(__file__).parents[2]


def test_defaults_are_a_safe_full_run():
    cfg = RunConfig()
    assert cfg.limit is None
    assert cfg.input.max_links == 1000
    assert cfg.fetch.delay_seconds == 1.5
    assert cfg.output.writers == ["xlsx", "csv"]


def test_example_config_in_the_repo_is_valid():
    cfg = load_config(ROOT / "config.example.yaml")
    assert cfg.limit == 2


def test_unknown_keys_fail_loudly(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("limt: 2\n")
    with pytest.raises(ValidationError, match="limt"):
        load_config(path)


def test_unknown_writer_is_refused():
    with pytest.raises(ValidationError, match="unknown writer"):
        RunConfig.model_validate({"output": {"writers": ["pdf"]}})


def test_duplicate_writers_are_collapsed():
    cfg = RunConfig.model_validate({"output": {"writers": ["csv", "csv", "json"]}})
    assert cfg.output.writers == ["csv", "json"]


def test_limit_must_be_positive():
    with pytest.raises(ValidationError):
        RunConfig(limit=0)
