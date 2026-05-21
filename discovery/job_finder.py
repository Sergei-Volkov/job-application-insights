from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import ssl
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parent if (APP_ROOT.parent / "applications").exists() else APP_ROOT
OUTPUT_DIR = REPO_ROOT / "applications" / "tracker"
TRACKER_PATH = OUTPUT_DIR / "job_applications.csv"
NOTES_PATH = OUTPUT_DIR / "application_notes_latest.md"
CHECKLIST_PATH = OUTPUT_DIR / "selected_jobs.md"
BROAD_MATCHES_PATH = OUTPUT_DIR / "job_matches_broad.md"

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

TRACKER_FIELDS = [
    "selected",
    "date_found",
    "date_applied",
    "company",
    "role",
    "location",
    "source",
    "remote_type",
    "fit",
    "fit_score",
    "link",
    "status",
    "next_step",
    "follow_up_date",
    "notes",
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
    return adjacent_title and stack_hits >= 2


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
        matched_keywords=matched_keywords,
        missing_skills=missing_skills,
        fit_notes=fit_notes,
    )


def collect_wwr() -> list[JobMatch]:
    matches: list[JobMatch] = []
    feed_errors: list[str] = []
    for feed_url in WWR_FEEDS:
        try:
            xml_text = fetch_text(feed_url)
            root = ET.fromstring(xml_text)
        except Exception as exc:
            feed_errors.append(f"{feed_url}: {exc}")
            continue

        for item in root.findall("./channel/item"):
            raw_title = normalize(item.findtext("title"))
            link = normalize(item.findtext("link"))
            region = normalize(item.findtext("region"))
            pub_date = parse_date(item.findtext("pubDate"))
            details = " ".join(
                normalize(item.findtext(tag)) for tag in ["description", "region", "category", "country"]
            )
            if not raw_title or not link or not is_relevant(raw_title, details):
                continue

            company, title = split_company_and_title(raw_title)
            matches.append(
                build_job_match(
                    title=title,
                    company=company,
                    source="We Work Remotely",
                    remote_policy=region or parse_remote_policy(details),
                    freshness=pub_date,
                    url=link,
                    details=details,
                )
            )
    if not matches and feed_errors:
        raise RuntimeError("; ".join(feed_errors[:3]))
    return matches


def collect_working_nomads() -> list[JobMatch]:
    matches: list[JobMatch] = []
    data = json.loads(fetch_text(WORKING_NOMADS_API))

    for item in data:
        title = normalize(item.get("title"))
        company = normalize(item.get("company_name")) or "Unknown"
        location = normalize(item.get("location"))
        pub_date = parse_date(item.get("pub_date", ""))
        tags = ", ".join(item.get("tags", []))
        details = f"{tags} {item.get('description', '')}"
        if not title or not is_relevant(title, details):
            continue
        matches.append(
            build_job_match(
                title=title,
                company=company,
                source="Working Nomads",
                remote_policy=location or parse_remote_policy(details),
                freshness=pub_date,
                url=normalize(item.get("url")),
                details=details,
            )
        )
    return matches


def collect_remoteok() -> list[JobMatch]:
    matches: list[JobMatch] = []
    data = json.loads(fetch_text(REMOTEOK_API))

    for item in data:
        title = normalize(item.get("position"))
        company = normalize(item.get("company")) or "Unknown"
        tags = ", ".join(item.get("tags", [])) if isinstance(item.get("tags"), list) else ""
        location = normalize(item.get("location"))
        details = f"{tags} {item.get('description', '')}"
        if not title or not is_relevant(title, details):
            continue
        matches.append(
            build_job_match(
                title=title,
                company=company,
                source="Remote OK",
                remote_policy=location or parse_remote_policy(details),
                freshness=parse_date(item.get("date", "")),
                url=normalize(item.get("url") or item.get("apply_url")),
                details=details,
            )
        )
    return matches


