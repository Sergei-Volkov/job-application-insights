import os
from pathlib import Path
import sys
from unittest.mock import patch

from fastapi.testclient import TestClient

_TMP_DIR = Path(__file__).resolve().parent / ".tmp"
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

_TMP_DIR.mkdir(parents=True, exist_ok=True)
_SEED_CSV = _TMP_DIR / "seed.csv"
_CV_PATH = _TMP_DIR / "cv.tex"
_DB_PATH = _TMP_DIR / "test.db"

_SEED_CSV.write_text(
    "selected,date_found,date_applied,company,role,location,source,remote_type,fit,fit_score,link,status,next_step,follow_up_date,notes\n",
    encoding="utf-8",
)
_CV_PATH.write_text("Python SQL FastAPI", encoding="utf-8")

if _DB_PATH.exists():
    _DB_PATH.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH.as_posix()}"
os.environ["CSV_PATH"] = str(_SEED_CSV)
os.environ["DISCOVERY_CV_PATH"] = str(_CV_PATH)
os.environ["WRITE_API_KEY"] = "test-key"
os.environ["DISCOVERY_LOG_MAX_CHARS"] = "80"

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import JobApplication  # noqa: E402

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

    with patch("app.main.subprocess.run", return_value=Completed()):
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
