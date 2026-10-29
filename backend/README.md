# MediPredict API

This project exposes its functionality through a FastAPI backend and a React dashboard in `frontend/`. The Vite development server proxies `/api` requests to the FastAPI backend.

For Aiven PostgreSQL and Cloudflare R2, first copy `backend/.env.example` to `backend/.env`, fill in the Aiven connection URL and R2 bucket, endpoint, credentials, and dashboard CSV object key, then set `MEDIPREDICT_STORAGE_BACKEND=s3`. URL-encode special characters in the database password and keep all credentials in the ignored `.env` file. When the dashboard object is missing, the API seeds that exact key from `MEDIPREDICT_CSV_PATH` if the configured local CSV is available; otherwise upload the dashboard CSV to R2 first. Existing keys are immutable and are never overwritten.

If the Aiven database is new and empty, verify the connection URL points to the intended database, then apply the existing schema from the repository root:

```powershell
.\backend\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini upgrade head
```

Do not run this against a database containing existing application tables until its schema and migration state have been checked. Start the API from the repository root; it loads `backend/.env` automatically:

```powershell
.\backend\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --port 8000
```

For the CSV-only local dashboard without connecting to SQLite or R2, set `$env:MEDIPREDICT_DATABASE_ENABLED = "false"` before starting the API. In another terminal, run `Set-Location frontend` and `npm run dev`.

Open `http://localhost:5173` for the dashboard, `http://localhost:8000/docs` for Swagger UI, or `http://localhost:8000/openapi.json` for the OpenAPI schema.

This mode uses the repository CSV and local files. Database-backed alert dispatch and dataset registry/provenance administration return HTTP 503. It does not create a SQLite schema, open a database connection, or modify/delete the local SQLite database. Set `MEDIPREDICT_DATABASE_ENABLED=true` to retain the full SQLite-backed behavior; that remains the default.

API routes are under `/api/v1`. The development frontend uses `http://localhost:8000` as its API proxy target. Set `MEDIPREDICT_CORS_ORIGINS` only when browser clients on other origins need access. Inventory, consumption, and risk predictions currently use synthetic demonstration data; district indicators are unverified seed values.

The current legacy model artifact is not accepted as validated: it lacks required time-based validation metadata and an artifact SHA-256. Assessments therefore use the explicitly labeled rule-based days-of-cover fallback, and confidence is not reported. Do not run the legacy training script or present its metrics as predictive performance.

Uploads to `POST /api/v1/data/assess-csv` are assessed by the backend and stored in configured object storage under a content-addressed key with a SHA-256-checked metadata record; they are not persisted to `DailyStockLog` or `Prediction`. Their `is_synthetic` provenance is preserved and never inferred. `POST /api/v1/data/validate-csv` only returns a structured validation report. `POST /api/v1/data/training-upload` is a distinct, admin-key-protected intake route that stores a validated dataset and metadata, then queues the leakage-safe `ml` candidate-training pipeline.

When `MEDIPREDICT_DATABASE_ENABLED=false`, the CSV assessment and validation endpoints remain available, while training upload, dataset registry/provenance administration, and alert notification dispatch return HTTP 503. Assessment CSVs still use the configured local or S3 storage backend. Set database enablement to `true` (the default) to enable database-backed features.

### Database provenance migration

Alembic baseline and provenance migration files are prepared under `backend/migrations/`; they have not yet been applied. The provenance migration adds nullable `is_synthetic` and `data_source` columns to `daily_stock_logs` and `predictions`, and backfills existing rows with `is_synthetic=true` and `data_source="synthetic"`. Before applying to the live SQLite database, stamp the verified existing schema at the baseline, take and integrity-check a backup in the ignored `backups/` folder, then upgrade. The provenance migration can be downgraded without dropping or recreating application tables. Uploaded assessment and training-intake files remain separate from those database tables. See `docs/data_contract.md` for the CSV contract and endpoints.

### Aiven and R2 dataset and candidate workflow

With the Aiven URL, `MEDIPREDICT_DATABASE_ENABLED=true`, and `MEDIPREDICT_STORAGE_BACKEND=s3` plus R2 credentials configured in `backend/.env`, apply migrations only after confirming the target database is empty or at the expected Alembic revision:

```powershell
.\backend\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini upgrade head
```

Archive the current dashboard CSV unchanged (it is synthetic and not training-eligible):

```powershell
.\backend\.venv\Scripts\python.exe -m ml.archive_dashboard_csv
```

The API's `POST /api/v1/data/training-upload` stores a validated source CSV and its metadata in the configured database and local storage or R2. Every successful upload automatically queues candidate training. Check `GET /api/v1/data/datasets/{dataset_id}/training-status` with the admin key for queued/running/completed/failed status and the candidate model version. Candidate bundles are hash-checked and stored in the configured object storage. Training never automatically promotes or serves a candidate.

```powershell
Invoke-RestMethod "http://localhost:8000/api/v1/data/datasets/$datasetId/training-status" `
  -Headers @{ "X-Admin-API-Key" = $env:MEDIPREDICT_ADMIN_API_KEY }
```

Source datasets, the archived dashboard CSV, feature tables, and candidate bundles can be retrieved through admin-key-protected endpoints documented in the repository root README. Downloads are SHA-256 checked. Synthetic and unverified candidates remain blocked from promotion and serving.
