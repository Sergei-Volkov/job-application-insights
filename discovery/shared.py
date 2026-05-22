from __future__ import annotations

import json
import os
import re
import ssl
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

WWR_FEEDS = [
    "https://weworkremotely.com/categories/all-other-remote-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss",
]
JOBICY_FEED = "https://jobicy.com/?feed=job_feed"
WORKING_NOMADS_API = "https://www.workingnomads.com/api/exposed_jobs/"
REMOTEOK_API = "https://remoteok.com/api"
REMOTIVE_API = "https://remotive.com/api/remote-jobs?search={query}"
ARBEITNOW_API = "https://www.arbeitnow.com/api/job-board-api"
SEARCH_TERMS = ["data engineer", "analytics engineer", "data platform", "airflow", "etl"]
PROFILE_SEARCH_TERMS = {
    "de": ["data engineer", "analytics engineer", "data platform", "airflow", "etl"],
    "swe": ["software engineer", "backend engineer", "platform engineer", "infrastructure engineer"],
    "other": ["data engineer", "software engineer", "platform engineer", "etl", "backend engineer"],
}

SOURCE_OPTIONS = ["wwr", "working_nomads", "remoteok", "remotive", "arbeitnow", "jobicy"]

KEYWORD_WEIGHTS = {
    "python": 3,
    "sql": 3,
    "airflow": 3,
    "etl": 2,
    "elt": 2,
    "postgres": 2,
    "postgresql": 2,
    "docker": 2,
    "aws": 2,
    "dbt": 2,
    "databricks": 2,
    "bigquery": 2,
    "gcp": 2,
    "terraform": 1,
    "analytics": 1,
    "reporting": 1,
    "data quality": 2,
    "pipeline": 2,
    "warehouse": 1,
    "snowflake": 2,
}

DISPLAY_NAMES = {
    "python": "Python",
    "sql": "SQL",
    "airflow": "Airflow",
    "etl": "ETL",
    "elt": "ELT",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "docker": "Docker",
    "aws": "AWS",
    "dbt": "dbt",
    "databricks": "Databricks",
    "bigquery": "BigQuery",
    "gcp": "GCP",
    "terraform": "Terraform",
    "analytics": "analytics",
    "reporting": "reporting",
    "data quality": "data quality",
    "pipeline": "pipelines",
    "warehouse": "data warehousing",
    "snowflake": "Snowflake",
}

SKILL_PATTERNS = {
    "python": [r"\bpython\b"],
    "sql": [r"\bsql\b", r"sqlalchemy"],
    "airflow": [r"\bairflow\b"],
    "etl": [r"\betl\b", r"pipelines?"],
    "elt": [r"\belt\b"],
    "postgres": [r"\bpostgres\b", r"\bpostgresql\b"],
    "postgresql": [r"\bpostgresql\b"],
    "docker": [r"\bdocker\b"],
    "aws": [r"\baws\b"],
    "analytics": [r"\banalytics\b", r"analysis-ready", r"reporting"],
    "reporting": [r"\breporting\b"],
    "data quality": [r"data quality", r"validation"],
    "pipeline": [r"pipelines?"],
    "warehouse": [r"warehouse", r"warehouse-ready"],
}

OWNED_SKILLS = set(SKILL_PATTERNS)
ACTIVE_PROFILE = "de"

REJECT_PATTERNS = [
    "data scientist",
    "data annotator",
    "marketing analytics",
    "ga4",
    "gtm",
    "manager",
    "director",
    "frontend",
    "front end",
    "full stack",
    "prompt engineering",
    "dataannotation",
    "voip",
    "volunteer",
    "talent community",
]

DEFAULT_API_BASE_URL = os.environ.get("JOB_SEARCH_API_BASE_URL", "http://127.0.0.1:8000")
DEFAULT_API_WRITE_KEY = os.environ.get("JOB_SEARCH_WRITE_API_KEY", "")


@dataclass
class JobMatch:
    title: str
    company: str
    source: str
    remote_policy: str
    freshness: str
    fit: str
    score: int
    url: str
    details_text: str
    matched_keywords: str
    missing_skills: str
    fit_notes: str


@dataclass(frozen=True)
class SourceAdapter:
    key: str
    label: str
    collector: Callable[[], list[JobMatch]]


