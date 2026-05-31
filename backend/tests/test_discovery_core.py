import json
import sys
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_APP_ROOT = Path(__file__).resolve().parents[2]
_ENGINE_ROOT = _APP_ROOT.parent / "job-discovery-engine" / "src"
for path in (str(_ENGINE_ROOT), str(_APP_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import job_discovery_engine as discovery_package  # noqa: E402
from job_discovery_engine import api as discovery_api  # noqa: E402
from job_discovery_engine import config as discovery_config  # noqa: E402
from job_discovery_engine.models import (  # noqa: E402
    CollectionReport,
    DiscoveryContext,
    JobMatch,
    SourceRunReport,
)
from job_discovery_engine.pipeline import DiscoveryRunOptions, run_discovery_pipeline  # noqa: E402
from job_discovery_engine.rerankers import LLMRerankReport  # noqa: E402
from job_discovery_engine.scoring import is_relevant, score_match  # noqa: E402
from job_discovery_engine.sources import collect_remotive  # noqa: E402


def test_public_api_surface_is_frozen() -> None:
    assert discovery_package.__all__ == [
        "DiscoveryContext",
        "DiscoveryRunOptions",
        "DiscoveryRunResult",
        "DiscoveryRunWarnings",
        "run_discovery_pipeline",
    ]
    assert discovery_api.__all__ == [
        "DiscoveryRunOptions",
        "DiscoveryRunResult",
        "DiscoveryRunWarnings",
        "run_discovery_pipeline",
    ]


def test_public_dataclass_shapes_are_stable() -> None:
    assert [field.name for field in fields(DiscoveryContext)] == ["profile", "owned_skills", "search_terms"]
    assert [field.name for field in fields(DiscoveryRunOptions)] == [
        "cv_path",
        "limit",
        "min_score",
        "max_age_days",
        "include_stretch",
        "profile",
        "sources",
        "salary_min_usd",
        "timezones",
        "seniority",
        "use_outcome_priors",
        "prior_lookback_days",
        "source_prior_weight",
        "role_prior_weight",
        "use_llm_reranker",
        "llm_top_n",
        "llm_weight",
        "llm_model",
        "llm_api_base_url",
        "llm_dry_run",
        "llm_max_calls",
        "llm_max_input_chars",
        "llm_max_retries",
        "llm_retry_backoff_seconds",
        "llm_timeout_seconds",
        "api_base_url",
        "api_write_key",
        "output_dir",
    ]
    assert [field.name for field in fields(discovery_api.DiscoveryRunResult)] == [
        "context",
        "strict_matches",
        "broad_matches",
        "collection_report",
        "llm_report",
        "csv_path",
        "strict_md_path",
        "broad_md_path",
        "notes_path",
        "checklist_path",
        "synced_count",
        "failed_rows",
    ]


def _sample_match() -> JobMatch:
    return JobMatch(
        title="Backend Engineer",
        company="Acme",
        source="Remotive",
        remote_policy="Remote",
        freshness="2026-05-20",
        fit="Strong",
        score=14,
        url="https://example.com/jobs/1",
        details_text="Python SQL FastAPI",
        matched_keywords="Python, SQL",
        missing_skills="dbt",
        fit_notes="Direct overlap on Python and SQL.",
    )


def test_explicit_context_overrides_globals() -> None:
    original_profile = discovery_config.ACTIVE_PROFILE
    original_owned_skills = set(discovery_config.OWNED_SKILLS)
    try:
        discovery_config.ACTIVE_PROFILE = "de"
        discovery_config.OWNED_SKILLS.clear()

        swe_context = DiscoveryContext(profile="swe", owned_skills={"python"}, search_terms=["backend engineer"])
        de_context = DiscoveryContext(profile="de", owned_skills={"python"}, search_terms=["data engineer"])

        assert is_relevant("Backend Engineer", "", context=swe_context)
        assert not is_relevant("Backend Engineer", "", context=de_context)

        context_score = score_match("Data Engineer", "Python SQL", context=DiscoveryContext(
            profile="de",
            owned_skills={"python"},
            search_terms=[],
        ))
        fallback_score = score_match("Data Engineer", "Python SQL")

        assert context_score > fallback_score
    finally:
        discovery_config.ACTIVE_PROFILE = original_profile
        discovery_config.OWNED_SKILLS.clear()
        discovery_config.OWNED_SKILLS.update(original_owned_skills)


def test_collect_remotive_uses_context_search_terms(monkeypatch) -> None:
    calls: list[str] = []

    def fake_fetch_text(url: str, timeout: int = 25) -> str:
        calls.append(url)
        return json.dumps(
            {
                "jobs": [
                    {
                        "title": "Backend Engineer",
                        "company_name": "Acme",
                        "description": "Python FastAPI SQL",
                        "candidate_required_location": "Remote",
                        "publication_date": "2026-05-20",
                        "url": "https://example.com/jobs/1",
                    }
                ]
            }
        )

    monkeypatch.setattr("job_discovery_engine.sources.fetch_text", fake_fetch_text)

    context = DiscoveryContext(
        profile="swe",
        owned_skills={"python"},
        search_terms=["backend engineer", "platform engineer"],
    )
    matches = collect_remotive(context)

    assert len(calls) == 2
    assert len(matches) == 1
    assert matches[0].company == "Acme"


def test_run_discovery_pipeline_public_api(monkeypatch, tmp_path: Path) -> None:
    cv_path = tmp_path / "cv.tex"
    cv_path.write_text("Python SQL FastAPI", encoding="utf-8")

    sample_match = _sample_match()
    collection_report = CollectionReport(
        sources=[SourceRunReport(key="remotive", label="Remotive", collected=1)],
        raw_total=1,
        filtered_age=0,
        filtered_score=0,
        filtered_stretch=0,
        filtered_salary=0,
        filtered_timezone=0,
        filtered_seniority=0,
        dedup_collisions=0,
        deduped_total=1,
    )
    llm_report = LLMRerankReport(
        adjusted=0,
        attempted=0,
        planned_calls=0,
        used_input_chars=0,
        dry_run=False,
        warnings=[],
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr("job_discovery_engine.pipeline.shared.extract_owned_skills_from_cv", lambda path: {"python", "sql"})
    monkeypatch.setattr("job_discovery_engine.pipeline.shared.infer_search_terms_for_profile", lambda owned, profile: ["backend engineer"])

    def fake_collect_matches(*, context: DiscoveryContext, **kwargs: object):
        captured["context"] = context
        return [sample_match], collection_report

    monkeypatch.setattr("job_discovery_engine.pipeline.collect_matches", fake_collect_matches)
    monkeypatch.setattr("job_discovery_engine.pipeline.rerankers.apply_llm_reranker", lambda matches, **kwargs: (matches, llm_report))
    monkeypatch.setattr(
        "job_discovery_engine.pipeline.outputs.write_outputs",
        lambda strict_matches, broad_matches, report=None, output_dir=None: (
            tmp_path / "job_matches.csv",
            tmp_path / "job_matches_latest.md",
            tmp_path / "job_matches_broad.md",
        ),
    )
    monkeypatch.setattr("job_discovery_engine.pipeline.outputs.write_application_notes", lambda matches, output_dir=None: tmp_path / "application_notes_latest.md")
    monkeypatch.setattr("job_discovery_engine.pipeline.outputs.sync_application_api", lambda matches, base_url, api_key, match_profile: (1, []))
    monkeypatch.setattr("job_discovery_engine.pipeline.outputs.write_selected_jobs_checklist", lambda matches, output_dir=None: tmp_path / "selected_jobs.md")

    options = DiscoveryRunOptions(
        cv_path=cv_path,
        profile="de",
        api_base_url="http://127.0.0.1:8000",
        api_write_key="test-key",
        sources=["remotive"],
    )
    result, warnings = run_discovery_pipeline(options)

    assert result.context.profile == "de"
    assert captured["context"].profile == "de"
    assert result.strict_matches == [sample_match]
    assert result.synced_count == 1
    assert warnings.messages == []
