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
- `discovery/cli.py` in this repo is a compatibility wrapper for subprocess mode.

## Configuration
- Main app env: `.env` / `.env.example`
- Discovery behavior override config: `discovery/discovery_config.json`
  - Override path via `DISCOVERY_CONFIG_PATH`

## Runtime flow
1. Frontend triggers `POST /run-discovery`.
2. Backend validates request and executes discovery via the extracted `job_discovery_engine` package (module mode) or the app wrapper `discovery/cli.py` (subprocess mode).
3. Discovery collects sources, scores, applies optional priors/LLM reranking.
4. Discovery writes tracker artifacts and upserts shortlist rows via API.
5. Frontend reloads applications and analytics.

## Stability guardrails
- Keep CLI/API/UI options synchronized whenever discovery arguments change.
- Prefer additive schema changes to keep old rows and payloads compatible.
- Run backend tests and frontend tests/build on every structural change.
- Avoid adding app-specific discovery details here; use the contract and extraction docs instead.
