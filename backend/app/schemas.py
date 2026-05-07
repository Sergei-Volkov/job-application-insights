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
    notes: str = ""


class SyncResult(BaseModel):
    added: int
    updated: int


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


class DiscoveryRunResult(BaseModel):
    exit_code: int
    command: list[str]
    stdout: str
    stderr: str