@dataclass
class SourceRunReport:
    key: str
    label: str
    collected: int
    error: str = ""


@dataclass
class CollectionReport:
    sources: list[SourceRunReport]
    raw_total: int
    filtered_age: int
    filtered_score: int
    filtered_stretch: int
    filtered_salary: int
    filtered_timezone: int
    filtered_seniority: int
    dedup_collisions: int
    deduped_total: int


@dataclass
class ApiUpsertFailure:
    company: str
    title: str
    source: str
    status_code: int | None
    error_type: str
    message: str


@dataclass
class OutcomePriors:
    source: dict[str, float]
    role_family: dict[str, float]


TRANSIENT_HTTP_CODES = {408, 425, 429, 500, 502, 503, 504}


def classify_upsert_exception(exc: Exception) -> tuple[int | None, str, bool]:
    if isinstance(exc, HTTPError):
        status_code = int(getattr(exc, "code", 0) or 0)
        transient = status_code in TRANSIENT_HTTP_CODES
        return status_code, "HTTPError", transient
    if isinstance(exc, URLError):
        return None, "URLError", True
    if isinstance(exc, TimeoutError):
        return None, "TimeoutError", True
    return None, type(exc).__name__, False


def fetch_json(
    url: str,
    timeout: int = 25,
    extra_headers: dict[str, str] | None = None,
) -> object:
    headers: dict[str, str] = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    request = Request(url, headers=headers)
    context = ssl.create_default_context()
    with urlopen(request, timeout=timeout, context=context) as response:
        return json.loads(response.read().decode("utf-8", errors="ignore"))


def fetch_text(url: str, timeout: int = 25) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    context = ssl.create_default_context()
    with urlopen(request, timeout=timeout, context=context) as response:
        return response.read().decode("utf-8", errors="ignore")


def post_json(
    url: str,
    payload: dict[str, object],
    timeout: int = 25,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, object]:
    headers: dict[str, str] = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    context = ssl.create_default_context()
    with urlopen(request, timeout=timeout, context=context) as response:
        return json.loads(response.read().decode("utf-8", errors="ignore"))


def normalize(text: object | None) -> str:
    return re.sub(r"\s+", " ", "" if text is None else str(text)).strip()


def normalize_url(url: str) -> str:
    raw = normalize(url)
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        query_items = [
            (k, v)
            for (k, v) in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith("utm_")
        ]
        normalized_query = urlencode(query_items, doseq=True)
        normalized_path = parts.path.rstrip("/") or "/"
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), normalized_path, normalized_query, ""))
    except Exception:
        return raw.rstrip("/")


def strip_latex(text: str) -> str:
    text = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r" \1 ", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?\{([^}]*)\}", r" \1 ", text)
    text = re.sub(r"\\[a-zA-Z]+\*?", " ", text)
    text = text.replace("\\\\", " ").replace("{", " ").replace("}", " ")
    return normalize(text)


def extract_owned_skills_from_cv(cv_path: Path) -> set[str]:
    raw_text = cv_path.read_text(encoding="utf-8", errors="ignore")
    text = strip_latex(raw_text).lower()
    owned: set[str] = set()

    for skill, patterns in SKILL_PATTERNS.items():
        if any(re.search(pattern, text) for pattern in patterns):
            owned.add(skill)

    if "postgres" in owned:
        owned.add("postgresql")
    if "pipeline" in owned:
        owned.add("etl")

    return owned


def infer_search_terms_for_profile(owned_skills: set[str], profile: str) -> list[str]:
    terms = PROFILE_SEARCH_TERMS.get(profile, PROFILE_SEARCH_TERMS["de"]).copy()
    if profile in {"de", "other"}:
        if "airflow" in owned_skills and "airflow" not in terms:
            terms.append("airflow")
        if ("etl" in owned_skills or "elt" in owned_skills) and "etl" not in terms:
            terms.append("etl")
    return terms


def profile_title_signals(profile: str) -> list[str]:
    if profile == "swe":
        return ["software engineer", "backend engineer", "platform engineer", "infrastructure", "devops"]
    if profile == "other":
        return [
            "data engineer",
            "analytics engineer",
            "software engineer",
            "backend engineer",
            "platform engineer",
            "devops",
        ]
    return [
        "data engineer",
        "analytics engineer",
        "data platform",
        "data ops",
        "data devops",
        "etl developer",
        "bi engineer",
    ]


