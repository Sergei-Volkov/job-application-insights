import os
from datetime import datetime
from pathlib import Path
import shutil
import sys
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
os.environ["DISCOVERY_LOG_MAX_CHARS"] = "80"
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

    rows = result.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "Applied"


def test_run_discovery_output_is_summarized() -> None:
    _clear_db()

    class Completed:
        returncode = 0
        stdout = "A" * 600
        stderr = "B" * 600

    with patch("app.routers.discovery.subprocess.run", return_value=Completed()):
        response = client.post(
            "/run-discovery",
            json={"limit": 5, "min_score": 1, "max_age_days": 10, "include_stretch": False},
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()

    assert "output truncated" in data["stdout"]
    assert "output truncated" in data["stderr"]
    assert len(data["stdout"]) <= 80
    assert len(data["stderr"]) <= 80


def test_run_discovery_forwards_profile_mode() -> None:
    _clear_db()

    class Completed:
        returncode = 0
        stdout = "ok"
        stderr = ""

    with patch("app.routers.discovery.subprocess.run", return_value=Completed()) as mocked:
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
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    command = mocked.call_args.kwargs["args"] if "args" in mocked.call_args.kwargs else mocked.call_args[0][0]
    assert "--profile" in command
    assert "swe" in command
    assert "--api-base-url" in command
    assert "http://127.0.0.1:8000" in command
    assert "--verbose" in command


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


def test_health_and_stats_endpoints() -> None:
    _clear_db()

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

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


def test_startup_bootstraps_missing_schema() -> None:
    class FakeInspector:
        def has_table(self, table_name: str) -> bool:
            return False

    with patch("app.main.inspect", return_value=FakeInspector()) as mocked_inspect, patch(
        "app.main.init_db"
    ) as mocked_init_db:
        with TestClient(app) as fresh_client:
            response = fresh_client.get("/health")

    assert response.status_code == 200
    mocked_inspect.assert_called_once()
    mocked_init_db.assert_called_once()


def test_path_and_helper_sanity() -> None:
    assert applications_root() == _APPLICATIONS_ROOT
    assert resolve_from_applications_root("vacancies/_template") == _TEMPLATE_DIR
    assert is_within_path(_TEMPLATE_DIR, _APPLICATIONS_ROOT)
    assert safe_relative_path(_TEMPLATE_DIR, _APPLICATIONS_ROOT) == "vacancies/_template"

    assert slugify("  Foo bar!!  ") == "foo_bar"
    assert summarize_process_output("abc", 10) == "abc"

    truncated = summarize_process_output("A" * 600, 80)
    assert "output truncated" in truncated
    assert len(truncated) <= 80
    assert today_iso() == datetime.now().strftime("%Y-%m-%d")


def test_run_discovery_failure_truncates_stderr() -> None:
    _clear_db()

    class Completed:
        returncode = 1
        stdout = "ok"
        stderr = "Z" * 600

    with patch("app.routers.discovery.subprocess.run", return_value=Completed()):
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
    assert "Discovery script failed with exit code 1" in detail
    assert "output truncated" in detail
    assert len(detail) <= 500
