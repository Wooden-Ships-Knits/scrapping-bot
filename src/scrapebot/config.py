"""Settings for one run. The CLI and the web API build the same `RunConfig` (PRD OP-04).

Settings come from a YAML file (see `config.example.yaml`); command-line flags
override it. Unknown keys are rejected, so a typo fails loudly instead of being
ignored. API keys never belong here (standards, section 4).
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .outputs import available_writers


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InputConfig(_Section):
    source: Path | None = None  # a file in any supported format
    text: str | None = None  # links pasted as free text
    url_column: str = "auto"  # for tabular files; "auto" finds it
    max_links: int = Field(default=1000, ge=1)  # PRD IN-07


class FetchConfig(_Section):
    cache_dir: Path = Path("data/.cache")
    delay_seconds: float = Field(default=1.5, ge=0)  # per domain
    timeout_seconds: float = Field(default=20, gt=0)
    retries: int = Field(default=2, ge=0)
    # Stores visited at once. Each host still gets one request at a time, `delay_seconds` apart.
    concurrency: int = Field(default=6, ge=1, le=32)


class OutputConfig(_Section):
    runs_dir: Path = Path("data/runs")
    writers: list[str] = Field(default_factory=lambda: ["xlsx", "csv"])

    @field_validator("writers")
    @classmethod
    def _known_writers(cls, names: list[str]) -> list[str]:
        unknown = [n for n in names if n not in available_writers()]
        if unknown:
            raise ValueError(
                f"unknown writer(s) {unknown}; available: {', '.join(available_writers())}"
            )
        if not names:
            raise ValueError("choose at least one writer")
        return list(dict.fromkeys(names))


class RunConfig(_Section):
    input: InputConfig = Field(default_factory=InputConfig)
    fetch: FetchConfig = Field(default_factory=FetchConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    # Test mode (PRD OP-01): visit only the first N stores, end to end. None = full run.
    limit: int | None = Field(default=None, ge=1)


def load_config(path: str | Path) -> RunConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return RunConfig.model_validate(data)