def profile_reject_patterns(profile: str) -> list[str]:
    if profile == "swe":
        return ["data scientist", "data annotator", "marketing analytics", "manager", "director", "volunteer"]
    if profile == "other":
        return ["manager", "director", "volunteer", "talent community"]
    return REJECT_PATTERNS


def split_company_and_title(raw_title: str, fallback_company: str = "Unknown") -> tuple[str, str]:
    raw_title = normalize(raw_title)
    if not raw_title:
        return fallback_company, "Unknown role"

    if ":" in raw_title:
        company, title = raw_title.split(":", 1)
        return normalize(company), normalize(title)

    lower = raw_title.lower()
    if " at " in lower:
        idx = lower.rfind(" at ")
        title = raw_title[:idx]
        company = raw_title[idx + 4 :]
        return normalize(company), normalize(title)

    if " - " in raw_title:
        left, right = raw_title.split(" - ", 1)
        if any(term in left.lower() for term in ["engineer", "analytics", "etl", "airflow", "platform"]):
            return normalize(fallback_company), normalize(left)
        return normalize(left), normalize(right)

    return normalize(fallback_company), raw_title


def is_relevant(title: str, details: str) -> bool:
    title_lower = title.lower()
    details_lower = details.lower()
    if any(bad in title_lower for bad in profile_reject_patterns(ACTIVE_PROFILE)):
        return False

    strong_title_signals = profile_title_signals(ACTIVE_PROFILE)
    if any(signal in title_lower for signal in strong_title_signals):
        return True

    has_data_word = re.search(r"\bdata\b", title_lower) is not None
    has_role_word = (
        re.search(r"\b(engineer|platform|warehouse|analytics|etl|elt|devops|backend|software)\b", title_lower)
        is not None
    )
    if has_data_word and has_role_word:
        return True

    adjacent_title = re.search(r"\b(devops|platform|backend|software|infrastructure)\b", title_lower) is not None
    stack_hits = sum(
        keyword in details_lower
        for keyword in [
            "airflow",
            "dbt",
            "databricks",
            "bigquery",
            "snowflake",
            "etl",
            "warehouse",
            "pipeline",
            "analytics",
        ]
    )
    return bool(adjacent_title and stack_hits >= 2)


def score_match(title: str, details: str) -> int:
    text = f"{title} {details}".lower()
    title_lower = title.lower()
    score = 0
    for keyword, weight in KEYWORD_WEIGHTS.items():
        if keyword in text:
            score += weight if keyword in OWNED_SKILLS else 1
    if "data engineer" in title_lower:
        score += 6
    if ACTIVE_PROFILE == "swe" and ("software engineer" in title_lower or "backend engineer" in title_lower):
        score += 5
    if ACTIVE_PROFILE == "other" and ("software engineer" in title_lower or "backend engineer" in title_lower):
        score += 3
    if "analytics engineer" in title_lower:
        score += 5
    if "data platform" in title_lower or "data ops" in title_lower or "data devops" in title_lower:
        score += 4
    if "remote" in text or "world" in text or "emea" in text or "europe" in text:
        score += 1
    return score


def fit_label(score: int) -> str:
    if score >= 12:
        return "Strong"
    if score >= 7:
        return "Medium"
    return "Stretch"


def parse_date(raw: str | None) -> str:
    raw = normalize(raw)
    if not raw:
        return "n/a"

    iso_match = re.search(r"\d{4}-\d{2}-\d{2}", raw)
    if iso_match:
        return iso_match.group(0)

    if raw.isdigit() and len(raw) >= 10:
        try:
            return datetime.fromtimestamp(int(raw)).strftime("%Y-%m-%d")
        except Exception:
            pass

    try:
        return parsedate_to_datetime(raw).strftime("%Y-%m-%d")
    except Exception:
        return raw[:20]


def days_old(date_str: str) -> int | None:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", date_str)
    if not match:
        return None
    try:
        then = datetime.strptime(match.group(1), "%Y-%m-%d")
        return (datetime.now() - then).days
    except Exception:
        return None


def parse_remote_policy(text: str) -> str:
    lower = text.lower()
    if "anywhere in the world" in lower or "worldwide" in lower:
        return "Worldwide"
    if "emea" in lower:
        return "EMEA"
    if "europe" in lower:
        return "Europe"
    if "north america" in lower or "us only" in lower or "usa only" in lower:
        return "US/North America"
    if "remote" in lower:
        return "Remote"
    return "Not stated"


