# Job Application Insights

[![CI](https://github.com/Sergei-Volkov/job-application-insights/actions/workflows/ci.yml/badge.svg)](https://github.com/Sergei-Volkov/job-application-insights/actions/workflows/ci.yml)

FastAPI + React dashboard for tracking job applications, running discovery, and generating vacancy-specific documents.

## Linked Submodule
- `job-discovery-engine/` is a git submodule linked to `https://github.com/Sergei-Volkov/job-discovery-engine`.
- After cloning this repo, initialize/update submodules:

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
- The API initializes schema automatically only when the database/tables are missing.
- Manual initialization is still available: `cd backend && python -m app.init_db`.
- `applications/` is mounted into the backend container for tracker and document files.

## Fast Setup (5-10 Minutes)
1. Copy env: `cp .env.example .env`
2. (Optional) set `WRITE_API_KEY` and `REQUIRE_WRITE_KEY=true` if you want write protection.
3. Set `DISCOVERY_CV_PATH` in `.env` to your base CV, for example `applications/resumes/CV.tex`.
4. Start app: `docker compose up --build`
5. Open dashboard at `http://localhost:3000` and run discovery.

Discovery engine dependency:
- Discovery logic now lives in the linked `job-discovery-engine/` repo and is also installed as a pinned backend dependency.
- Backend installs it from `backend/requirements.txt` (pinned release).

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
- `discovery/cli.py` in this repo is only a thin compatibility wrapper.
- Local override config remains at `discovery/discovery_config.json` and can be enabled with `DISCOVERY_CONFIG_PATH`.
- Discovery artifacts are written to `applications/tracker/`.

## Environment variables
| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./app.db` | SQLAlchemy connection string |
| `CORS_ORIGINS` | `[...]` | Allowed frontend origins |
| `WRITE_API_KEY` | _(empty)_ | Optional key for write endpoints |
| `REQUIRE_WRITE_KEY` | `false` | Require `X-API-Key` when true |
| `DISCOVERY_SCRIPT_PATH` | `discovery/cli.py` | Discovery script location |
| `DISCOVERY_CV_PATH` | _(empty)_ | Fallback CV path for discovery runs |
| `DISCOVERY_RUNNER_MODE` | `subprocess` | Discovery execution mode (`subprocess` or `module`) |
| `DISCOVERY_CONFIG_PATH` | `discovery/discovery_config.json` | Optional discovery config override file |
| `OPENAI_API_KEY` or `LLM_API_KEY` | _(empty)_ | Optional key for LLM reranker |
| `LLM_API_BASE_URL` | `https://api.openai.com/v1` | Optional base URL for OpenAI-compatible reranker API |
| `LLM_MODEL` | `gpt-4o-mini` | Default model used by LLM reranker |
| `APPLICATIONS_ROOT` | `applications` | Root for generated docs and file APIs |
| `VACANCIES_TEMPLATE_DIR` | `vacancies/_template` | Template dir relative to `APPLICATIONS_ROOT` (or absolute path) |
| `BASE_CV_TEMPLATE_PATH` | `resumes/CV.tex` | Base CV path relative to `APPLICATIONS_ROOT` (or absolute path) |

## Discovery Runner Modes
- `subprocess`:
	- Backend executes `DISCOVERY_SCRIPT_PATH`.
	- Most explicit path for debugging command args and logs.
- `module`:
	- Backend imports `job_discovery_engine` directly.
	- Recommended once backend dependencies are installed and stable.
