"""Settings for one run. The CLI and the web API build the same `RunConfig` (PRD OP-04).

Settings come from a YAML file (see `config.example.yaml`); command-line flags
override it. Unknown keys are rejected, so a typo fails loudly instead of being
ignored. API keys never belong here (standards, section 4).
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .extract.focus import DEFAULT_ITEMS, ITEMS, OTHER
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


class RenderConfig(_Section):
    """The browser stage (ADR 0002): Camoufox, for stores HTTP cannot read."""

    enabled: bool = True  # used when Camoufox is installed (make install)
    max_pages: int = Field(default=10, ge=1, le=25)  # rendered pages per store
    browsers: int = Field(default=2, ge=1, le=8)  # pages rendered at once
    timeout_seconds: float = Field(default=30, gt=0)  # to load a page
    settle_seconds: float = Field(default=6, ge=0)  # waited for the page's own requests


DEFAULT_LLM_MODEL = "openai/gpt-4o-mini"


class LLMConfig(_Section):
    """The LLM stage (PRD 7.4). Never holds keys: those come from the interface or .env.

    On by default (ADR 0010): it reads stores no other stage could and judges the store
    type the vendors leave unclear. gpt-4o-mini cost about US$0.001 a store on real
    runs; without its key the run goes on without it and the report says so.
    """

    enabled: bool = True
    model: str = DEFAULT_LLM_MODEL  # provider/model, e.g. gemini/gemini-2.5-flash
    fallbacks: list[str] = Field(default_factory=list)  # tried in order when `model` fails
    budget_usd: float = Field(default=1.0, ge=0)  # LLM calls stop once a run spends this
    api_base: str | None = None  # for a local or self-hosted server, e.g. Ollama

    @field_validator("model")
    @classmethod
    def _provider_prefix(cls, model: str) -> str:
        model = model.strip()
        if model and "/" not in model:
            raise ValueError("write the model as provider/model, e.g. gemini/gemini-2.5-flash")
        return model


class FocusConfig(_Section):
    """The kinds of items looked for (ADR 0008). Products are flagged, never dropped."""

    items: list[str] = Field(default_factory=lambda: list(DEFAULT_ITEMS))
    terms: list[str] = Field(default_factory=list)  # the operator's own words, item "other"

    @field_validator("items")
    @classmethod
    def _known_items(cls, items: list[str]) -> list[str]:
        known = [*ITEMS, OTHER]
        unknown = [i for i in items if i not in known]
        if unknown:
            raise ValueError(f"unknown item(s) {unknown}; choose from {', '.join(known)}")
        return list(dict.fromkeys(items))

    @field_validator("terms")
    @classmethod
    def _clean_terms(cls, terms: list[str]) -> list[str]:
        return list(dict.fromkeys(t.strip() for t in terms if t.strip()))


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
    llm: LLMConfig = Field(default_factory=LLMConfig)
    render: RenderConfig = Field(default_factory=RenderConfig)
    focus: FocusConfig = Field(default_factory=FocusConfig)
    # Test mode (PRD OP-01): visit only the first N stores, end to end. None = full run.
    limit: int | None = Field(default=None, ge=1)


def load_config(path: str | Path) -> RunConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return RunConfig.model_validate(data)
