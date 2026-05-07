# Job Application Insights

A job application tracking and analytics system with a Python API and React dashboard.

## Stack
- Backend: FastAPI + SQLAlchemy + Pydantic Settings (Python)
- Frontend: React + TypeScript + Recharts (Vite)
- Proxy: nginx (production Docker)
- Config: environment variables via `.env`

On first startup, the backend seeds a local SQLite database from CSV.
A bundled sample CSV (`data/job_applications_sample.csv`) seeds the database on first startup so the charts are populated immediately. Replace it with your own CSV or use `POST /sync-from-csv` to load data later.

## Run with Docker (recommended)

```bash
cp .env.example .env
# Optional: set DISCOVERY_CV_PATH in .env to enable /run-discovery
docker compose up --build
```

- Dashboard: http://localhost:3000
- API docs: http://localhost:8000/docs
- Alternative docs: http://localhost:8000/redoc

## Run locally (dev mode)

```powershell
# Backend
cd backend
pip install -r requirements.txt
cp ../.env.example .env       # adjust CSV_PATH / DISCOVERY_CV_PATH as needed
uvicorn app.main:app --reload
```

```bash
# Frontend (separate terminal)
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

Vite proxies `/api/*` to the local FastAPI backend automatically.

## API endpoints
- `GET /health`
- `GET /stats`
- `GET /missing-skills`
- `GET /trend`
- `GET /applications?min_fit_score=10&status=to+review&limit=20`
- `POST /applications/upsert`
- `PATCH /applications/{id}`
- `POST /run-discovery`
- `POST /sync-from-csv`

## API usage examples

OpenAPI docs are available at `/docs` and `/redoc`. The endpoint schemas are typed, so the request and response bodies are visible directly in FastAPI.

Create or update one discovered job:

```bash
curl -X POST http://localhost:8000/applications/upsert \
	-H "Content-Type: application/json" \
	-d '{
		"company": "Example Inc",
		"role": "Backend Engineer",
		"source": "manual",
		"fit": "Strong",
		"fit_score": 12,
		"link": "https://example.com/jobs/123",
		"status": "To review",
		"notes": "Strong Python overlap. missing or adjacent tools: Terraform, GCP."
	}'
```

Patch tracked application details from the UI or a script:

```bash
curl -X PATCH http://localhost:8000/applications/1 \
	-H "Content-Type: application/json" \
	-d '{
		"selected": "yes",
		"date_applied": "2026-05-07",
		"status": "Applied",
		"resume_ref": "resume_v2.pdf",
		"cover_letter_ref": "cover_letter_v2.md"
	}'
```

Import legacy CSV rows into the DB:

```bash
curl -X POST http://localhost:8000/sync-from-csv
```

Run the external discovery script through the API:

```bash
curl -X POST http://localhost:8000/run-discovery \
	-H "Content-Type: application/json" \
	-d '{
		"limit": 40,
		"min_score": 7,
		"max_age_days": 45,
		"include_stretch": false
	}'
```

## Config (env vars)
| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./app.db` | SQLAlchemy connection string |
| `CSV_PATH` | `data/job_applications_sample.csv` | Path to CSV used for first-run DB seeding |
| `DEFAULT_MISSING_SKILLS` | `Kubernetes,Redis,...` | Fallback skill list when notes lack gap markers |
| `CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated allowed frontend origins |
| `CORS_ALLOW_CREDENTIALS` | `false` | Enables credentialed CORS requests |
| `WRITE_API_KEY` | _(empty)_ | Optional API key required for write/execute endpoints (`X-API-Key`) |
| `DISCOVERY_SCRIPT_PATH` | `discovery/job_finder.py` | Discovery script path inside this repo |
| `DISCOVERY_CV_PATH` | _(empty)_ | Required: path to your CV passed to discovery |
| `DISCOVERY_API_BASE_URL` | `http://127.0.0.1:8000` | API base URL used by the discovery script for upserts |
| `DISCOVERY_LOG_MAX_CHARS` | `3000` | Max stdout/stderr chars returned by `/run-discovery` |

## Operational Notes
1. The API starts with SQLite and seeds data from `CSV_PATH` only when the database is empty.
2. `/run-discovery` requires `DISCOVERY_CV_PATH` to be configured and point to an existing file.
3. If `WRITE_API_KEY` is configured, send it via `X-API-Key` for `POST`/`PATCH` write endpoints.
4. `/run-discovery` response logs are summarized and truncated by `DISCOVERY_LOG_MAX_CHARS`.
5. The frontend reads and writes application state through `/api/*` proxied to the backend.
6. OpenAPI docs are available at `/docs` and `/redoc`.

