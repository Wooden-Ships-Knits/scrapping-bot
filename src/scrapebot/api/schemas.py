"""Request and response bodies. The web app's TypeScript types are generated from these."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RunState = Literal["queued", "running", "done", "failed", "interrupted"]


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


class RunIn(_In):
    source: SourceIn
    url_column: str = "auto"
    writers: list[str] = Field(min_length=1)
    test_mode: bool = True
    test_limit: int = Field(default=2, ge=1, le=50)
    # PRD OP-01: a full run needs a test run of the same input first, unless the
    # operator deliberately skips it.
    skip_test_run: bool = False


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
    tested: bool  # a finished test run of exactly these links exists


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


class OptionsOut(BaseModel):
    writers: list[str]
    default_writers: list[str]
    suffixes: list[str]
    max_links: int
    default_test_limit: int
    max_upload_mb: int


class ErrorOut(BaseModel):
    code: str
    message: str
