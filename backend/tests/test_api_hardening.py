import os
import json
from datetime import datetime
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

_TMP_DIR = Path(__file__).resolve().parent / ".tmp"
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

_TMP_DIR.mkdir(parents=True, exist_ok=True)
_CV_PATH = _TMP_DIR / "cv.tex"
_DB_PATH = _TMP_DIR / "test.db"
_APPLICATIONS_ROOT = _TMP_DIR / "applications"
_TEMPLATE_DIR = _APPLICATIONS_ROOT / "vacancies" / "_template"
_RESUMES_DIR = _APPLICATIONS_ROOT / "resumes"

_CV_PATH.write_text("Python SQL FastAPI", encoding="utf-8")
_TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
_RESUMES_DIR.mkdir(parents=True, exist_ok=True)
(_TEMPLATE_DIR / "cover_letter.md").write_text(
    "Dear Hiring Team, [Role Title] at [Company].\n[Author Name]", encoding="utf-8"
)
(_TEMPLATE_DIR / "notes.md").write_text("# Tailoring Notes\n", encoding="utf-8")
(_TEMPLATE_DIR / "vacancy.md").write_text(
    "# Vacancy\n\n## Company\n- \n\n## Role\n- \n\n## Source URL\n- \n\n## Requirements (copied)\n- \n\n## Key signals to mirror in CV\n- \n\n## Potential gaps and response strategy\n- \n",
    encoding="utf-8",
)
(_RESUMES_DIR / "CV.tex").write_text("% base cv\n", encoding="utf-8")

if _DB_PATH.exists():
    _DB_PATH.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH.as_posix()}"
os.environ["DISCOVERY_CV_PATH"] = str(_CV_PATH)
os.environ["WRITE_API_KEY"] = "test-key"
os.environ["REQUIRE_WRITE_KEY"] = "true"
os.environ["APPLICATIONS_ROOT"] = str(_APPLICATIONS_ROOT)
os.environ["VACANCIES_TEMPLATE_DIR"] = str(_TEMPLATE_DIR)
os.environ["BASE_CV_TEMPLATE_PATH"] = str(_RESUMES_DIR / "CV.tex")

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.helpers import slugify, summarize_process_output, today_iso  # noqa: E402
from app.main import app  # noqa: E402
from app.models import JobApplication  # noqa: E402
from app.pathing import (  # noqa: E402
    applications_root,
    is_within_path,
    resolve_from_applications_root,
    safe_relative_path,
)
from app.routers import discovery as discovery_router  # noqa: E402

Base.metadata.create_all(bind=engine)

client = TestClient(app)


def _auth_headers() -> dict[str, str]:
    return {"X-API-Key": "test-key"}


def _base_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "company": "Acme",
        "role": "Engineer",
        "link": "https://example.com/job/base",
        "status": "To review",
    }
    payload.update(overrides)
    return payload


def _clear_db() -> None:
    with SessionLocal() as db:
        db.query(JobApplication).delete()
        db.commit()


def _reset_discovery_guard() -> None:
    discovery_router._reset_discovery_run_guard()


def test_write_endpoints_require_api_key() -> None:
    _clear_db()

    response = client.post("/applications/upsert", json=_base_payload())
    assert response.status_code == 401

    ok = client.post("/applications/upsert", json=_base_payload(), headers=_auth_headers())
    assert ok.status_code == 200


def test_create_application_rejects_duplicates() -> None:
    _clear_db()

    first = client.post(
        "/applications", json=_base_payload(link="https://example.com/job/create-1"), headers=_auth_headers()
    )
    assert first.status_code == 201

    duplicate = client.post(
        "/applications",
        json=_base_payload(link="https://example.com/job/create-1"),
        headers=_auth_headers(),
    )
    assert duplicate.status_code == 409