SENIORITY_LEVELS = {
    "junior": 1,
    "mid": 2,
    "senior": 3,
    "lead": 4,
    "staff": 5,
}


def infer_seniority(title: str, details: str) -> str:
    text = f"{title} {details}".lower()
    if any(token in text for token in ["staff", "principal"]):
        return "staff"
    if "lead" in text:
        return "lead"
    if any(token in text for token in ["senior", "sr.", "sr "]):
        return "senior"
    if any(token in text for token in ["junior", "jr.", "jr ", "entry level", "intern"]):
        return "junior"
    return "mid"


def matches_seniority(title: str, details: str, requested: str | None) -> bool:
    if not requested:
        return True
    req = requested.strip().lower()
    if req not in {"junior", "mid", "senior"}:
        return True
    detected = infer_seniority(title, details)
    return SENIORITY_LEVELS[detected] >= SENIORITY_LEVELS[req]


def extract_salary_ceiling_usd(text: str) -> int | None:
    lower = text.lower()
    if not any(token in lower for token in ["$", "usd", "salary", "compensation", "pay", "rate"]):
        return None

    amounts: list[int] = []
    for match in re.finditer(r"(\d{2,3})(\s?)(k)\b", lower):
        amounts.append(int(match.group(1)) * 1000)

    for match in re.finditer(r"\b(\d{4,6})\b", lower):
        value = int(match.group(1))
        if 10_000 <= value <= 1_000_000:
            amounts.append(value)

    if not amounts:
        return None
    return max(amounts)


def matches_salary_requirement(title: str, details: str, minimum_usd: int | None) -> bool:
    if minimum_usd is None or minimum_usd <= 0:
        return True
    ceiling = extract_salary_ceiling_usd(f"{title} {details}")
    if ceiling is None:
        return True
    return ceiling >= minimum_usd


def matches_timezone(remote_policy: str, details: str, allowed_timezones: list[str] | None) -> bool:
    if not allowed_timezones:
        return True
    text = f"{remote_policy} {details}".lower()
    normalized_allowed = [tz.strip().lower() for tz in allowed_timezones if tz and tz.strip()]
    if not normalized_allowed:
        return True
    if any(token in text for token in normalized_allowed):
        return True
    return "remote" in text and "only" not in text


def extract_keywords(text: str) -> tuple[list[str], list[str]]:
    lower = text.lower()
    owned: list[str] = []
    missing: list[str] = []
    for keyword in KEYWORD_WEIGHTS:
        if keyword in lower:
            label = DISPLAY_NAMES[keyword]
            if keyword in OWNED_SKILLS:
                if label not in owned:
                    owned.append(label)
            else:
                if label not in missing:
                    missing.append(label)
    return owned, missing


def build_fit_note(title: str, details: str, remote_policy: str) -> tuple[str, str, str]:
    matched_keywords, missing_keywords = extract_keywords(f"{title} {details}")
    parts: list[str] = []
    if matched_keywords:
        parts.append(f"Direct overlap on {', '.join(matched_keywords[:6])}")
    if missing_keywords:
        parts.append(f"missing or adjacent tools: {', '.join(missing_keywords[:5])}")
    if remote_policy in {"Worldwide", "EMEA", "Europe", "Remote"}:
        parts.append("remote setup looks workable")
    note = ". ".join(parts).strip()
    if note and not note.endswith("."):
        note += "."
    return (
        ", ".join(matched_keywords),
        ", ".join(missing_keywords),
        note or "General overlap with your data-engineering profile.",
    )


def next_step_for_fit(fit: str) -> str:
    if fit == "Strong":
        return "Tailor CV and apply soon"
    if fit == "Medium":
        return "Review requirements and tailor selectively"
    return "Keep as backup option"


