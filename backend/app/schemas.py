from pydantic import BaseModel


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

    model_config = {"from_attributes": True}


class JobApplicationUpdate(BaseModel):
    selected: str | None = None
    date_applied: str | None = None
    status: str | None = None
    next_step: str | None = None
    follow_up_date: str | None = None
    resume_ref: str | None = None
    cover_letter_ref: str | None = None
    match_profile: str | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    listing_fingerprint: str | None = None
    change_note: str | None = None
    notes: str | None = None


class JobApplicationUpsert(BaseModel):
    selected: str = "no"
    date_found: str = ""
    date_applied: str = ""
    company: str
    role: str
    location: str = ""
    source: str = ""
    remote_type: str = ""
    fit: str = ""
    fit_score: int = 0
    link: str = ""
    status: str = ""
    next_step: str = ""
    follow_up_date: str = ""
    resume_ref: str = ""
    cover_letter_ref: str = ""
    match_profile: str = ""
    first_seen_at: str = ""
    last_seen_at: str = ""
    listing_fingerprint: str = ""
    change_note: str = ""
    notes: str = ""


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


class DiscoveryRunRequest(BaseModel):
    limit: int = 40
    min_score: int = 7
    max_age_days: int = 45
    include_stretch: bool = False
    profile: str = "de"
    salary_min_usd: int | None = None
    timezones: list[str] | None = None
    seniority: str | None = None
    use_outcome_priors: bool = False
    prior_lookback_days: int = 365
    source_prior_weight: float = 1.0
    role_prior_weight: float = 1.0
    cv_path: str | None = None
    api_base_url: str | None = None
    verbose: bool = False
    sources: list[str] | None = None


class DiscoveryRunResult(BaseModel):
    exit_code: int
    command: list[str]
    stdout: str
    stderr: str


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
    path: str
    content: str
