from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class ScoreBreakdownOut(BaseModel):
    score: int | None = None
    fit: str = ""
    matched_keywords: list[str] = []
    missing_skills: list[str] = []
    fit_notes: str = ""


class JobApplicationOut(BaseModel):
    id: int
    selected: str
    date_found: str
    date_applied: str
    company: str
    role: str
    location: str
    source: str
    remote_type: str
    fit: str
    fit_score: int
    link: str
    status: str
    next_step: str
    follow_up_date: str
    resume_ref: str
    cover_letter_ref: str
    match_profile: str
    first_seen_at: str
    last_seen_at: str
    listing_fingerprint: str
    change_note: str
    notes: str
    score_breakdown: ScoreBreakdownOut | None = None

    model_config = {"from_attributes": True}


class JobApplicationUpdate(BaseModel):
    selected: str | None = Field(default=None, max_length=10)
    date_applied: str | None = Field(default=None, max_length=32)
    status: str | None = Field(default=None, max_length=128)
    next_step: str | None = Field(default=None, max_length=8192)
    follow_up_date: str | None = Field(default=None, max_length=32)
    resume_ref: str | None = Field(default=None, max_length=8192)
    cover_letter_ref: str | None = Field(default=None, max_length=8192)
    match_profile: str | None = Field(default=None, max_length=32)
    notes: str | None = Field(default=None, max_length=50_000)
    # first_seen_at / last_seen_at are system-managed and not patchable via this schema


class JobApplicationUpsert(BaseModel):
    selected: str = Field(default="no", max_length=10)
    date_found: str = Field(default="", max_length=32)
    date_applied: str = Field(default="", max_length=32)
    company: str = Field(min_length=1, max_length=255)
    role: str = Field(min_length=1, max_length=255)
    location: str = Field(default="", max_length=255)
    source: str = Field(default="", max_length=255)
    remote_type: str = Field(default="", max_length=255)
    fit: str = Field(default="", max_length=64)
    fit_score: int = Field(default=0, ge=0, le=100)
    link: str = Field(default="", max_length=8192)
    status: str = Field(default="", max_length=128)
    next_step: str = Field(default="", max_length=8192)
    follow_up_date: str = Field(default="", max_length=32)
    resume_ref: str = Field(default="", max_length=8192)
    cover_letter_ref: str = Field(default="", max_length=8192)
    match_profile: str = Field(default="", max_length=32)
    first_seen_at: str = Field(default="", max_length=32)
    last_seen_at: str = Field(default="", max_length=32)
    listing_fingerprint: str = Field(default="", max_length=8192)
    change_note: str = Field(default="", max_length=50_000)
    score_breakdown: str = Field(default="", max_length=100_000)
    notes: str = Field(default="", max_length=50_000)

    @field_validator("link")
    @classmethod
    def _validate_link(cls, v: str) -> str:
        if not v:
            return v
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("link must be a valid http:// or https:// URL")
        return v


class PaginatedApplications(BaseModel):
    items: list[JobApplicationOut]
    total: int
    limit: int
    offset: int


class SkillGapItem(BaseModel):
    skill: str
    count: int


class SkillGapList(BaseModel):
    items: list[SkillGapItem]


class TrendItem(BaseModel):
    week: str
    count: int


class TrendList(BaseModel):
    items: list[TrendItem]


class StatsOut(BaseModel):
    total_applications: int
    by_status: dict[str, int]
    by_stage: dict[str, int]


class DiscoveryStatusOut(BaseModel):
    in_flight: bool
    elapsed_seconds: float | None = None
    cooldown_seconds_remaining: float | None = None


class DiscoveryRunRequest(BaseModel):
    limit: int = Field(default=40, ge=1, le=500)
    min_score: int = Field(default=7, ge=0, le=100)
    max_age_days: int = Field(default=45, ge=1, le=3650)
    include_stretch: bool = False
    profile: str = "de"
    salary_min_usd: int | None = Field(default=None, ge=0, le=10_000_000)
    timezones: list[str] | None = None
    seniority: str | None = None
    use_outcome_priors: bool = False
    prior_lookback_days: int = Field(default=365, ge=1, le=3650)
    source_prior_weight: float = Field(default=1.0, ge=0.0, le=5.0)
    role_prior_weight: float = Field(default=1.0, ge=0.0, le=5.0)
    use_llm_reranker: bool = False
    llm_top_n: int = Field(default=20, ge=1, le=200)
    llm_weight: float = Field(default=1.0, ge=0.0, le=5.0)
    llm_model: str | None = None
    llm_api_base_url: str | None = None
    llm_dry_run: bool = False
    llm_max_calls: int = Field(default=20, ge=1, le=200)
    llm_max_input_chars: int = Field(default=50000, ge=1000, le=1_000_000)
    llm_max_retries: int = Field(default=2, ge=0, le=10)
    llm_retry_backoff_seconds: float = Field(default=0.5, ge=0.0, le=30.0)
    llm_timeout_seconds: int = Field(default=20, ge=1, le=180)
    output_dir: str | None = None
    cv_path: str | None = None
    api_base_url: str | None = None
    verbose: bool = False
    sources: list[str] | None = None

    @field_validator("profile")
    @classmethod
    def _validate_profile(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in {"de", "swe", "sre", "other"}:
            raise ValueError("profile must be one of: de, swe, sre, other")
        return v

    @field_validator("seniority")
    @classmethod
    def _validate_seniority(cls, v: str | None) -> str | None:
        if not v:
            return v
        v = v.strip().lower()
        if v not in {"junior", "mid", "senior"}:
            raise ValueError("seniority must be one of: junior, mid, senior")
        return v

    @field_validator("llm_api_base_url")
    @classmethod
    def _validate_llm_api_base_url(cls, v: str | None) -> str | None:
        if not v:
            return v
        v = v.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("llm_api_base_url must start with http:// or https://")
        return v


class SourceRunResult(BaseModel):
    key: str
    label: str
    collected: int
    error: str = ""


class DiscoveryRunResponse(BaseModel):
    exit_code: int
    command: list[str]
    stdout: str
    stderr: str
    source_results: list[SourceRunResult] = []
    strict_count: int = 0
    broad_count: int = 0
    synced_count: int = 0
    failed_count: int = 0


class GenerateDocumentsRequest(BaseModel):
    overwrite: bool = False
    author_name: str | None = None
    your_name: str | None = None


class GenerateDocumentsResult(BaseModel):
    vacancy_dir: str
    vacancy_path: str
    cv_path: str
    cover_letter_path: str
    notes_path: str


class WorkspaceFileReadResult(BaseModel):
    path: str
    content: str


class WorkspaceFileWriteRequest(BaseModel):
    path: str = Field(max_length=512)
    content: str = Field(max_length=1_000_000)
