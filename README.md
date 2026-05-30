# Job Application Insights

[![CI](https://github.com/Sergei-Volkov/job-application-insights/actions/workflows/ci.yml/badge.svg)](https://github.com/Sergei-Volkov/job-application-insights/actions/workflows/ci.yml)

FastAPI + React dashboard for tracking job applications, running discovery, and generating vacancy-specific documents.

## Linked Submodule
- `job-discovery-engine/` is a git submodule linked to `https://github.com/Sergei-Volkov/job-discovery-engine`.
- Preferred clone command (fetches submodules immediately):

```bash
git clone --recurse-submodules https://github.com/Sergei-Volkov/job-application-insights
```

- If you already cloned without submodules, initialize/update them with:

```bash
git submodule update --init --recursive
```

## What This App Does
- Tracks applications in a single dashboard.
- Runs discovery and syncs shortlisted jobs into the tracker.
- Generates vacancy folders with tailored document stubs.
- Keeps all editable materials under `../applications/`.

## Architecture map
- See `ARCHITECTURE.md` for a concise map of backend, frontend, and discovery modules and data flow.

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
- Initialize schema once before first run: `docker compose run --rm backend python -m app.init_db`.
- `applications/` is mounted into the backend container for tracker and document files.

## Fast Setup (5-10 Minutes)
1. Clone with submodule: `git clone --recurse-submodules https://github.com/Sergei-Volkov/job-application-insights`
2. Enter app folder: `cd app`
3. Copy env: `cp .env.example .env`
4. Set `DISCOVERY_CV_PATH` in `.env` (for example `applications/resumes/CV.tex`).
5. Optional write protection: set `WRITE_API_KEY=<your-key>` and `REQUIRE_WRITE_KEY=true`.
6. Initialize DB once: `docker compose run --rm backend python -m app.init_db`
7. Start app: `docker compose up --build`
8. Open dashboard at `http://localhost:3000` and run discovery.

Discovery engine dependency:
- Discovery logic now lives in the linked `job-discovery-engine/` repo and is also installed as a pinned backend dependency.
- Backend installs it from `backend/requirements.txt` (pinned release).

## Run locally

```bash
# Backend
cd backend
pip install -r requirements.txt
python -m app.init_db
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-include "*.py" --reload-include "*.md" --reload-include "*.tex" --reload-include ".env"
```

```bash
# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

## Discovery request examples

Minimal run (backend fallback values from `.env`):

```bash
curl -X POST http://127.0.0.1:8000/run-discovery \
	-H "Content-Type: application/json" \
	-H "X-API-Key: <WRITE_API_KEY>" \
	-d '{"limit": 40, "min_score": 7, "max_age_days": 45, "include_stretch": false}'
```

Profile + reranker run:

```bash
curl -X POST http://127.0.0.1:8000/run-discovery \
	-H "Content-Type: application/json" \
	-H "X-API-Key: <WRITE_API_KEY>" \
	-d '{
		"profile": "swe",
		"use_llm_reranker": true,
		"llm_top_n": 12,
		"llm_dry_run": true,
		"verbose": true
	}'
```

## Stability checklist
Run this quick verification before and after larger refactors:

```bash
# Backend tests
cd backend && pytest -q

# Frontend tests + build
cd ../frontend && npm test -- --run && npm run build

# Discovery CLI surface check
cd .. && python discovery/cli.py --help
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

Discovery contract and caveats:
- Canonical discovery contract lives in `job-discovery-engine` (`API_CONTRACT.md`).
- By default discovery uses package defaults from `job_discovery_engine`.
- Optional local override: copy `discovery/discovery_config.override.example.json` to `discovery/discovery_config.override.json` and set `DISCOVERY_CONFIG_PATH`.
- Discovery artifacts are written to `applications/tracker/`.

## Common caveats
- `POST /run-discovery` requires a valid CV path: either send `cv_path` in request or set `DISCOVERY_CV_PATH` in `.env`.
- If `REQUIRE_WRITE_KEY=true`, write endpoints require `X-API-Key` header.
- Discovery endpoint is intentionally rate-limited and single-flight to prevent duplicate runs from repeated clicks.
- LLM reranker needs `OPENAI_API_KEY` or `LLM_API_KEY`; without keys use `llm_dry_run=true`.

## Environment variables
| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./app.db` | SQLAlchemy connection string |
| `CORS_ORIGINS` | `[...]` | Allowed frontend origins |
| `WRITE_API_KEY` | _(empty)_ | Optional key for write endpoints |
| `REQUIRE_WRITE_KEY` | `false` | Require `X-API-Key` when true |
| `DISCOVERY_CV_PATH` | _(empty)_ | Fallback CV path for discovery runs |
| `DISCOVERY_CONFIG_PATH` | _(empty)_ | Optional path to local discovery config override JSON |
| `OPENAI_API_KEY` or `LLM_API_KEY` | _(empty)_ | Optional key for LLM reranker |
| `LLM_API_BASE_URL` | `https://api.openai.com/v1` | Optional base URL for OpenAI-compatible reranker API |
| `LLM_MODEL` | `gpt-4o-mini` | Default model used by LLM reranker |
| `APPLICATIONS_ROOT` | `applications` | Root for generated docs and file APIs |
| `VACANCIES_TEMPLATE_DIR` | `vacancies/_template` | Template dir relative to `APPLICATIONS_ROOT` (or absolute path) |
| `BASE_CV_TEMPLATE_PATH` | `resumes/CV.tex` | Base CV path relative to `APPLICATIONS_ROOT` (or absolute path) |

## Discovery Runner
- The app runs discovery in module mode only.
- Backend imports `job_discovery_engine` directly and executes `run_discovery_pipeline`.
