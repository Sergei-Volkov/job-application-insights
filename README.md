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
- Data import is explicit via `POST /sync-from-csv`.
- `applications/` is mounted into the backend container for tracker and document files.

## Run locally

```powershell
# Backend
cd backend
pip install -r requirements.txt
cd ..
.\run_backend_dev.ps1
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
- `POST /sync-from-csv`
- `POST /run-discovery`
- `POST /applications/{id}/generate-documents`
- `GET /workspace-file`
- `PUT /workspace-file`

## Environment variables
| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./app.db` | SQLAlchemy connection string |
| `CSV_PATH` | `applications/tracker/job_applications.csv` | CSV imported by `/sync-from-csv` |
| `CORS_ORIGINS` | `[...]` | Allowed frontend origins |
| `WRITE_API_KEY` | _(empty)_ | Optional key for write endpoints |
| `REQUIRE_WRITE_KEY` | `false` | Require `X-API-Key` when true |
| `DISCOVERY_SCRIPT_PATH` | `discovery/job_finder.py` | Discovery script location |
| `DISCOVERY_CV_PATH` | _(empty)_ | Fallback CV path for discovery runs |
| `APPLICATIONS_ROOT` | `applications` | Root for generated docs and file APIs |