def collect_remotive() -> list[JobMatch]:
    matches: list[JobMatch] = []
    seen: set[tuple[str, str]] = set()
    term_errors: list[str] = []
    for term in SEARCH_TERMS:
        try:
            data = json.loads(fetch_text(REMOTIVE_API.format(query=quote_plus(term))))
        except Exception as exc:
            term_errors.append(f"{term}: {exc}")
            continue

        for item in data.get("jobs", []):
            title = normalize(item.get("title"))
            company = normalize(item.get("company_name")) or "Unknown"
            details = f"{' '.join(item.get('tags', []))} {item.get('description', '')}"
            if not title or not is_relevant(title, details):
                continue
            key = (company.lower(), title.lower())
            if key in seen:
                continue
            seen.add(key)
            matches.append(
                build_job_match(
                    title=title,
                    company=company,
                    source="Remotive",
                    remote_policy=normalize(item.get("candidate_required_location")) or parse_remote_policy(details),
                    freshness=parse_date(item.get("publication_date", "")),
                    url=normalize(item.get("url")),
                    details=details,
                )
            )
    if not matches and term_errors:
        raise RuntimeError("; ".join(term_errors[:3]))
    return matches


def collect_arbeitnow() -> list[JobMatch]:
    matches: list[JobMatch] = []
    data = json.loads(fetch_text(ARBEITNOW_API))

    for item in data.get("data", []):
        title = normalize(item.get("title"))
        company = normalize(item.get("company_name")) or "Unknown"
        tags = ", ".join(item.get("tags", []))
        job_types = ", ".join(item.get("job_types", []))
        details = f"{tags} {job_types} {item.get('description', '')}"
        if not title or not is_relevant(title, details):
            continue
        remote_text = "Remote" if item.get("remote") else normalize(item.get("location"))
        matches.append(
            build_job_match(
                title=title,
                company=company,
                source="Arbeitnow",
                remote_policy=remote_text or parse_remote_policy(details),
                freshness=parse_date(item.get("created_at", "")),
                url=normalize(item.get("url")),
                details=details,
            )
        )
    return matches


def collect_jobicy() -> list[JobMatch]:
    matches: list[JobMatch] = []
    xml_text = fetch_text(JOBICY_FEED)
    root = ET.fromstring(xml_text)

    for item in root.findall("./channel/item"):
        raw_title = normalize(item.findtext("title"))
        details = " ".join(
            normalize(item.findtext(tag)) for tag in ["description", "category", "job_listing:job_location"]
        )
        if not raw_title or not is_relevant(raw_title, details):
            continue
        company, title = split_company_and_title(raw_title)
        matches.append(
            build_job_match(
                title=title,
                company=company,
                source="Jobicy",
                remote_policy=parse_remote_policy(details),
                freshness=parse_date(item.findtext("pubDate", "")),
                url=normalize(item.findtext("link")),
                details=details,
            )
        )
    return matches


def source_adapters() -> dict[str, SourceAdapter]:
    return {
        "wwr": SourceAdapter("wwr", "We Work Remotely", collect_wwr),
        "working_nomads": SourceAdapter("working_nomads", "Working Nomads", collect_working_nomads),
        "remoteok": SourceAdapter("remoteok", "Remote OK", collect_remoteok),
        "remotive": SourceAdapter("remotive", "Remotive", collect_remotive),
        "arbeitnow": SourceAdapter("arbeitnow", "Arbeitnow", collect_arbeitnow),
        "jobicy": SourceAdapter("jobicy", "Jobicy", collect_jobicy),
    }


def collect_from_sources(selected_sources: list[str]) -> tuple[list[JobMatch], list[SourceRunReport]]:
    adapters = source_adapters()
    combined: list[JobMatch] = []
    reports: list[SourceRunReport] = []

    for key in selected_sources:
        adapter = adapters.get(key)
        if adapter is None:
            reports.append(SourceRunReport(key=key, label=key, collected=0, error="Unknown source key"))
            continue

        try:
            items = adapter.collector()
            combined.extend(items)
            reports.append(SourceRunReport(key=key, label=adapter.label, collected=len(items)))
        except Exception as exc:
            reports.append(SourceRunReport(key=key, label=adapter.label, collected=0, error=str(exc)))

    return combined, reports