def tailoring_points(match: JobMatch) -> list[str]:
    keywords = {item.strip() for item in match.matched_keywords.split(",") if item.strip()}
    points = ["Highlight Python and SQL pipeline development experience."]

    if "Airflow" in keywords:
        points.append("Emphasize Airflow orchestration and batch workflow reliability.")
    if "data quality" in keywords:
        points.append("Use the 20% data-quality improvement result prominently.")
    if "analytics" in keywords or "reporting" in keywords:
        points.append("Stress analytics-ready datasets and reporting support.")
    if "AWS" in keywords or "Docker" in keywords:
        points.append("Mention cloud and containerized delivery experience.")
    if any(item in keywords for item in ["dbt", "BigQuery", "GCP", "Databricks", "Terraform", "Snowflake"]):
        points.append("Call out quick ramp-up on adjacent platform tooling.")

    deduped: list[str] = []
    for point in points:
        if point not in deduped:
            deduped.append(point)
    return deduped[:4]


def build_job_match(
    title: str,
    company: str,
    source: str,
    remote_policy: str,
    freshness: str,
    url: str,
    details: str,
) -> JobMatch:
    score = score_match(title, details)
    matched_keywords, missing_skills, fit_notes = build_fit_note(title, details, remote_policy)
    return JobMatch(
        title=title,
        company=company or "Unknown",
        source=source,
        remote_policy=remote_policy or "Not stated",
        freshness=freshness or "n/a",
        fit=fit_label(score),
        score=score,
        url=url,
        details_text=normalize(details),
        matched_keywords=matched_keywords,
        missing_skills=missing_skills,
        fit_notes=fit_notes,
    )


def classify_role_family(title: str) -> str:
    lower = title.lower()
    if any(token in lower for token in ["data engineer", "etl", "pipeline", "warehouse"]):
        return "data_engineering"
    if "analytics engineer" in lower:
        return "analytics_engineering"
    if any(token in lower for token in ["backend", "software engineer", "api", "services"]):
        return "backend"
    if any(token in lower for token in ["platform", "infrastructure", "devops", "sre"]):
        return "platform"
    return "other"


def status_outcome_weight(status: str) -> float:
    lower = status.strip().lower()
    if "offer" in lower:
        return 3.0
    if "interview" in lower:
        return 2.0
    if "applied" in lower:
        return 1.0
    if "rejected" in lower:
        return -2.0
    return 0.0


def build_outcome_priors(
    rows: list[dict[str, object]],
    lookback_days: int = 365,
    min_samples: int = 3,
) -> OutcomePriors:
    now = datetime.now()
    source_scores: dict[str, list[float]] = {}
    role_scores: dict[str, list[float]] = {}

    for row in rows:
        date_found = normalize(row.get("date_found"))
        age = days_old(date_found)
        if age is not None and age > max(lookback_days, 1):
            continue

        status = normalize(row.get("status"))
        weight = status_outcome_weight(status)
        if weight == 0:
            continue

        source_key = normalize(row.get("source")).lower()
        role = normalize(row.get("role"))
        role_family = classify_role_family(role)

        if source_key:
            source_scores.setdefault(source_key, []).append(weight)
        role_scores.setdefault(role_family, []).append(weight)

    def summarize(scores: dict[str, list[float]]) -> dict[str, float]:
        out: dict[str, float] = {}
        for key, values in scores.items():
            if len(values) < min_samples:
                continue
            avg = sum(values) / len(values)
            out[key] = max(-2.0, min(2.0, avg))
        return out

    return OutcomePriors(
        source=summarize(source_scores),
        role_family=summarize(role_scores),
    )


def apply_outcome_priors(
    matches: list[JobMatch],
    priors: OutcomePriors,
    source_weight: float,
    role_weight: float,
) -> list[JobMatch]:
    adjusted: list[JobMatch] = []
    for item in matches:
        source_key = item.source.strip().lower()
        role_family = classify_role_family(item.title)
        source_bonus = priors.source.get(source_key, 0.0)
        role_bonus = priors.role_family.get(role_family, 0.0)
        delta = source_bonus * source_weight + role_bonus * role_weight
        if delta == 0:
            adjusted.append(item)
            continue
        bumped = int(round(delta))
        new_score = max(0, item.score + bumped)
        adjusted.append(
            JobMatch(
                title=item.title,
                company=item.company,
                source=item.source,
                remote_policy=item.remote_policy,
                freshness=item.freshness,
                fit=fit_label(new_score),
                score=new_score,
                url=item.url,
                details_text=item.details_text,
                matched_keywords=item.matched_keywords,
                missing_skills=item.missing_skills,
                fit_notes=item.fit_notes,
            )
        )
    return adjusted
