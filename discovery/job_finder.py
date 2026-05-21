from __future__ import annotations

import argparse
from pathlib import Path

import job_finder_outputs as outputs
import job_finder_shared as shared
from job_finder_shared import DEFAULT_API_BASE_URL, DEFAULT_API_WRITE_KEY
from job_finder_sources import collect_matches

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parent if (APP_ROOT.parent / "applications").exists() else APP_ROOT


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
        default=",".join(shared.SOURCE_OPTIONS),
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

    if args.output_dir:
        outputs.configure_output_dir(Path(args.output_dir).resolve())

    cv_path = Path(args.cv_path)
    if not cv_path.is_absolute():
        cv_path = (REPO_ROOT / cv_path).resolve()
    if not cv_path.exists():
        print(f"CV file not found: {cv_path}")
        return 2

    shared.OWNED_SKILLS = shared.extract_owned_skills_from_cv(cv_path)
    if not shared.OWNED_SKILLS:
        print(f"No recognizable skills found in CV: {cv_path}")
        return 2
    shared.ACTIVE_PROFILE = args.profile
    shared.SEARCH_TERMS = shared.infer_search_terms_for_profile(shared.OWNED_SKILLS, shared.ACTIVE_PROFILE)

    if not DEFAULT_API_WRITE_KEY:
        print("Warning: JOB_SEARCH_WRITE_API_KEY is not set; API upserts will likely fail with 401 Unauthorized.")
    elif len(DEFAULT_API_WRITE_KEY.strip()) < 8:
        print("Warning: JOB_SEARCH_WRITE_API_KEY looks unusually short; verify the value if API upserts fail.")

    requested_sources = [part.strip().lower() for part in str(args.sources).split(",") if part.strip()]
    requested_sources = [source for source in requested_sources if source in shared.SOURCE_OPTIONS]
    if not requested_sources:
        requested_sources = shared.SOURCE_OPTIONS.copy()

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

    csv_path, md_path, broad_md_path = outputs.write_outputs(strict_matches, broad_matches, collection_report)
    notes_path = outputs.write_application_notes(strict_matches)
    synced_count, failed_rows = outputs.sync_application_api(strict_matches, args.api_base_url, DEFAULT_API_WRITE_KEY)
    checklist_path = outputs.write_selected_jobs_checklist(strict_matches)

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
