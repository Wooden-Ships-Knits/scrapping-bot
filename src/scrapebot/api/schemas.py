"""Request and response bodies. The web app's TypeScript types are generated from these."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

RunState = Literal["queued", "running", "stopped", "done", "failed", "interrupted"]
DiscoveryState = Literal["searching", "starting_run", "done", "failed"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceIn(_In):
    """Exactly one of pasted text or a previously uploaded file."""

    text: str | None = None
    upload_id: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "SourceIn":
        if (self.text is None) == (self.upload_id is None):
            raise ValueError("give either text or upload_id")
        return self


class PreviewIn(_In):
    source: SourceIn
    url_column: str = "auto"


class LLMIn(_In):
    """LLM settings for one run. The key stays in memory for this run only (PRD LM-04)."""

    enabled: bool = False
    model: str = ""
    fallbacks: list[str] = Field(default_factory=list)
    budget_usd: float = Field(default=1.0, ge=0)
    api_base: str | None = None
    api_key: SecretStr | None = None


class LLMCheckIn(_In):
    model: str
    api_key: SecretStr | None = None
    api_base: str | None = None


class LLMCheckOut(BaseModel):
    ok: bool
    message: str


class ProviderOut(BaseModel):
    provider: str
    label: str
    example_model: str
    needs_key: bool
    key_in_env: bool  # a key for this provider is set in .env or the environment


class RunIn(_In):
    source: SourceIn
    url_column: str = "auto"
    writers: list[str] = Field(min_length=1)
    llm: LLMIn | None = None


class UploadOut(BaseModel):
    upload_id: str
    filename: str
    size_bytes: int


class SkippedLink(BaseModel):
    raw: str
    reason: str


class PreviewOut(BaseModel):
    links: int
    stores: int
    duplicates: int
    skipped: dict[str, int]
    skipped_examples: list[SkippedLink]
    store_examples: list[str]
    max_links: int
    too_many: bool


class StoreOut(BaseModel):
    domain: str
    url: str
    status: str
    error: str
    platform: str
    currency: str
    source_used: str
    product_count: int
    page_count: int
    contact_count: int
    ssl_bypassed: bool


class DownloadOut(BaseModel):
    key: str
    label: str
    filename: str


class RunOut(BaseModel):
    run_id: str
    state: RunState
    mode: Literal["test", "full"]
    limit: int | None
    started_at: str
    finished_at: str
    source_kind: Literal["text", "file"]
    source_name: str
    writers: list[str]
    links_in: int
    processed: int
    skipped: int
    skipped_by_reason: dict[str, int]
    stores_total: int
    stores_done: int
    status_counts: dict[str, int]
    products: int
    pages: int
    contacts: int
    stores: list[StoreOut]
    downloads: list[DownloadOut]
    error: str
    config: dict[str, Any]  # the run's settings, never secrets
    cli: str  # the equivalent command line
    llm_model: str  # "" when the run did not use the LLM stage
    llm_cost_usd: float
    llm_stores: int  # stores sent to the LLM


class RunListItem(BaseModel):
    run_id: str
    state: RunState
    mode: Literal["test", "full"]
    started_at: str
    source_name: str
    links_in: int
    stores_total: int
    stores_done: int
    products: int
    contacts: int


class OptionsOut(BaseModel):
    writers: list[str]
    default_writers: list[str]
    suffixes: list[str]
    max_links: int
    max_upload_mb: int


class RowsOut(BaseModel):
    """A page of one table's rows, for previewing data in the interface."""

    table: str
    columns: list[str]
    total: int
    offset: int
    rows: list[dict[str, Any]]
    truncated_fields: bool  # long values were shortened for the preview


class OverviewOut(BaseModel):
    runs: int
    runs_done: int
    stores: int
    products: int
    contacts: int
    last_run: RunListItem | None


class ErrorOut(BaseModel):
    code: str
    message: str


class DiscoverIn(_In):
    """Find stores, then start a run on them (ADR 0008)."""

    count: int = Field(ge=1, le=500)  # how many stores to find and visit
    region: str
    items: list[str] = Field(min_length=1)
    terms: list[str] = Field(default_factory=list)  # the operator's own words, item "other"
    writers: list[str] = Field(min_length=1)


class DiscoverySourceOut(BaseModel):
    name: str  # google_places | web_search | social_search | ai_agent
    status: str  # ok | disabled | no_api_key | budget_reached | error
    found: int
    error: str


class DiscoveryOut(BaseModel):
    discovery_id: str
    state: DiscoveryState
    count: int  # stores asked for
    step: str  # the source being searched now; "" when none
    found: int  # stores or sightings so far
    stores_to_visit: int  # stores with a website handed to the run
    sources: list[DiscoverySourceOut]
    cost_usd: float  # the agent's spend; search APIs bill per request
    run_id: str | None
    error: str


class DiscoverOptionsOut(BaseModel):
    regions: list[str]
    default_region: str
    items: list[str]
    default_items: list[str]
    max_count: int
    agent_model: str  # "" when no LLM key is set
    sources: dict[str, bool]  # source -> its key is set