def collect_matches(
    limit: int,
    min_score: int,
    max_age_days: int,
    include_stretch: bool,
    sources: list[str] | None = None,
) -> tuple[list[JobMatch], CollectionReport]:
    requested_sources = [source for source in (sources or SOURCE_OPTIONS) if source in SOURCE_OPTIONS]
    combined, source_reports = collect_from_sources(requested_sources)

    deduped: dict[tuple[str, str, str], JobMatch] = {}
    filtered_age = 0
    filtered_score = 0
    filtered_stretch = 0
    dedup_collisions = 0

    for item in combined:
        age = days_old(item.freshness)
        if age is not None and age > max_age_days:
            filtered_age += 1
            continue
        if item.score < min_score:
            filtered_score += 1
            continue
        if not include_stretch and item.fit == "Stretch":
            filtered_stretch += 1
            continue

        normalized_link = normalize_url(item.url)
        url_or_context = normalized_link or normalize(item.remote_policy).lower() or "no-url"
        key = (item.title.lower(), item.company.lower(), url_or_context)
        current = deduped.get(key)
        if current is None:
            deduped[key] = item
            continue
        dedup_collisions += 1
        if item.score > current.score:
            deduped[key] = item

    matches = sorted(
        deduped.values(),
        key=lambda row: (-row.score, row.freshness, row.title.lower()),
    )
    report = CollectionReport(
        sources=source_reports,
        raw_total=len(combined),
        filtered_age=filtered_age,
        filtered_score=filtered_score,
        filtered_stretch=filtered_stretch,
        dedup_collisions=dedup_collisions,
        deduped_total=len(deduped),
    )
    return matches[:limit], report


def write_table(path: Path, title: str, matches: list[JobMatch], report: CollectionReport | None = None) -> Path:
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"# {title}\n\n")
        fh.write(f"Generated: {datetime.now().isoformat(timespec='minutes')}\n\n")
        fh.write("| Role | Company | Source | Remote | Freshness | Fit | Score | Missing skills | Match notes |\n")
        fh.write("|---|---|---|---|---|---|---:|---|---|\n")
        for item in matches:
            safe_title = item.title.replace("|", "/")
            safe_company = item.company.replace("|", "/")
            safe_missing = (item.missing_skills or "—").replace("|", "/")
            safe_note = item.fit_notes.replace("|", "/")
            fh.write(
                f"| [{safe_title}]({item.url}) | {safe_company} | {item.source} | {item.remote_policy} | {item.freshness} | {item.fit} | {item.score} | {safe_missing} | {safe_note} |\n"
            )

        if report is not None:
            fh.write("\n## Source Health\n\n")
            fh.write("| Source | Key | Collected | Error |\n")
            fh.write("|---|---|---:|---|\n")
            for source_report in report.sources:
                safe_error = (source_report.error or "—").replace("|", "/")
                fh.write(
                    f"| {source_report.label} | {source_report.key} | {source_report.collected} | {safe_error} |\n"
                )

            fh.write("\n## Filter Summary\n\n")
            fh.write(f"- Raw collected listings: {report.raw_total}\n")
            fh.write(f"- Filtered by age: {report.filtered_age}\n")
            fh.write(f"- Filtered by score: {report.filtered_score}\n")
            fh.write(f"- Filtered stretch roles: {report.filtered_stretch}\n")
            fh.write(f"- Dedup collisions: {report.dedup_collisions}\n")
            fh.write(f"- Unique listings after dedup: {report.deduped_total}\n")
    return path


def write_outputs(
    strict_matches: list[JobMatch], broad_matches: list[JobMatch], report: CollectionReport | None = None
) -> tuple[Path, Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    csv_path = OUTPUT_DIR / f"job_matches_{stamp}.csv"
    strict_md_path = OUTPUT_DIR / "job_matches_latest.md"
    broad_md_path = BROAD_MATCHES_PATH

    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "title",
                "company",
                "source",
                "remote_policy",
                "freshness",
                "fit",
                "score",
                "matched_keywords",
                "missing_skills",
                "fit_notes",
                "url",
            ],
        )
        writer.writeheader()
        for item in broad_matches:
            writer.writerow(item.__dict__)

    write_table(strict_md_path, "Latest Job Matches - Strict Shortlist", strict_matches, report)
    write_table(broad_md_path, "Broad Job Discovery List", broad_matches, report)
    return csv_path, strict_md_path, broad_md_path