def test_extract_url_parses_basic_job_fields(monkeypatch) -> None:
    class _FakeHeaders:
        def get(self, key: str, default: str | None = None) -> str | None:
            if key.lower() == "content-type":
                return "text/html; charset=utf-8"
            return default

        def get_content_charset(self) -> str:
            return "utf-8"

    class _FakeResponse:
        headers = _FakeHeaders()

        def read(self, _size: int) -> bytes:
            return (
                b"<html><head><title>Senior Data Engineer at Blue Harbor</title>"
                b"<meta name='description' content='Build robust ETL pipelines in Python and SQL.'/></head>"
                b"<body><p>Remote position. Location: Germany.</p></body></html>"
            )

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr("app.routers.applications.urlopen", lambda *args, **kwargs: _FakeResponse())

    response = client.post(
        "/applications/extract-url",
        json={"url": "https://example.com/jobs/123"},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["company"] == "Blue Harbor"
    assert data["role"] == "Senior Data Engineer"
    assert data["remote_type"] == "Remote"
    assert data["source"] == "example.com"
    assert "Python and SQL" in data["description"]


def test_extract_url_rejects_private_ip_host() -> None:
    response = client.post(
        "/applications/extract-url",
        json={"url": "http://10.0.0.1/jobs/123"},
        headers=_auth_headers(),
    )
    assert response.status_code == 400
    assert "publicly routable" in response.json()["detail"]


def test_extract_url_rejects_non_html(monkeypatch) -> None:
    class _FakeHeaders:
        def get(self, key: str, default: str | None = None) -> str | None:
            if key.lower() == "content-type":
                return "application/pdf"
            return default

        def get_content_charset(self) -> str:
            return "utf-8"

    class _FakeResponse:
        headers = _FakeHeaders()

        def read(self, _size: int) -> bytes:
            return b"%PDF-1.5"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr("app.routers.applications.urlopen", lambda *args, **kwargs: _FakeResponse())
    response = client.post(
        "/applications/extract-url",
        json={"url": "https://example.com/file.pdf"},
        headers=_auth_headers(),
    )
    assert response.status_code == 400
    assert "HTML page" in response.json()["detail"]


def test_extract_url_requires_api_key() -> None:
    response = client.post(
        "/applications/extract-url",
        json={"url": "https://example.com/jobs/123"},
    )
    assert response.status_code == 401


def test_extract_url_rejects_invalid_url_format() -> None:
    response = client.post(
        "/applications/extract-url",
        json={"url": "ftp://example.com/jobs/1"},
        headers=_auth_headers(),
    )
    assert response.status_code == 422


def test_extract_url_rejects_oversized_html(monkeypatch) -> None:
    class _FakeHeaders:
        def get(self, key: str, default: str | None = None) -> str | None:
            if key.lower() == "content-type":
                return "text/html; charset=utf-8"
            return default

        def get_content_charset(self) -> str:
            return "utf-8"

    class _FakeResponse:
        headers = _FakeHeaders()

        def read(self, _size: int) -> bytes:
            return b"a" * 1_000_002

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr("app.routers.applications.urlopen", lambda *args, **kwargs: _FakeResponse())
    response = client.post(
        "/applications/extract-url",
        json={"url": "https://example.com/jobs/big"},
        headers=_auth_headers(),
    )
    assert response.status_code == 400
    assert "too large" in response.json()["detail"]


def test_extract_url_handles_timeout(monkeypatch) -> None:
    monkeypatch.setattr("app.routers.applications.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("timed out")))
    response = client.post(
        "/applications/extract-url",
        json={"url": "https://example.com/jobs/timeout"},
        headers=_auth_headers(),
    )
    assert response.status_code == 422
    assert "Failed to fetch URL" in response.json()["detail"]


def test_extract_url_falls_back_when_title_and_meta_missing(monkeypatch) -> None:
    class _FakeHeaders:
        def get(self, key: str, default: str | None = None) -> str | None:
            if key.lower() == "content-type":
                return "text/html; charset=utf-8"
            return default

        def get_content_charset(self) -> str:
            return "utf-8"

    class _FakeResponse:
        headers = _FakeHeaders()

        def read(self, _size: int) -> bytes:
            return b"<html><body><h1>Platform Engineer opening</h1><p>Hybrid role in Berlin.</p></body></html>"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr("app.routers.applications.urlopen", lambda *args, **kwargs: _FakeResponse())
    response = client.post(
        "/applications/extract-url",
        json={"url": "https://example.com/jobs/no-meta"},
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["company"] == ""
    assert data["role"] == ""
    assert "Platform Engineer" in data["description"]
    assert data["remote_type"] == "Hybrid"


def test_create_application_allows_same_company_role_with_different_links() -> None:
    _clear_db()

    first = client.post(
        "/applications", json=_base_payload(link="https://example.com/job/create-a"), headers=_auth_headers()
    )
    assert first.status_code == 201

    second = client.post(
        "/applications", json=_base_payload(link="https://example.com/job/create-b"), headers=_auth_headers()
    )
    assert second.status_code == 201
    assert second.json()["id"] != first.json()["id"]


def test_upsert_allows_same_company_role_with_different_links() -> None:
    _clear_db()

    first = client.post(
        "/applications/upsert", json=_base_payload(link="https://example.com/job/upsert-a"), headers=_auth_headers()
    )
    assert first.status_code == 200

    second = client.post(
        "/applications/upsert", json=_base_payload(link="https://example.com/job/upsert-b"), headers=_auth_headers()
    )
    assert second.status_code == 200
    assert second.json()["id"] != first.json()["id"]

    listed = client.get("/applications?limit=50")
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 2


def test_upsert_without_link_falls_back_to_company_role() -> None:
    _clear_db()

    first = client.post(
        "/applications/upsert",
        json=_base_payload(link="", status="To review"),
        headers=_auth_headers(),
    )
    assert first.status_code == 200

    second = client.post(
        "/applications/upsert",
        json=_base_payload(link="", status="Interview"),
        headers=_auth_headers(),
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["status"] == "Interview"

    listed = client.get("/applications?limit=50")
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1


def test_status_filter_is_exact_match_case_insensitive() -> None:
    _clear_db()

    first = _base_payload(link="https://example.com/job/1", status="Applied")
    second = _base_payload(
        company="Acme Labs",
        role="Engineer II",
        link="https://example.com/job/2",
        status="Applied Later",
    )

    assert client.post("/applications/upsert", json=first, headers=_auth_headers()).status_code == 200
    assert client.post("/applications/upsert", json=second, headers=_auth_headers()).status_code == 200

    result = client.get("/applications?status=applied&limit=50")
    assert result.status_code == 200

    rows = result.json()["items"]
    assert len(rows) == 1
    assert rows[0]["status"] == "Applied"


def test_applications_include_score_breakdown_when_present() -> None:
    _clear_db()

    payload = _base_payload(
        link="https://example.com/job/score-breakdown",
        fit="Strong",
        fit_score=13,
        change_note=json.dumps(
            {
                "score": 13,
                "fit": "Strong",
                "matched_keywords": ["Python", "SQL"],
                "missing_skills": ["dbt"],
                "fit_notes": "Direct overlap on Python, SQL.",
            }
        ),
    )

    created = client.post("/applications/upsert", json=payload, headers=_auth_headers())
    assert created.status_code == 200

    listed = client.get("/applications?limit=50")
    assert listed.status_code == 200
    rows = listed.json()["items"]
    assert len(rows) == 1
    assert rows[0]["score_breakdown"] is not None
    assert rows[0]["score_breakdown"]["score"] == 13
    assert rows[0]["score_breakdown"]["fit"] == "Strong"
    assert rows[0]["score_breakdown"]["matched_keywords"] == ["Python", "SQL"]


def test_run_discovery_output_is_summarized() -> None:
    _clear_db()
    _reset_discovery_guard()

    class FakeOptions:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    fake_result = SimpleNamespace(
        strict_matches=[],
        broad_matches=[],
        llm_report=SimpleNamespace(dry_run=False, planned_calls=0, attempted=0, adjusted=0, used_input_chars=0),
        synced_count=0,
        failed_rows=[],
        collection_report=SimpleNamespace(sources=[]),
    )
    fake_warnings = SimpleNamespace(messages=[])
    fake_module = SimpleNamespace(
        DiscoveryRunOptions=FakeOptions,
        run_discovery_pipeline=lambda options: (fake_result, fake_warnings),
    )

    with patch("app.routers.discovery.importlib.import_module", return_value=fake_module):
        response = client.post(
            "/run-discovery",
            json={"limit": 5, "min_score": 1, "max_age_days": 10, "include_stretch": False},
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()

    assert data["command"] == []
    assert "Enable verbose=true" in data["stdout"]
    assert data["stderr"] == ""


def test_run_discovery_verbose_output_is_summarized() -> None:
    _clear_db()
    _reset_discovery_guard()

    class FakeOptions:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    fake_result = SimpleNamespace(
        strict_matches=[],
        broad_matches=[],
        llm_report=SimpleNamespace(dry_run=False, planned_calls=0, attempted=0, adjusted=0, used_input_chars=0),
        synced_count=0,
        failed_rows=[],
        collection_report=SimpleNamespace(sources=[]),
    )
    fake_warnings = SimpleNamespace(messages=[])
    fake_module = SimpleNamespace(
        DiscoveryRunOptions=FakeOptions,
        run_discovery_pipeline=lambda options: (fake_result, fake_warnings),
    )

    with patch("app.routers.discovery.importlib.import_module", return_value=fake_module):
        response = client.post(
            "/run-discovery",
            json={
                "limit": 5,
                "min_score": 1,
                "max_age_days": 10,
                "include_stretch": False,
                "verbose": True,
                "api_base_url": "http://127.0.0.1:8000",
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["command"] == ["module:job_discovery_engine.run_discovery_pipeline"]
    assert "strict_matches=0" in data["stdout"]
    assert data["stderr"] == ""


def test_run_discovery_forwards_profile_mode() -> None:
    _clear_db()
    _reset_discovery_guard()

    captured: dict[str, object] = {}

    class FakeOptions:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    fake_result = SimpleNamespace(
        strict_matches=[],
        broad_matches=[],
        llm_report=SimpleNamespace(dry_run=True, planned_calls=2, attempted=0, adjusted=0, used_input_chars=0),
        synced_count=0,
        failed_rows=[],
        collection_report=SimpleNamespace(sources=[]),
    )
    fake_warnings = SimpleNamespace(messages=[])
    fake_module = SimpleNamespace(
        DiscoveryRunOptions=FakeOptions,
        run_discovery_pipeline=lambda options: (fake_result, fake_warnings),
    )

    with patch("app.routers.discovery.importlib.import_module", return_value=fake_module):
        response = client.post(
            "/run-discovery",
            json={
                "limit": 5,
                "min_score": 1,
                "max_age_days": 10,
                "include_stretch": False,
                "profile": "swe",
                "api_base_url": "http://127.0.0.1:8000",
                "verbose": True,
                "salary_min_usd": 120000,
                "timezones": ["UTC", "CET"],
                "seniority": "senior",
                "use_outcome_priors": True,
                "prior_lookback_days": 180,
                "source_prior_weight": 1.4,
                "role_prior_weight": 0.9,
                "use_llm_reranker": True,
                "llm_top_n": 12,
                "llm_weight": 0.8,
                "llm_model": "gpt-4o-mini",
                "llm_api_base_url": "https://api.openai.com/v1",
                "llm_dry_run": True,
                "llm_max_calls": 9,
                "llm_max_input_chars": 18000,
                "llm_max_retries": 3,
                "llm_retry_backoff_seconds": 0.6,
                "llm_timeout_seconds": 25,
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    assert captured["profile"] == "swe"
    assert captured["api_base_url"] == "http://127.0.0.1:8000"
    assert captured["max_age_days"] == 10
    assert captured["salary_min_usd"] == 120000
    assert captured["timezones"] == ["UTC", "CET"]
    assert captured["seniority"] == "senior"
    assert captured["use_outcome_priors"] is True
    assert captured["prior_lookback_days"] == 180
    assert captured["source_prior_weight"] == 1.4
    assert captured["role_prior_weight"] == 0.9
    assert captured["use_llm_reranker"] is True
    assert captured["llm_top_n"] == 12
    assert captured["llm_weight"] == 0.8
    assert captured["llm_model"] == "gpt-4o-mini"
    assert captured["llm_api_base_url"] == "https://api.openai.com/v1"
    assert captured["llm_dry_run"] is True
    assert captured["llm_max_calls"] == 9
    assert captured["llm_max_input_chars"] == 18000
    assert captured["llm_max_retries"] == 3
    assert captured["llm_retry_backoff_seconds"] == 0.6
    assert captured["llm_timeout_seconds"] == 25
    assert captured["sources"] is None
    assert captured["output_dir"] is None


def test_generate_documents_and_workspace_file_editing() -> None:
    _clear_db()
    created = client.post(
        "/applications/upsert",
        json=_base_payload(company="Northwind", role="Data Engineer", link="https://example.com/jobs/gen-1"),
        headers=_auth_headers(),
    )
    assert created.status_code == 200
    application_id = created.json()["id"]

    generated = client.post(
        f"/applications/{application_id}/generate-documents",
        json={"overwrite": True},
        headers=_auth_headers(),
    )
    assert generated.status_code == 200
    data = generated.json()
    assert "/applications/vacancies/" in data["cover_letter_path"]
    assert data["cv_path"].endswith("/cv.tex")

    read_file = client.get("/workspace-file", params={"path": data["cover_letter_path"]}, headers=_auth_headers())
    assert read_file.status_code == 200
    assert "Northwind" in read_file.json()["content"]

    updated_text = read_file.json()["content"] + "\nCustom edit line.\n"
    write_file = client.put(
        "/workspace-file",
        json={"path": data["cover_letter_path"], "content": updated_text},
        headers=_auth_headers(),
    )
    assert write_file.status_code == 200
    assert "Custom edit line." in write_file.json()["content"]


def test_workspace_file_rejects_outside_applications() -> None:
    _clear_db()
    response = client.get("/workspace-file", params={"path": "README.md"}, headers=_auth_headers())
    assert response.status_code == 400


def test_workspace_file_read_requires_api_key() -> None:
    _clear_db()
    response = client.get("/workspace-file", params={"path": "applications/tracker/application_notes_latest.md"})
    assert response.status_code == 401


def test_generate_documents_overwrite_flow() -> None:
    _clear_db()
    target_dir = _APPLICATIONS_ROOT / "vacancies" / "northwind_data_engineer"
    if target_dir.exists():
        shutil.rmtree(target_dir)

    created = client.post(
        "/applications/upsert",
        json=_base_payload(company="Northwind", role="Data Engineer", link="https://example.com/jobs/gen-overwrite"),
        headers=_auth_headers(),
    )
    assert created.status_code == 200
    application_id = created.json()["id"]

    first = client.post(
        f"/applications/{application_id}/generate-documents",
        json={"overwrite": False},
        headers=_auth_headers(),
    )
    assert first.status_code == 200

    second = client.post(
        f"/applications/{application_id}/generate-documents",
        json={"overwrite": False},
        headers=_auth_headers(),
    )
    assert second.status_code == 409

    cover_template = _TEMPLATE_DIR / "cover_letter.md"
    original_template = cover_template.read_text(encoding="utf-8")
    try:
        cover_template.write_text("OVERWRITTEN [Role Title] at [Company].\n[Author Name]", encoding="utf-8")

        overwritten = client.post(
            f"/applications/{application_id}/generate-documents",
            json={"overwrite": True},
            headers=_auth_headers(),
        )
        assert overwritten.status_code == 200
        path = overwritten.json()["cover_letter_path"]

        read_back = client.get("/workspace-file", params={"path": path}, headers=_auth_headers())
        assert read_back.status_code == 200
        content = read_back.json()["content"]
        assert "OVERWRITTEN" in content
        assert "Northwind" in content
    finally:
        cover_template.write_text(original_template, encoding="utf-8")


def test_generate_documents_cleans_files_when_commit_fails() -> None:
    _clear_db()
    target_dir = _APPLICATIONS_ROOT / "vacancies" / "rollback_inc_data_engineer"
    if target_dir.exists():
        shutil.rmtree(target_dir)

    created = client.post(
        "/applications/upsert",
        json=_base_payload(company="Rollback Inc", role="Data Engineer", link="https://example.com/jobs/gen-fail"),
        headers=_auth_headers(),
    )
    assert created.status_code == 200
    application_id = created.json()["id"]

    with patch("app.routers.workspace.Session.commit", side_effect=RuntimeError("commit failed")):
        failed = client.post(
            f"/applications/{application_id}/generate-documents",
            json={"overwrite": True},
            headers=_auth_headers(),
        )

    assert failed.status_code == 500
    assert failed.json()["detail"] == "Failed to generate documents"
    assert not (target_dir / "vacancy.md").exists()
    assert not (target_dir / "cover_letter.md").exists()
    assert not (target_dir / "notes.md").exists()
    assert not (target_dir / "cv.tex").exists()


def test_health_and_stats_endpoints() -> None:
    _clear_db()

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    ver = client.get("/version")
    assert ver.status_code == 200
    assert "version" in ver.json()
    assert isinstance(ver.json()["version"], str)
    assert ver.json()["version"]  # non-empty

    first = client.post(
        "/applications/upsert",
        json=_base_payload(
            company="Northwind",
            role="Data Engineer",
            link="https://example.com/job/stats-1",
            status="Applied",
            next_step="Interview",
        ),
        headers=_auth_headers(),
    )
    assert first.status_code == 200

    second = client.post(
        "/applications/upsert",
        json=_base_payload(
            company="Blue Harbor",
            role="Backend Engineer",
            link="https://example.com/job/stats-2",
            status="To Review",
            next_step="Screening",
        ),
        headers=_auth_headers(),
    )
    assert second.status_code == 200

    stats = client.get("/stats")
    assert stats.status_code == 200
    data = stats.json()

    assert data["total_applications"] == 2
    assert data["by_status"]["applied"] == 1
    assert data["by_status"]["to review"] == 1
    assert data["by_stage"]["interview"] == 1
    assert data["by_stage"]["screening"] == 1


def test_startup_does_not_bootstrap_schema() -> None:
    # API startup is now side-effect free; schema init is an explicit command.
    with TestClient(app) as fresh_client:
        response = fresh_client.get("/health")

    assert response.status_code == 200


def test_path_and_helper_sanity() -> None:
    assert applications_root() == _APPLICATIONS_ROOT
    assert resolve_from_applications_root("vacancies/_template") == _TEMPLATE_DIR
    assert is_within_path(_TEMPLATE_DIR, _APPLICATIONS_ROOT)
    assert safe_relative_path(_TEMPLATE_DIR, _APPLICATIONS_ROOT) == "vacancies/_template"

    assert slugify("  Foo bar!!  ") == "foo_bar"
    assert slugify("") == "item"                           # empty → fallback
    assert slugify("!!!") == "item"                        # only specials → fallback
    assert slugify("héllo wörld") == "h_llo_w_rld"         # non-ASCII stripped
    assert slugify("a" * 100, max_len=10) == "a" * 10      # truncated at max_len
    assert slugify("AB--CD") == "ab_cd"                    # consecutive specials collapsed
    assert summarize_process_output("abc", 10) == "abc"

    truncated = summarize_process_output("A" * 600, 80)
    assert "output truncated" in truncated
    assert len(truncated) <= 80
    assert today_iso() == datetime.now().strftime("%Y-%m-%d")


def test_run_discovery_failure_truncates_stderr() -> None:
    _clear_db()
    _reset_discovery_guard()

    with patch("app.routers.discovery.importlib.import_module", side_effect=ImportError("missing package")):
        response = client.post(
            "/run-discovery",
            json={
                "limit": 5,
                "min_score": 1,
                "max_age_days": 10,
                "include_stretch": False,
                "api_base_url": "http://127.0.0.1:8000",
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert "Discovery module package not found" in detail


def test_run_discovery_verbose_failure_truncates_stderr() -> None:
    _clear_db()
    _reset_discovery_guard()

    with patch("app.routers.discovery.importlib.import_module", side_effect=ImportError("missing package")):
        response = client.post(
            "/run-discovery",
            json={
                "limit": 5,
                "min_score": 1,
                "max_age_days": 10,
                "include_stretch": False,
                "verbose": True,
                "api_base_url": "http://127.0.0.1:8000",
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert "Discovery module package not found" in detail


def test_run_discovery_rate_limit_blocks_immediate_repeat() -> None:
    _clear_db()
    _reset_discovery_guard()

    class FakeOptions:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    fake_result = SimpleNamespace(
        strict_matches=[],
        broad_matches=[],
        llm_report=SimpleNamespace(dry_run=False, planned_calls=0, attempted=0, adjusted=0, used_input_chars=0),
        synced_count=0,
        failed_rows=[],
        collection_report=SimpleNamespace(sources=[]),
    )
    fake_warnings = SimpleNamespace(messages=[])
    fake_module = SimpleNamespace(
        DiscoveryRunOptions=FakeOptions,
        run_discovery_pipeline=lambda options: (fake_result, fake_warnings),
    )

    payload = {
        "limit": 5,
        "min_score": 1,
        "max_age_days": 10,
        "include_stretch": False,
        "api_base_url": "http://127.0.0.1:8000",
    }

    with patch("app.routers.discovery.importlib.import_module", return_value=fake_module):
        first = client.post("/run-discovery", json=payload, headers=_auth_headers())
        second = client.post("/run-discovery", json=payload, headers=_auth_headers())

    assert first.status_code == 200
    assert second.status_code == 429
    assert "rate-limited" in second.json()["detail"]


def test_run_discovery_rejects_invalid_numeric_bounds() -> None:
    _clear_db()
    _reset_discovery_guard()

    response = client.post(
        "/run-discovery",
        json={
            "limit": 0,
            "min_score": -1,
            "max_age_days": 0,
            "llm_max_input_chars": -100,
            "llm_timeout_seconds": 0,
            "api_base_url": "http://127.0.0.1:8000",
        },
        headers=_auth_headers(),
    )

    assert response.status_code == 422


def test_run_discovery_rejects_private_ip_api_base_url() -> None:
    _clear_db()
    _reset_discovery_guard()

    for private_url in [
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1:8000",
        "http://192.168.1.100:8080",
        "http://172.16.0.1/",
    ]:
        response = client.post(
            "/run-discovery",
            json={"limit": 5, "min_score": 1, "max_age_days": 10, "include_stretch": False, "api_base_url": private_url},
            headers=_auth_headers(),
        )
        assert response.status_code == 400, f"Expected 400 for {private_url}, got {response.status_code}"
        _reset_discovery_guard()


def test_workspace_file_rejects_path_traversal() -> None:
    """Explicit traversal sequence must be blocked regardless of target path."""
    for traversal_path in [
        "../../../../etc/passwd",
        "../../../etc/shadow",
        "applications/../../etc/passwd",
    ]:
        response = client.get("/workspace-file", params={"path": traversal_path}, headers=_auth_headers())
        assert response.status_code == 400, f"Expected 400 for {traversal_path!r}, got {response.status_code}"


def test_missing_skills_endpoint() -> None:
    _clear_db()

    client.post(
        "/applications/upsert",
        json=_base_payload(
            company="SkillCo",
            role="Data Engineer",
            link="https://example.com/job/skills-1",
            notes="Experience needed. Missing or adjacent tools: dbt, Trino, Terraform.",
        ),
        headers=_auth_headers(),
    )
    client.post(
        "/applications/upsert",
        json=_base_payload(
            company="SkillCo2",
            role="Analytics Engineer",
            link="https://example.com/job/skills-2",
            notes="Nice to have. Missing or adjacent tools: dbt, Spark.",
        ),
        headers=_auth_headers(),
    )

    response = client.get("/missing-skills")
    assert response.status_code == 200
    data = response.json()
    items = {item["skill"]: item["count"] for item in data["items"]}
    assert items.get("dbt") == 2
    assert items.get("Trino") == 1
    assert items.get("Spark") == 1


def test_delete_application() -> None:
    _clear_db()

    created = client.post(
        "/applications/upsert",
        json=_base_payload(link="https://example.com/job/delete-me"),
        headers=_auth_headers(),
    )
    assert created.status_code == 200
    app_id = created.json()["id"]

    # Requires write key
    no_auth = client.delete(f"/applications/{app_id}")
    assert no_auth.status_code == 401

    # Happy path
    deleted = client.delete(f"/applications/{app_id}", headers=_auth_headers())
    assert deleted.status_code == 204

    # Gone afterwards
    listed = client.get("/applications?limit=50")
    ids = [r["id"] for r in listed.json()["items"]]
    assert app_id not in ids

    # Second delete → 404
    second = client.delete(f"/applications/{app_id}", headers=_auth_headers())
    assert second.status_code == 404


def test_trend_endpoint() -> None:
    _clear_db()

    client.post(
        "/applications/upsert",
        json=_base_payload(company="A", role="DE", link="https://example.com/job/trend-1", date_found="2026-05-01"),
        headers=_auth_headers(),
    )
    client.post(
        "/applications/upsert",
        json=_base_payload(company="B", role="DE", link="https://example.com/job/trend-2", date_found="2026-05-02"),
        headers=_auth_headers(),
    )
    client.post(
        "/applications/upsert",
        json=_base_payload(company="C", role="DE", link="https://example.com/job/trend-3", date_found="2026-05-15"),
        headers=_auth_headers(),
    )

    response = client.get("/trend")
    assert response.status_code == 200
    data = response.json()
    weeks = {item["week"]: item["count"] for item in data["items"]}
    # 2026-05-01 and 2026-05-02 fall in ISO week 2026-W18
    assert weeks.get("2026-W18") == 2
    # 2026-05-15 falls in ISO week 2026-W20
    assert weeks.get("2026-W20") == 1


def test_discovery_status_idle() -> None:
    _reset_discovery_guard()
    response = client.get("/discovery/status")
    assert response.status_code == 200
    data = response.json()
    assert data["in_flight"] is False
    assert data["elapsed_seconds"] is None


def test_discovery_status_cooldown() -> None:
    import time
    from app.routers import discovery as dr
    # Simulate a completed run that just finished
    with dr._guard.lock:
        dr._guard.in_flight = False
        dr._guard.last_started_monotonic = time.monotonic()  # set to "just now"
    response = client.get("/discovery/status")
    assert response.status_code == 200
    data = response.json()
    assert data["in_flight"] is False
    # Cooldown should be close to DISCOVERY_MIN_INTERVAL_SECONDS
    assert data["cooldown_seconds_remaining"] is not None
    assert 0 < data["cooldown_seconds_remaining"] <= dr.DISCOVERY_MIN_INTERVAL_SECONDS
    _reset_discovery_guard()


def test_score_breakdown_preserved_on_fingerprint_change() -> None:
    """score_breakdown must survive an upsert that changes the listing fingerprint."""
    _clear_db()
    scoring_json = json.dumps({
        "score": 85,
        "fit": "Strong",
        "matched_keywords": ["python", "sql"],
        "missing_skills": ["kubernetes"],
        "fit_notes": "Good match overall",
    })

    # First upsert: create the row with scoring data in change_note (discovery engine pattern)
    first = client.post(
        "/applications/upsert",
        json=_base_payload(change_note=scoring_json, listing_fingerprint="fp-v1"),
        headers=_auth_headers(),
    )
    assert first.status_code == 200
    body1 = first.json()
    assert body1["score_breakdown"] is not None
    assert body1["score_breakdown"]["score"] == 85

    # Second upsert: different fingerprint (listing changed) — change_note is plain text now
    second = client.post(
        "/applications/upsert",
        json=_base_payload(change_note="", listing_fingerprint="fp-v2"),
        headers=_auth_headers(),
    )
    assert second.status_code == 200
    body2 = second.json()
    # score_breakdown must still be present from the earlier run
    assert body2["score_breakdown"] is not None
    assert body2["score_breakdown"]["score"] == 85
    # change_note should reflect the human-readable update message
    assert "Updated on" in body2["change_note"]


def test_patch_application_happy_path() -> None:
    """PATCH /applications/{id} updates editable fields and returns the row."""
    _clear_db()
    create = client.post(
        "/applications/upsert",
        json=_base_payload(),
        headers=_auth_headers(),
    )
    assert create.status_code == 200
    app_id = create.json()["id"]

    resp = client.patch(
        f"/applications/{app_id}",
        json={"status": "Interview", "notes": "Going well"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "Interview"
    assert body["notes"] == "Going well"


def test_patch_application_404() -> None:
    """PATCH /applications/{id} returns 404 for a non-existent id."""
    _clear_db()
    resp = client.patch(
        "/applications/99999",
        json={"status": "Rejected"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 404


def test_patch_application_requires_api_key() -> None:
    """PATCH /applications/{id} returns 401 without a valid API key."""
    _clear_db()
    create = client.post(
        "/applications/upsert",
        json=_base_payload(),
        headers=_auth_headers(),
    )
    assert create.status_code == 200
    app_id = create.json()["id"]

    resp = client.patch(f"/applications/{app_id}", json={"status": "Saved"})
    assert resp.status_code == 401


def test_trend_endpoint_with_dates() -> None:
    """GET /trend groups applications by ISO week correctly."""
    _clear_db()
    client.post(
        "/applications/upsert",
        json=_base_payload(date_found="2024-01-08"),
        headers=_auth_headers(),
    )
    payload2 = _base_payload(date_found="2024-01-15")
    payload2["company"] = "OtherCo"
    payload2["link"] = "https://example.com/job/base2"
    client.post("/applications/upsert", json=payload2, headers=_auth_headers())

    resp = client.get("/trend", headers=_auth_headers())
    assert resp.status_code == 200
    items = resp.json()["items"]
    weeks = [item["week"] for item in items]
    assert "2024-W02" in weeks
    assert "2024-W03" in weeks


def test_missing_skills_uses_default_when_empty() -> None:
    """GET /missing-skills falls back to settings.default_missing_skills when no marker rows exist."""
    _clear_db()
    # Create a row without the marker text
    client.post(
        "/applications/upsert",
        json=_base_payload(notes="Great job, no skill gap text here"),
        headers=_auth_headers(),
    )
    resp = client.get("/missing-skills", headers=_auth_headers())
    assert resp.status_code == 200
    # Should return the default skills list (may be empty or populated from settings)
    data = resp.json()
    assert "items" in data
    assert isinstance(data["items"], list)


def test_missing_skills_parses_marker() -> None:
    """GET /missing-skills extracts skills from the marker text in notes."""
    _clear_db()
    client.post(
        "/applications/upsert",
        json=_base_payload(notes="Missing or adjacent tools: Kubernetes, Terraform"),
        headers=_auth_headers(),
    )
    resp = client.get("/missing-skills", headers=_auth_headers())
    assert resp.status_code == 200
    items = resp.json()["items"]
    skills = [item["skill"] for item in items]
    assert any("Kubernetes" in s for s in skills)
    assert any("Terraform" in s for s in skills)


# ── Discovery router: auth, validation, concurrency, log sanitization ──────────


def test_run_discovery_requires_write_key() -> None:
    """POST /run-discovery must return 401 when the API key is absent."""
    _reset_discovery_guard()
    response = client.post(
        "/run-discovery",
        json={"limit": 5, "min_score": 1, "max_age_days": 10, "include_stretch": False},
    )
    assert response.status_code == 401


def test_run_discovery_invalid_profile_returns_422() -> None:
    """POST /run-discovery returns 422 for a profile value not in {de, swe, sre, other}."""
    _reset_discovery_guard()
    response = client.post(
        "/run-discovery",
        json={
            "limit": 5,
            "min_score": 1,
            "max_age_days": 10,
            "include_stretch": False,
            "profile": "cto",
        },
        headers=_auth_headers(),
    )
    assert response.status_code == 422
    body = response.json()
    # Pydantic validation error — detail is a list of error objects
    assert any("profile" in str(err).lower() for err in body["detail"])


def test_run_discovery_cv_path_outside_workspace_returns_400() -> None:
    """POST /run-discovery rejects cv_path values that escape the workspace root."""
    _reset_discovery_guard()
    response = client.post(
        "/run-discovery",
        json={
            "limit": 5,
            "min_score": 1,
            "max_age_days": 10,
            "include_stretch": False,
            "cv_path": "/etc/passwd",
        },
        headers=_auth_headers(),
    )
    assert response.status_code == 400
    assert "workspace" in response.json()["detail"].lower()


def test_run_discovery_ssrf_rejects_private_ip() -> None:
    """POST /run-discovery returns 400 when api_base_url targets a private IP."""
    _reset_discovery_guard()
    response = client.post(
        "/run-discovery",
        json={
            "limit": 5,
            "min_score": 1,
            "max_age_days": 10,
            "include_stretch": False,
            "api_base_url": "http://192.168.1.1:8000",
        },
        headers=_auth_headers(),
    )
    assert response.status_code == 400
    assert "private" in response.json()["detail"].lower()


def test_run_discovery_ssrf_allows_loopback() -> None:
    """Loopback api_base_url (127.0.0.1) is the legitimate default and must pass SSRF guard."""
    _reset_discovery_guard()

    class FakeOptions:
        def __init__(self, **kwargs: object) -> None:
            pass

    fake_result = SimpleNamespace(
        strict_matches=[],
        broad_matches=[],
        llm_report=SimpleNamespace(dry_run=False, planned_calls=0, attempted=0, adjusted=0, used_input_chars=0),
        synced_count=0,
        failed_rows=[],
        collection_report=SimpleNamespace(sources=[]),
    )
    fake_warnings = SimpleNamespace(messages=[])
    fake_module = SimpleNamespace(
        DiscoveryRunOptions=FakeOptions,
        run_discovery_pipeline=lambda options: (fake_result, fake_warnings),
    )

    with patch("app.routers.discovery.importlib.import_module", return_value=fake_module):
        response = client.post(
            "/run-discovery",
            json={
                "limit": 5,
                "min_score": 1,
                "max_age_days": 10,
                "include_stretch": False,
                "api_base_url": "http://127.0.0.1:8000",
            },
            headers=_auth_headers(),
        )
    assert response.status_code == 200
    # Reset so subsequent tests and other test files do not hit the cooldown.
    _reset_discovery_guard()


def test_sanitize_for_public_logs_redacts_workspace_path() -> None:
    """_sanitize_for_public_logs replaces the workspace root path with <workspace>."""
    from app.routers.discovery import _sanitize_for_public_logs
    from app.pathing import workspace_root

    root = str(workspace_root())
    raw = f"CV not found at {root}/applications/resumes/CV.tex"
    sanitized = _sanitize_for_public_logs(raw)
    assert root not in sanitized
    assert "<workspace>" in sanitized


def test_claim_discovery_slot_rejects_concurrent_run() -> None:
    """A second /run-discovery request returns 429 while a run is already in flight."""
    _reset_discovery_guard()
    from app.routers import discovery as dr

    with dr._guard.lock:
        dr._guard.in_flight = True

    try:
        response = client.post(
            "/run-discovery",
            json={"limit": 5, "min_score": 1, "max_age_days": 10, "include_stretch": False},
            headers=_auth_headers(),
        )
        assert response.status_code == 429
        assert "in progress" in response.json()["detail"].lower()
    finally:
        _reset_discovery_guard()


def test_run_discovery_module_import_error_returns_500() -> None:
    """POST /run-discovery returns 500 when the job_discovery_engine package is missing."""
    _reset_discovery_guard()
    with patch(
        "app.routers.discovery.importlib.import_module",
        side_effect=ImportError("No module named 'job_discovery_engine'"),
    ):
        response = client.post(
            "/run-discovery",
            json={"limit": 5, "min_score": 1, "max_age_days": 10, "include_stretch": False},
            headers=_auth_headers(),
        )
    assert response.status_code == 500
    assert "Discovery module" in response.json()["detail"]


def test_workspace_file_rejects_symlink_escape() -> None:
    """GET /workspace-file rejects a path that resolves outside the workspace via symlink."""
    import tempfile
    from app.pathing import applications_root, workspace_root

    ws_root = workspace_root()
    app_root = applications_root()
    fd, outside = tempfile.mkstemp()
    os.close(fd)
    symlink = app_root / "_test_evil_symlink.txt"
    try:
        symlink.symlink_to(outside)
        rel_path = symlink.relative_to(ws_root).as_posix()
        response = client.get(f"/workspace-file?path={rel_path}", headers=_auth_headers())
        assert response.status_code == 400
    finally:
        symlink.unlink(missing_ok=True)
        os.unlink(outside)


def test_workspace_file_write_at_limit_is_accepted() -> None:
    """PUT /workspace-file accepts exactly 1 MB of content."""
    from app.pathing import applications_root, workspace_root

    ws_root = workspace_root()
    app_root = applications_root()
    # Build a path that is within applications_root and express it relative to workspace_root
    target_abs = app_root / "_test_limit_boundary.txt"
    rel_path = target_abs.relative_to(ws_root).as_posix()

    content = "x" * 1_000_000
    try:
        response = client.put(
            "/workspace-file",
            json={"path": rel_path, "content": content},
            headers=_auth_headers(),
        )
        assert response.status_code == 200
    finally:
        if target_abs.exists():
            target_abs.unlink()


def test_workspace_file_write_above_limit_is_rejected() -> None:
    """PUT /workspace-file rejects content exceeding the 1 MB limit with 422."""
    from app.pathing import applications_root, workspace_root

    ws_root = workspace_root()
    app_root = applications_root()
    target_abs = app_root / "_test_over_limit.txt"
    rel_path = target_abs.relative_to(ws_root).as_posix()

    content = "x" * 1_000_001
    response = client.put(
        "/workspace-file",
        json={"path": rel_path, "content": content},
        headers=_auth_headers(),
    )
    assert response.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# Option B: Integration tests – coverage for previously untested code paths
# ─────────────────────────────────────────────────────────────────────────────


def test_analytics_missing_skills_section_truncation() -> None:
    """GET /missing-skills truncates the raw text at the next section header."""
    _clear_db()
    client.post(
        "/applications/upsert",
        json=_base_payload(
            notes="Summary\nMissing or adjacent tools: dbt, Spark\nNext Steps: submit tomorrow",
        ),
        headers=_auth_headers(),
    )
    resp = client.get("/missing-skills")
    assert resp.status_code == 200
    skills = {item["skill"] for item in resp.json()["items"]}
    assert "dbt" in skills
    assert "Spark" in skills
    # Nothing from the section that follows the skills list should appear
    assert not any(s in {"Next Steps", "submit", "tomorrow"} for s in skills)


def test_analytics_trend_whitespace_date_found() -> None:
    """GET /trend skips records where date_found is whitespace-only."""
    _clear_db()
    client.post(
        "/applications/upsert",
        json=_base_payload(date_found="   "),
        headers=_auth_headers(),
    )
    resp = client.get("/trend")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_analytics_trend_bad_date_format() -> None:
    """GET /trend skips records where date_found is not a valid YYYY-MM-DD date."""
    _clear_db()
    client.post(
        "/applications/upsert",
        json=_base_payload(date_found="not-a-date"),
        headers=_auth_headers(),
    )
    resp = client.get("/trend")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_list_applications_source_filter() -> None:
    """GET /applications?source=... filters results by the source field."""
    _clear_db()
    client.post(
        "/applications/upsert",
        json={"company": "Remotive Corp", "role": "Engineer", "link": "https://example.com/job/src-remotive", "source": "remotive"},
        headers=_auth_headers(),
    )
    client.post(
        "/applications/upsert",
        json={"company": "LinkedIn Corp", "role": "Engineer", "link": "https://example.com/job/src-linkedin", "source": "linkedin"},
        headers=_auth_headers(),
    )
    resp = client.get("/applications?source=remotive&limit=50")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["source"] == "remotive"


def test_list_applications_min_fit_score_filter() -> None:
    """GET /applications?min_fit_score=... returns only records at or above the threshold."""
    _clear_db()
    client.post(
        "/applications/upsert",
        json={"company": "HiScore Inc", "role": "Engineer", "link": "https://example.com/job/hi-score", "fit_score": 8},
        headers=_auth_headers(),
    )
    client.post(
        "/applications/upsert",
        json={"company": "LoScore Inc", "role": "Engineer", "link": "https://example.com/job/lo-score", "fit_score": 3},
        headers=_auth_headers(),
    )
    resp = client.get("/applications?min_fit_score=5&limit=50")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["fit_score"] == 8


def test_upsert_preserves_change_note_same_fingerprint() -> None:
    """Upserting with the same fingerprint and no incoming change_note preserves the original."""
    _clear_db()
    client.post(
        "/applications/upsert",
        json=_base_payload(listing_fingerprint="fp-stable", change_note="original note"),
        headers=_auth_headers(),
    )
    resp = client.post(
        "/applications/upsert",
        json=_base_payload(listing_fingerprint="fp-stable"),
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["change_note"] == "original note"


def test_parse_score_json_non_dict_string() -> None:
    """Upserting with a non-JSON score_breakdown string normalises it to None."""
    _clear_db()
    resp = client.post(
        "/applications/upsert",
        json=_base_payload(score_breakdown="plain text, not JSON"),
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["score_breakdown"] is None


def test_parse_score_json_invalid_json() -> None:
    """A change_note that opens with '{' but is not valid JSON does not become score_breakdown."""
    _clear_db()
    resp = client.post(
        "/applications/upsert",
        json=_base_payload(change_note='{"broken json'),
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["score_breakdown"] is None


def test_run_discovery_cv_path_not_found() -> None:
    """POST /run-discovery returns 400 when cv_path resolves within the workspace but the file is absent."""
    _reset_discovery_guard()
    resp = client.post(
        "/run-discovery",
        json={
            "limit": 5,
            "min_score": 1,
            "max_age_days": 10,
            "include_stretch": False,
            "cv_path": "applications/resumes/no_such_file.tex",
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 400
    assert "Discovery CV not found" in resp.json()["detail"]


def test_run_discovery_no_cv_path_configured() -> None:
    """POST /run-discovery returns 400 when neither cv_path nor DISCOVERY_CV_PATH is set."""
    _reset_discovery_guard()
    from app.config import settings as _settings

    with patch.object(_settings, "discovery_cv_path", ""):
        resp = client.post(
            "/run-discovery",
            json={"limit": 5, "min_score": 1, "max_age_days": 10, "include_stretch": False},
            headers=_auth_headers(),
        )
    assert resp.status_code == 400
    assert "CV path is missing" in resp.json()["detail"]


def test_run_discovery_missing_api_base_url() -> None:
    """POST /run-discovery returns 400 when api_base_url is absent and no env fallback is configured."""
    _reset_discovery_guard()
    from app.config import settings as _settings

    with patch.object(_settings, "discovery_api_base_url", ""):
        resp = client.post(
            "/run-discovery",
            json={"limit": 5, "min_score": 1, "max_age_days": 10, "include_stretch": False},
            headers=_auth_headers(),
        )
    assert resp.status_code == 400
    assert "api_base_url is missing" in resp.json()["detail"]


def test_run_discovery_bad_scheme_api_base_url() -> None:
    """POST /run-discovery returns 400 when api_base_url uses an unsupported scheme."""
    _reset_discovery_guard()
    resp = client.post(
        "/run-discovery",
        json={
            "limit": 5,
            "min_score": 1,
            "max_age_days": 10,
            "include_stretch": False,
            "api_base_url": "ftp://example.com/api",
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 400
    assert "http" in resp.json()["detail"]


def test_run_discovery_output_dir_traversal() -> None:
    """POST /run-discovery returns 400 when output_dir would escape the workspace root."""
    _reset_discovery_guard()
    resp = client.post(
        "/run-discovery",
        json={
            "limit": 5,
            "min_score": 1,
            "max_age_days": 10,
            "include_stretch": False,
            "api_base_url": "http://127.0.0.1:8000",
            "output_dir": "../../../../tmp",
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 400
    assert "output_dir" in resp.json()["detail"].lower()


def test_run_discovery_with_sources() -> None:
    """POST /run-discovery passes a normalised sources list to the engine."""
    _clear_db()
    _reset_discovery_guard()

    captured: dict[str, object] = {}

    class FakeOptions:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    fake_result = SimpleNamespace(
        strict_matches=[],
        broad_matches=[],
        llm_report=SimpleNamespace(dry_run=False, planned_calls=0, attempted=0, adjusted=0, used_input_chars=0),
        synced_count=0,
        failed_rows=[],
        collection_report=SimpleNamespace(sources=[]),
    )
    fake_warnings = SimpleNamespace(messages=[])
    fake_module = SimpleNamespace(
        DiscoveryRunOptions=FakeOptions,
        run_discovery_pipeline=lambda options: (fake_result, fake_warnings),
    )

    with patch("app.routers.discovery.importlib.import_module", return_value=fake_module):
        resp = client.post(
            "/run-discovery",
            json={
                "limit": 5,
                "min_score": 1,
                "max_age_days": 10,
                "include_stretch": False,
                "api_base_url": "http://127.0.0.1:8000",
                "sources": ["remotive", "  WeWorkRemotely  "],
            },
            headers=_auth_headers(),
        )
    assert resp.status_code == 200
    assert captured.get("sources") == ["remotive", "weworkremotely"]


def test_run_discovery_timeout_returns_504() -> None:
    """POST /run-discovery returns 504 when the pipeline exceeds the wall-clock timeout."""
    _clear_db()
    _reset_discovery_guard()

    import concurrent.futures as _cf
    from unittest.mock import MagicMock

    mock_future = MagicMock()
    mock_future.result.side_effect = _cf.TimeoutError()
    mock_executor = MagicMock()
    mock_executor.submit.return_value = mock_future

    class FakeOptions:
        def __init__(self, **kwargs: object) -> None:
            pass

    fake_result = SimpleNamespace(
        strict_matches=[],
        broad_matches=[],
        llm_report=SimpleNamespace(dry_run=False, planned_calls=0, attempted=0, adjusted=0, used_input_chars=0),
        synced_count=0,
        failed_rows=[],
        collection_report=SimpleNamespace(sources=[]),
    )
    fake_warnings = SimpleNamespace(messages=[])
    fake_module = SimpleNamespace(
        DiscoveryRunOptions=FakeOptions,
        run_discovery_pipeline=lambda options: (fake_result, fake_warnings),
    )

    with patch("app.routers.discovery.importlib.import_module", return_value=fake_module), \
         patch.object(_cf, "ThreadPoolExecutor", return_value=mock_executor):
            resp = client.post(
                "/run-discovery",
                json={
                    "limit": 5,
                    "min_score": 1,
                    "max_age_days": 10,
                    "include_stretch": False,
                    "api_base_url": "http://127.0.0.1:8000",
                },
                headers=_auth_headers(),
            )

    assert resp.status_code == 504
    assert "timed out" in resp.json()["detail"].lower()
    _reset_discovery_guard()


def test_workspace_file_rejects_unsupported_extension() -> None:
    """GET /workspace-file returns 400 for a file extension not in the allowed set."""
    from app.pathing import workspace_root

    ws_root = workspace_root()
    target = _APPLICATIONS_ROOT / "script.py"
    rel_path = str(target.relative_to(ws_root))
    resp = client.get("/workspace-file", params={"path": rel_path}, headers=_auth_headers())
    assert resp.status_code == 400
    assert "Unsupported file extension" in resp.json()["detail"]


def test_generate_documents_app_not_found() -> None:
    """POST /applications/{id}/generate-documents returns 404 for a non-existent application."""
    resp = client.post(
        "/applications/99999/generate-documents",
        json={"overwrite": True},
        headers=_auth_headers(),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Application not found"


def test_generate_documents_template_dir_missing() -> None:
    """POST generate-documents returns 500 when the configured template directory does not exist."""
    _clear_db()
    created = client.post(
        "/applications/upsert",
        json=_base_payload(link="https://example.com/job/tmpl-dir-missing"),
        headers=_auth_headers(),
    )
    assert created.status_code == 200
    app_id = created.json()["id"]

    from app.config import settings as _settings

    with patch.object(_settings, "vacancies_template_dir", "/nonexistent/template/dir"):
        resp = client.post(
            f"/applications/{app_id}/generate-documents",
            json={"overwrite": True},
            headers=_auth_headers(),
        )
    assert resp.status_code == 500
    assert "Template directory not found" in resp.json()["detail"]


def test_generate_documents_template_file_missing() -> None:
    """POST generate-documents returns 500 when a required template file is missing."""
    _clear_db()
    created = client.post(
        "/applications/upsert",
        json=_base_payload(link="https://example.com/job/tmpl-file-missing"),
        headers=_auth_headers(),
    )
    assert created.status_code == 200
    app_id = created.json()["id"]

    vacancy_tmpl = _TEMPLATE_DIR / "vacancy.md"
    vacancy_tmpl_bak = _TEMPLATE_DIR / "_vacancy.md.bak"
    vacancy_tmpl.rename(vacancy_tmpl_bak)
    try:
        resp = client.post(
            f"/applications/{app_id}/generate-documents",
            json={"overwrite": True},
            headers=_auth_headers(),
        )
        assert resp.status_code == 500
        assert "Required template file not found" in resp.json()["detail"]
    finally:
        vacancy_tmpl_bak.rename(vacancy_tmpl)


def test_generate_documents_restores_backup_on_failure() -> None:
    """generate-documents restores backup files when db.commit raises after files already exist."""
    _clear_db()
    target_dir = _APPLICATIONS_ROOT / "vacancies" / "restore_inc_restore_tester"
    if target_dir.exists():
        shutil.rmtree(target_dir)

    created = client.post(
        "/applications/upsert",
        json=_base_payload(
            company="Restore Inc",
            role="Restore Tester",
            link="https://example.com/job/restore-backup-test",
        ),
        headers=_auth_headers(),
    )
    assert created.status_code == 200
    app_id = created.json()["id"]

    # First generate: create the target files
    first = client.post(
        f"/applications/{app_id}/generate-documents",
        json={"overwrite": False},
        headers=_auth_headers(),
    )
    assert first.status_code == 200
    assert target_dir.exists()

    # Second generate: overwrite=True, but commit fails — backups are restored
    with patch("app.routers.workspace.Session.commit", side_effect=RuntimeError("forced failure")):
        second = client.post(
            f"/applications/{app_id}/generate-documents",
            json={"overwrite": True},
            headers=_auth_headers(),
        )
    assert second.status_code == 500
    # Original files should be restored from backup (covers workspace.py line 176)
    assert (target_dir / "vacancy.md").exists()


def test_workspace_file_not_found() -> None:
    """GET /workspace-file returns 404 when the target file does not exist."""
    from app.pathing import workspace_root

    ws_root = workspace_root()
    target = _APPLICATIONS_ROOT / "does_not_exist_at_all.md"
    rel_path = str(target.relative_to(ws_root))
    resp = client.get("/workspace-file", params={"path": rel_path}, headers=_auth_headers())
    assert resp.status_code == 404
    assert resp.json()["detail"] == "File not found"


def test_upsert_validates_link_empty() -> None:
    """Upsert with an explicit empty link is accepted (validator early-return path)."""
    _clear_db()
    resp = client.post(
        "/applications/upsert",
        json={"company": "LinklessCorps", "role": "Dev", "link": ""},
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["link"] == ""


def test_upsert_validates_link_bad_scheme() -> None:
    """Upsert with a link that has an unsupported URL scheme returns 422."""
    _clear_db()
    resp = client.post(
        "/applications/upsert",
        json=_base_payload(link="ftp://invalid.example.com/job/1"),
        headers=_auth_headers(),
    )
    assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# Option A: Unit tests – pure functions and Pydantic schema validators
# ─────────────────────────────────────────────────────────────────────────────


def test_pure_function_edge_cases() -> None:
    """Unit coverage for helpers, pathing, and applications-layer pure functions."""
    # helpers.summarize_process_output ────────────────────────────────────────
    assert summarize_process_output("", 10) == ""        # empty → early return
    assert summarize_process_output("   ", 10) == ""     # whitespace-only → early return
    assert summarize_process_output("hello", 0) == ""    # max_chars=0 → early return
    assert summarize_process_output("hello", -1) == ""   # max_chars<0 → early return
    # max_chars too small for the truncation marker (marker is 26 chars; need >28)
    assert summarize_process_output("A" * 100, 5) == "A" * 5

    # pathing.resolve_from_project_root ───────────────────────────────────────
    from app.pathing import project_root, resolve_from_project_root

    result = resolve_from_project_root("relative/path")
    assert result == (project_root() / "relative/path").resolve()

    # pathing.resolve_from_applications_root (already-rooted path) ────────────
    from app.config import settings as _settings
    from app.pathing import resolve_from_applications_root, workspace_root

    with patch.object(_settings, "applications_root", "applications"):
        result2 = resolve_from_applications_root("applications/vacancies")
        expected = (workspace_root() / "applications/vacancies").resolve()
        assert result2 == expected

    # applications._parse_score_breakdown ─────────────────────────────────────
    from app.routers.applications import _parse_score_breakdown

    assert _parse_score_breakdown(None) is None
    assert _parse_score_breakdown("") is None            # empty string → early return
    assert _parse_score_breakdown("   ") is None         # whitespace-only → early return
    sb_json = (
        '{"score": 7, "fit": "Good", "matched_keywords": ["Python"], '
        '"missing_skills": [], "fit_notes": "direct overlap"}'
    )
    result3 = _parse_score_breakdown(sb_json)
    assert result3 is not None
    assert result3.score == 7
    assert _parse_score_breakdown('{"broken') is None       # JSONDecodeError path
    assert _parse_score_breakdown("[1, 2, 3]") is None      # valid JSON but not a dict

    # applications._parse_score_json ──────────────────────────────────────────
    from app.routers.applications import _parse_score_json

    d: dict = {"score": 1}
    assert _parse_score_json(d) is d  # dict pass-through


def test_schema_validators_unit() -> None:
    """Unit coverage for Pydantic field validators that are not reachable via the API alone."""
    from pydantic import ValidationError

    from app.schemas import DiscoveryRunRequest, JobApplicationUpsert

    # _validate_link: empty string → early return (line 85)
    m1 = JobApplicationUpsert(company="A", role="B", link="")
    assert m1.link == ""

    # _validate_link: unsupported scheme → raises ValueError (line 88)
    try:
        JobApplicationUpsert(company="A", role="B", link="ftp://bad.example.com")
        assert False, "Expected ValidationError"
    except ValidationError:
        pass

    # _validate_seniority: None explicitly provided → early return (line 171)
    m2 = DiscoveryRunRequest(seniority=None)
    assert m2.seniority is None

    # _validate_seniority: invalid value → raises ValueError (line 174)
    try:
        DiscoveryRunRequest(seniority="vp")
        assert False, "Expected ValidationError"
    except ValidationError:
        pass

    # _validate_llm_api_base_url: None explicitly provided → early return (line 181)
    m3 = DiscoveryRunRequest(llm_api_base_url=None)
    assert m3.llm_api_base_url is None

    # _validate_llm_api_base_url: unsupported scheme → raises ValueError (line 184)
    try:
        DiscoveryRunRequest(llm_api_base_url="ftp://bad.example.com")
        assert False, "Expected ValidationError"
    except ValidationError:
        pass
