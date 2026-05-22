from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

from shared import (
    ARBEITNOW_API,
    JOBICY_FEED,
    REMOTIVE_API,
    REMOTEOK_API,
    SEARCH_TERMS,
    SOURCE_OPTIONS,
    WWR_FEEDS,
    CollectionReport,
    JobMatch,
    SourceAdapter,
    SourceRunReport,
    build_job_match,
    days_old,
    fetch_text,
    fit_label,
    infer_search_terms_for_profile,
    is_relevant,
    matches_salary_requirement,
    matches_seniority,
    matches_timezone,
    normalize,
    normalize_url,
    parse_date,
    parse_remote_policy,
    score_match,
    split_company_and_title,
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
    data = json.loads(fetch_text("https://www.workingnomads.com/api/exposed_jobs/"))

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
    salary_min_usd: int | None = None,
    allowed_timezones: list[str] | None = None,
    seniority: str | None = None,
    sources: list[str] | None = None,
) -> tuple[list[JobMatch], CollectionReport]:
    requested_sources = [source for source in (sources or SOURCE_OPTIONS) if source in SOURCE_OPTIONS]
    combined, source_reports = collect_from_sources(requested_sources)

    deduped: dict[tuple[str, str, str], JobMatch] = {}
    filtered_age = 0
    filtered_score = 0
    filtered_stretch = 0
    filtered_salary = 0
    filtered_timezone = 0
    filtered_seniority = 0
    dedup_collisions = 0

    for item in combined:
        details = item.details_text
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
        if not matches_salary_requirement(item.title, details, salary_min_usd):
            filtered_salary += 1
            continue
        if not matches_timezone(item.remote_policy, details, allowed_timezones):
            filtered_timezone += 1
            continue
        if not matches_seniority(item.title, details, seniority):
            filtered_seniority += 1
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
        filtered_salary=filtered_salary,
        filtered_timezone=filtered_timezone,
        filtered_seniority=filtered_seniority,
        dedup_collisions=dedup_collisions,
        deduped_total=len(deduped),
    )
    return matches[:limit], report