def write_application_notes(matches: list[JobMatch]) -> Path:
    with NOTES_PATH.open("w", encoding="utf-8") as fh:
        fh.write("# Application Notes\n\n")
        fh.write(f"Generated: {datetime.now().isoformat(timespec='minutes')}\n\n")
        for item in matches:
            fh.write(f"## {item.company} — {item.title}\n\n")
            fh.write(f"- Source: {item.source}\n")
            fh.write(f"- Remote: {item.remote_policy}\n")
            fh.write(f"- Fit: {item.fit} ({item.score})\n")
            fh.write(f"- Link: {item.url}\n")
            fh.write(f"- Why it fits: {item.fit_notes}\n")
            fh.write(f"- Missing skills to watch: {item.missing_skills or 'None flagged'}\n")
            fh.write("- CV tailoring focus:\n")
            for point in tailoring_points(item):
                fh.write(f"  - {point}\n")
            fh.write(f"- Recommended next step: {next_step_for_fit(item.fit)}\n\n")
    return NOTES_PATH


def load_existing_checks() -> dict[tuple[str, str], bool]:
    checked: dict[tuple[str, str], bool] = {}
    if not CHECKLIST_PATH.exists():
        return checked

    for line in CHECKLIST_PATH.read_text(encoding="utf-8").splitlines():
        match = re.match(r"- \[( |x|X)\] (.+?) — (.+)$", line.strip())
        if not match:
            continue
        is_checked = match.group(1).lower() == "x"
        company = normalize(match.group(2))
        title = normalize(match.group(3))
        checked[(company.lower(), title.lower())] = is_checked
    return checked


def write_selected_jobs_checklist(matches: list[JobMatch]) -> Path:
    existing_checks = load_existing_checks()
    priority = [item for item in matches if item.fit == "Strong"]
    later = [item for item in matches if item.fit == "Medium"]

    with CHECKLIST_PATH.open("w", encoding="utf-8") as fh:
        fh.write("# Selected Jobs Checklist\n\n")
        fh.write("Check items to keep for later applying or active targeting.\n\n")
        fh.write(f"Updated: {datetime.now().isoformat(timespec='minutes')}\n\n")

        fh.write("## Priority Apply\n\n")
        for item in priority:
            key = (item.company.lower(), item.title.lower())
            box = "x" if existing_checks.get(key, False) else " "
            fh.write(f"- [{box}] {item.company} — {item.title}\n")
            fh.write(f"  - Fit: {item.fit} ({item.score}) | Remote: {item.remote_policy} | Source: {item.source}\n")
            fh.write(f"  - Link: {item.url}\n")
            fh.write(f"  - Note: {item.fit_notes}\n")

        fh.write("\n## Review Later\n\n")
        for item in later:
            key = (item.company.lower(), item.title.lower())
            box = "x" if existing_checks.get(key, False) else " "
            fh.write(f"- [{box}] {item.company} — {item.title}\n")
            fh.write(f"  - Fit: {item.fit} ({item.score}) | Remote: {item.remote_policy} | Source: {item.source}\n")
            fh.write(f"  - Link: {item.url}\n")
            fh.write(f"  - Note: {item.fit_notes}\n")

    return CHECKLIST_PATH


