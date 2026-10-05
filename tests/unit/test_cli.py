import io

import pytest

from scrapebot import cli


@pytest.fixture
def captured(monkeypatch, tmp_path):
    """Replace the pipeline so CLI tests never fetch anything."""
    seen = {}

    class Result:
        links_in = processed = skipped = stores = 0
        stopped = False
        root = report_path = summary_path = tmp_path

    def fake_run(config, **kwargs):
        seen["config"] = config
        return Result()

    monkeypatch.setattr(cli, "run", fake_run)
    return seen


def test_flags_build_the_run_config(captured, tmp_path):
    src = tmp_path / "in.csv"
    src.write_text("website\nhttps://a.com\n")
    code = cli.main(
        [
            "run",
            str(src),
            "--limit",
            "2",
            "--format",
            "xlsx, parquet",
            "--runs-dir",
            str(tmp_path / "r"),
        ]
    )
    assert code == 0
    cfg = captured["config"]
    assert cfg.input.source == src
    assert cfg.limit == 2
    assert cfg.output.writers == ["xlsx", "parquet"]
    assert cfg.output.runs_dir == tmp_path / "r"


def test_flags_override_the_config_file(captured, tmp_path):
    conf = tmp_path / "c.yaml"
    conf.write_text("limit: 5\noutput:\n  writers: [json]\n")
    cli.main(["run", "x.csv", "-c", str(conf), "--limit", "2"])
    assert captured["config"].limit == 2
    assert captured["config"].output.writers == ["json"]


def test_dash_reads_pasted_links_from_stdin(captured, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("a.com b.com"))
    cli.main(["run", "-"])
    assert captured["config"].input.text == "a.com b.com"
    assert captured["config"].input.source is None


def test_bad_settings_exit_with_code_2(captured, capsys):
    assert cli.main(["run", "x.csv", "--format", "pdf"]) == 2
    assert "unknown writer" in capsys.readouterr().err


def test_llm_flags_enable_the_llm_stage_without_any_key_in_the_config(captured):
    cli.main(
        [
            "run",
            "x.csv",
            "--llm",
            "ollama/qwen2.5:3b",
            "--llm-fallback",
            "gemini/gemini-2.5-flash",
            "--llm-budget",
            "0.5",
        ]
    )
    llm = captured["config"].llm
    assert (llm.enabled, llm.model, llm.fallbacks, llm.budget_usd) == (
        True,
        "ollama/qwen2.5:3b",
        ["gemini/gemini-2.5-flash"],
        0.5,
    )
    assert "key" not in llm.model_dump_json()


def test_a_model_without_a_provider_is_refused(captured, capsys):
    assert cli.main(["run", "x.csv", "--llm", "gpt-4o-mini"]) == 2
    assert "provider/model" in capsys.readouterr().err
