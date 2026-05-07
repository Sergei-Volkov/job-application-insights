# Job Application Insights (Portfolio MVP)

A fullstack showcase: Python API + React dashboard — built around real job-search data.

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
| `DEFAULT_MISSING_SKILLS` | `dbt,BigQuery,...` | Fallback skill list when notes lack gap markers |
| `CORS_ORIGINS` | `*` | Comma-separated allowed frontend origins |
| `DISCOVERY_SCRIPT_PATH` | `discovery/job_finder.py` | Discovery script path inside this repo |
| `DISCOVERY_CV_PATH` | _(empty)_ | Required: path to your CV passed to discovery |
| `DISCOVERY_API_BASE_URL` | `http://127.0.0.1:8000` | API base URL used by the discovery script for upserts |

## Demo flow (for interviews)
1. Open dashboard — show live data from your real tracker
2. Walk through the skill gaps chart — explain how it drives your upskilling roadmap
3. Show the weekly trend chart — demonstrates time-series reasoning
4. Open `/docs` — show auto-generated API docs from Pydantic schemas
5. Mention: FastAPI startup event seeds SQLite from CSV, zero manual setup needed

