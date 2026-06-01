# Architecture Overview

This file summarizes the app structure and points discovery readers to the frozen contract.

## Backend
- Path: `backend/app/`
- Entry point: `main.py`
- Core modules:
  - `routers/`: API surfaces (`applications`, `analytics`, `discovery`, `workspace`, `system`)
  - `config.py`: runtime settings from env
  - `database.py`, `models.py`, `schemas.py`: data layer and API contracts
  - `dependencies.py`: DB session and write-key guard
  - `pathing.py`: path resolution helpers and traversal-safety guard (`is_within_path`)
  - `init_db.py`: Alembic migration runner, called at startup to keep the schema current
  - `helpers.py`: pure utilities (slugify, date helpers, output truncation)

## Frontend
- Path: `frontend/src/`
- Entry point: `App.tsx`
- Core modules:
  - `api.ts`: typed API client contracts
  - `appTypes.ts`, `appConstants.ts`: shared frontend typing/constants
  - `utils/`: listing filters, document paths, previews

## Discovery
- Discovery logic is owned by the external `job-discovery-engine` package.
- This app should only consume discovery through that package boundary.

## Configuration
- Main app env: `.env` / `.env.example`
- Discovery uses package defaults by default.
- Optional local override path can be provided via `DISCOVERY_CONFIG_PATH`.

## Setup quick map
1. Copy `.env.example` to `.env`.
2. Set `DISCOVERY_CV_PATH` so discovery can infer owned skills.
3. Optionally enable write-key protection (`WRITE_API_KEY`, `REQUIRE_WRITE_KEY=true`).
4. Start with `docker compose up --build`.

## Runtime flow
1. Frontend triggers `POST /run-discovery`.
2. Backend validates request and executes discovery via the extracted `job_discovery_engine` package.
3. Discovery collects sources, scores, applies optional priors/LLM reranking.
4. Discovery writes tracker artifacts and upserts shortlist rows via API.
5. Frontend reloads applications and analytics.

## Stability guardrails
- Keep CLI/API/UI options synchronized whenever discovery arguments change.
- Prefer additive schema changes to keep old rows and payloads compatible.
- Run backend tests and frontend tests/build on every structural change.
- Avoid adding app-specific discovery details here; use the contract and extraction docs instead.

## Runtime caveats
- Discovery endpoint is single-flight and rate-limited to prevent accidental duplicate executions.
- Discovery logs are sanitized before returning verbose output.
- Missing or invalid CV path fails fast with a 400 response to avoid partial runs.
