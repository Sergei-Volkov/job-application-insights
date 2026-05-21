# Job Application Insights

[![CI](https://github.com/Sergei-Volkov/job-application-insights/actions/workflows/ci.yml/badge.svg)](https://github.com/Sergei-Volkov/job-application-insights/actions/workflows/ci.yml)

FastAPI + React dashboard for tracking job applications, running discovery, and generating vacancy-specific documents.

## Stack
- Backend: FastAPI, SQLAlchemy
- Frontend: React, TypeScript, Vite
- Local DB: SQLite

## Run with Docker

```bash
cp .env.example .env
docker compose up --build
```

- Frontend: http://localhost:3000
- API docs: http://localhost:8000/docs

Notes:
- The API initializes schema automatically only when the database/tables are missing.
- Manual initialization is still available: `cd backend && python -m app.init_db`.
- `applications/` is mounted into the backend container for tracker and document files.

## Run locally

```bash
# Backend
cd backend
pip install -r requirements.txt
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload --reload-include "*.py" --reload-include "*.md" --reload-include "*.tex" --reload-include ".env"
```

```bash
# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

## Key endpoints
- `GET /health`
- `GET /applications`
- `POST /applications/upsert`
- `PATCH /applications/{id}`
- `POST /run-discovery`
- `POST /applications/{id}/generate-documents`
- `GET /workspace-file`
- `PUT /workspace-file`

## Workflow

1. Start backend and frontend.
2. Open the dashboard and run discovery from the UI (this calls `POST /run-discovery`).
3. Review discovered roles in the UI and update status/notes.
4. Generate vacancy-specific documents for selected roles.
5. Repeat discovery periodically.

Discovery rerun behavior:
- Discovery rewrites generated tracker artifacts each run:
	- `applications/tracker/job_matches_latest.md`
	- `applications/tracker/job_matches_broad.md`
	- `applications/tracker/application_notes_latest.md`
	- `applications/tracker/selected_jobs.md` (preserves existing checkbox state when company+role still match)
- Discovery also writes a new timestamped export every run:
	- `applications/tracker/job_matches_YYYYMMDD_HHMM.csv`
- Database rows are upserted, not blindly duplicated:
	- Existing rows are matched by link, or by company+role when link is missing.
	- Matching rows are updated and `last_seen_at` is refreshed.
	- New rows are created only when no match is found.

## Environment variables
| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./app.db` | SQLAlchemy connection string |
| `CORS_ORIGINS` | `[...]` | Allowed frontend origins |
| `WRITE_API_KEY` | _(empty)_ | Optional key for write endpoints |
| `REQUIRE_WRITE_KEY` | `false` | Require `X-API-Key` when true |
| `DISCOVERY_SCRIPT_PATH` | `discovery/cli.py` | Discovery script location |
| `DISCOVERY_CV_PATH` | _(empty)_ | Fallback CV path for discovery runs |
| `APPLICATIONS_ROOT` | `applications` | Root for generated docs and file APIs |
| `VACANCIES_TEMPLATE_DIR` | `vacancies/_template` | Template dir relative to `APPLICATIONS_ROOT` (or absolute path) |
| `BASE_CV_TEMPLATE_PATH` | `resumes/CV.tex` | Base CV path relative to `APPLICATIONS_ROOT` (or absolute path) |
