from __future__ import annotations

import csv
import hashlib
from datetime import datetime
from pathlib import Path
import re
import time

from shared import (
    ApiUpsertFailure,
    CollectionReport,
    DEFAULT_API_WRITE_KEY,
    JobMatch,
    classify_upsert_exception,
    next_step_for_fit,
    post_json,
    tailoring_points,
)

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parent if (APP_ROOT.parent / "applications").exists() else APP_ROOT
OUTPUT_DIR = REPO_ROOT / "applications" / "tracker"
TRACKER_PATH = OUTPUT_DIR / "job_applications.csv"
NOTES_PATH = OUTPUT_DIR / "application_notes_latest.md"
CHECKLIST_PATH = OUTPUT_DIR / "selected_jobs.md"
BROAD_MATCHES_PATH = OUTPUT_DIR / "job_matches_broad.md"


def configure_output_dir(output_dir: Path | None) -> None:
    global OUTPUT_DIR, TRACKER_PATH, NOTES_PATH, CHECKLIST_PATH, BROAD_MATCHES_PATH
    if output_dir is None:
        return
    OUTPUT_DIR = output_dir.resolve()
    TRACKER_PATH = OUTPUT_DIR / "job_applications.csv"
    NOTES_PATH = OUTPUT_DIR / "application_notes_latest.md"
    CHECKLIST_PATH = OUTPUT_DIR / "selected_jobs.md"
    BROAD_MATCHES_PATH = OUTPUT_DIR / "job_matches_broad.md"


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
        company = match.group(2).strip()
        title = match.group(3).strip()
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
            "match_profile": "de",
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
