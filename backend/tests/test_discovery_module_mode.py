from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_APP_ROOT = Path(__file__).resolve().parents[2]
for path in (str(_BACKEND_ROOT), str(_APP_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


def _auth_headers() -> dict[str, str]:
    return {"X-API-Key": "test-key"}


def test_run_discovery_module_mode_uses_public_api(monkeypatch) -> None:
    original_mode = settings.discovery_runner_mode
    try:
        settings.discovery_runner_mode = "module"

        class FakeOptions:
            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs

        fake_result = SimpleNamespace(
            strict_matches=[],
            broad_matches=[],
            llm_report=SimpleNamespace(dry_run=False, planned_calls=0, attempted=0, adjusted=0, used_input_chars=0),
            synced_count=0,
            failed_rows=[],
        )
        fake_warnings = SimpleNamespace(messages=["module mode ok"])

        fake_module = SimpleNamespace(
            DiscoveryRunOptions=FakeOptions,
            run_discovery_pipeline=lambda options: (fake_result, fake_warnings),
        )
        monkeypatch.setattr("app.routers.discovery.importlib.import_module", lambda name: fake_module)

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
    finally:
        settings.discovery_runner_mode = original_mode
