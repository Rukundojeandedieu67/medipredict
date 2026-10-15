# MediPredict Rwanda

MediPredict monitors medicine availability through a React dashboard and FastAPI service. Inventory, consumption, and risk predictions currently use synthetic demonstration data; district indicators are unverified seed values. Do not use dashboard outputs for operational decisions.

## Run locally

1. Copy `backend/.env.example` to `backend/.env` and adjust settings if needed.
2. Copy `ml_engine/.env.example` to `ml_engine/.env` and adjust paths if needed.
3. Install the API dependencies: `python -m pip install -r backend/requirements.txt`.
4. Install the model pipeline dependencies: `python -m pip install -r ml_engine/requirements.txt`.
5. Train the risk model: `python ml_engine/pipeline/train.py`.
6. Start the API from the repository root: `uvicorn backend.app.main:app --reload --port 8000`.
7. In another terminal, start the frontend: `cd frontend`, `npm install`, then `npm run dev`.
8. Open the dashboard at `http://localhost:5173`. Swagger UI is at `http://localhost:8000/docs`, and the OpenAPI schema is available at `http://localhost:8000/openapi.json`.

## API endpoints

All application routes use the `/api/v1` prefix:

- `GET /health` — check service status.
- `GET /inventory/summary` — retrieve current inventory totals.
- `GET /predictions/risk-register` — browse risk predictions; supports `risk`, `district`, `search`, and `limit` filters.
- `POST /data/upload-csv` — upload a CSV for risk recalculation (up to 20 MB).
- `GET /transfers/recommendations` — retrieve suggested stock transfers.
- `GET /analytics/trust-metrics` — retrieve model metrics and feature importance.

The API reads `datasets/medipredict_data/processed/medipredict_facility_timeseries_2026.csv` by default. Configure `MEDIPREDICT_CSV_PATH`, `MEDIPREDICT_DATABASE_URL`, `MEDIPREDICT_MODEL_PATH`, and `MEDIPREDICT_CORS_ORIGINS` in `backend/.env` to use deployment resources or permit browser clients hosted on other origins. Relative API file paths and SQLite database paths are resolved from the repository root. Existing repository-root `.env` settings remain supported, with `backend/.env` taking precedence. The training pipeline reads `ML_ENGINE_TRAINING_DATA_PATH` and `ML_ENGINE_ARTIFACTS_DIR` from `ml_engine/.env`; relative paths there are resolved from `ml_engine`. CSV uploads must include the dataset headers shown in the frontend upload view.
# medipredict-V001