def sync_application_api(
    matches: list[JobMatch],
    api_base_url: str,
    api_key: str = "",
    max_attempts: int = 3,
    base_backoff_seconds: float = 0.5,
) -> tuple[int, list[ApiUpsertFailure]]:
    today = datetime.now().strftime("%Y-%m-%d")
    created_or_updated = 0
    failed: list[ApiUpsertFailure] = []
    endpoint = api_base_url.rstrip("/") + "/applications/upsert"
    extra_headers: dict[str, str] = {}
    if api_key:
        extra_headers["X-API-Key"] = api_key

    for item in matches:
        payload = {
            "selected": "no",
            "date_found": today,
            "date_applied": "",
            "company": item.company,
            "role": item.title,
            "location": item.remote_policy,
            "source": item.source,
            "remote_type": item.remote_policy,
            "fit": item.fit,
            "fit_score": item.score,
            "link": item.url,
            "status": "To review",
            "next_step": next_step_for_fit(item.fit),
            "follow_up_date": "",
            "resume_ref": "",
            "cover_letter_ref": "",
            "match_profile": ACTIVE_PROFILE,
            "first_seen_at": today,
            "last_seen_at": today,
            "listing_fingerprint": hashlib.sha256(
                f"{item.company}|{item.title}|{item.url}|{item.source}|{item.remote_policy}|{item.freshness}|{item.fit_notes}".encode(
                    "utf-8"
                )
            ).hexdigest(),
            "change_note": "",
            "notes": item.fit_notes,
        }
        attempt = 0
        while attempt < max_attempts:
            try:
                post_json(endpoint, payload, extra_headers=extra_headers)
                created_or_updated += 1
                break
            except Exception as exc:
                status_code, error_type, is_transient = classify_upsert_exception(exc)
                attempt += 1

                if is_transient and attempt < max_attempts:
                    sleep_seconds = base_backoff_seconds * (2 ** (attempt - 1))
                    time.sleep(sleep_seconds)
                    continue

                failed.append(
                    ApiUpsertFailure(
                        company=item.company,
                        title=item.title,
                        source=item.source,
                        status_code=status_code,
                        error_type=error_type,
                        message=str(exc),
                    )
                )
                break

    return created_or_updated, failed


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch remote data-engineering jobs aligned with the selected profile.")
    parser.add_argument("--cv-path", required=True, help="Path to CV file used to infer available skills.")
    parser.add_argument("--limit", type=int, default=40, help="Maximum number of rows to keep in the strict shortlist.")
    parser.add_argument("--min-score", type=int, default=7, help="Minimum fit score for the strict shortlist.")
    parser.add_argument(
        "--max-age-days", type=int, default=45, help="Maximum listing age to keep when a date is available."
    )
    parser.add_argument(
        "--include-stretch", action="store_true", help="Include low-fit stretch roles in the strict shortlist."
    )
    parser.add_argument(
        "--api-base-url",
        default=DEFAULT_API_BASE_URL,
        help="Base URL for the Job Application Insights API, e.g. http://127.0.0.1:8000",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to write output files (md, csv). Defaults to applications/tracker.",
    )
    parser.add_argument(
        "--profile",
        default="de",
        choices=["de", "swe", "other"],
        help="Search profile: de (data engineering), swe (software engineering), other (broader adjacent).",
    )
    parser.add_argument(
        "--sources",
        default=",".join(SOURCE_OPTIONS),
        help=(
            "Comma-separated source keys to query. "
            "Options: wwr, working_nomads, remoteok, remotive, arbeitnow, jobicy"
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print source-by-source collection diagnostics and filtering summary.",
    )
    args = parser.parse_args()

    global OUTPUT_DIR, TRACKER_PATH, NOTES_PATH, CHECKLIST_PATH, BROAD_MATCHES_PATH
    if args.output_dir:
        OUTPUT_DIR = Path(args.output_dir).resolve()
        TRACKER_PATH = OUTPUT_DIR / "job_applications.csv"
        NOTES_PATH = OUTPUT_DIR / "application_notes_latest.md"
        CHECKLIST_PATH = OUTPUT_DIR / "selected_jobs.md"
        BROAD_MATCHES_PATH = OUTPUT_DIR / "job_matches_broad.md"

    cv_path = Path(args.cv_path)
    if not cv_path.is_absolute():
        cv_path = (REPO_ROOT / cv_path).resolve()
    if not cv_path.exists():
        print(f"CV file not found: {cv_path}")
        return 2

    global OWNED_SKILLS, SEARCH_TERMS, ACTIVE_PROFILE
    OWNED_SKILLS = extract_owned_skills_from_cv(cv_path)
    if not OWNED_SKILLS:
        print(f"No recognizable skills found in CV: {cv_path}")
        return 2
    ACTIVE_PROFILE = args.profile
    SEARCH_TERMS = infer_search_terms_for_profile(OWNED_SKILLS, ACTIVE_PROFILE)

    if not DEFAULT_API_WRITE_KEY:
        print("Warning: JOB_SEARCH_WRITE_API_KEY is not set; API upserts will likely fail with 401 Unauthorized.")
    elif len(DEFAULT_API_WRITE_KEY.strip()) < 8:
        print("Warning: JOB_SEARCH_WRITE_API_KEY looks unusually short; verify the value if API upserts fail.")

    requested_sources = [part.strip().lower() for part in str(args.sources).split(",") if part.strip()]
    requested_sources = [source for source in requested_sources if source in SOURCE_OPTIONS]
    if not requested_sources:
        requested_sources = SOURCE_OPTIONS.copy()

    broad_matches, collection_report = collect_matches(
        limit=max(args.limit * 3, 120),
        min_score=1,
        max_age_days=120,
        include_stretch=True,
        sources=requested_sources,
    )
    strict_matches = [
        item
        for item in broad_matches
        if item.score >= args.min_score and (args.include_stretch or item.fit != "Stretch")
    ][: args.limit]

    if not broad_matches:
        source_errors = [report for report in collection_report.sources if report.error]
        if source_errors:
            print("Source errors:")
            for report in source_errors:
                print(f"- {report.label} ({report.key}): {report.error}")
        print("No matches found this run.")
        return 1

    csv_path, md_path, broad_md_path = write_outputs(strict_matches, broad_matches, collection_report)
    notes_path = write_application_notes(strict_matches)
    synced_count, failed_rows = sync_application_api(strict_matches, args.api_base_url, DEFAULT_API_WRITE_KEY)
    checklist_path = write_selected_jobs_checklist(strict_matches)

    source_errors = [report for report in collection_report.sources if report.error]
    if args.verbose or source_errors:
        print("Source diagnostics:")
        for report in collection_report.sources:
            status = f"error={report.error}" if report.error else f"collected={report.collected}"
            print(f"- {report.label} ({report.key}): {status}")
    if args.verbose:
        print("Filter summary:")
        print(f"- raw_total={collection_report.raw_total}")
        print(f"- filtered_age={collection_report.filtered_age}")
        print(f"- filtered_score={collection_report.filtered_score}")
        print(f"- filtered_stretch={collection_report.filtered_stretch}")
        print(f"- dedup_collisions={collection_report.dedup_collisions}")
        print(f"- deduped_total={collection_report.deduped_total}")

    print(f"Saved {len(broad_matches)} total matches to: {csv_path}")
    print(f"Updated strict shortlist: {md_path}")
    print(f"Updated broad discovery list: {broad_md_path}")
    print(f"Updated notes: {notes_path}")
    print(f"Updated checklist: {checklist_path}")
    print(f"API upserts sent: {synced_count}")
    if failed_rows:
        print(f"API upserts failed: {len(failed_rows)}")
        status_counts: dict[str, int] = {}
        for row in failed_rows:
            status_label = str(row.status_code) if row.status_code is not None else row.error_type
            status_counts[status_label] = status_counts.get(status_label, 0) + 1

        if args.verbose:
            print("API upsert failures by status/error:")
            for status_label in sorted(status_counts):
                print(f"- {status_label}: {status_counts[status_label]}")

        if args.verbose:
            print("API upsert failure samples:")
            for row in failed_rows[:5]:
                status_label = str(row.status_code) if row.status_code is not None else row.error_type
                print(f"- {row.company} | {row.title} | {row.source} | {status_label} | {row.message}")

        unauthorized_count = status_counts.get("401", 0)
        if unauthorized_count:
            print(
                "Warning: Received 401 Unauthorized during API upserts. Check JOB_SEARCH_WRITE_API_KEY and backend key settings."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
