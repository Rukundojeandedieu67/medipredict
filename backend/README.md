# MediPredict API

This project exposes its functionality through a FastAPI backend and a React dashboard in `frontend/`. The Vite development server proxies `/api` requests to the FastAPI backend.

From the repository root:

1. Copy `backend/.env.example` to `backend/.env` and adjust settings if needed.
2. Install dependencies with `python -m pip install -r backend/requirements.txt`.
3. Start the API with `uvicorn backend.app.main:app --reload --port 8000`.
4. In another terminal, run `cd frontend`, `npm install`, and `npm run dev`.
5. Open `http://localhost:5173` for the dashboard, `http://localhost:8000/docs` for Swagger UI, or `http://localhost:8000/openapi.json` for the OpenAPI schema.

API routes are under `/api/v1`. The development frontend uses `http://localhost:8000` as its API proxy target. Set `MEDIPREDICT_CORS_ORIGINS` only when browser clients on other origins need access. Inventory, consumption, and risk predictions currently use synthetic demonstration data; district indicators are unverified seed values.

The current legacy model artifact is not accepted as validated: it lacks required time-based validation metadata and an artifact SHA-256. Assessments therefore use the explicitly labeled rule-based days-of-cover fallback, and confidence is not reported. Do not run the legacy training script or present its metrics as predictive performance.

Uploads to `POST /api/v1/data/assess-csv` are assessed in memory and are not persisted to `DailyStockLog` or `Prediction`. They must include `is_synthetic` with `true` or `false`; provenance is not inferred. `POST /api/v1/data/validate-csv` only returns a structured validation report. `POST /api/v1/data/training-upload` is a distinct, admin-key-protected intake route that stores a validated dataset and metadata but does not train.

### Database provenance migration

Alembic baseline and provenance migration files are prepared under `backend/migrations/`; they have not yet been applied. The provenance migration adds nullable `is_synthetic` and `data_source` columns to `daily_stock_logs` and `predictions`, and backfills existing rows with `is_synthetic=true` and `data_source="synthetic"`. Before applying to the live SQLite database, stamp the verified existing schema at the baseline, take and integrity-check a backup in the ignored `backups/` folder, then upgrade. The provenance migration can be downgraded without dropping or recreating application tables. Uploaded assessment and training-intake files remain separate from those database tables. See `docs/data_contract.md` for the CSV contract and endpoints.
