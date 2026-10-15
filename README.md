# MediPredict Rwanda API

MediPredict is a backend-only medicine availability monitoring service. Use the interactive Swagger UI to explore and call the API; there is no frontend dashboard in this project.

## Run locally

1. Install the API dependencies: `python -m pip install -r backend/requirements.txt`.
2. Train the risk model: `python ml_engine/pipeline/train.py`.
3. Start the API from the repository root: `uvicorn backend.app.main:app --reload --port 8000`.
4. Open Swagger UI at `http://localhost:8000/docs`. The OpenAPI schema is available at `http://localhost:8000/openapi.json`.

## API endpoints

All application routes use the `/api/v1` prefix:

- `GET /health` — check service status.
- `GET /inventory/summary` — retrieve current inventory totals.
- `GET /predictions/risk-register` — browse risk predictions; supports `risk`, `district`, `search`, and `limit` filters.
- `POST /data/upload-csv` — upload a CSV for risk recalculation (up to 20 MB).
- `GET /transfers/recommendations` — retrieve suggested stock transfers.
- `GET /analytics/trust-metrics` — retrieve model metrics and feature importance.

The API reads `datasets/medipredict_data/processed/medipredict_facility_timeseries_2026.csv` by default. Configure `MEDIPREDICT_CSV_PATH`, `MEDIPREDICT_DATABASE_URL`, `MEDIPREDICT_MODEL_PATH`, and `MEDIPREDICT_CORS_ORIGINS` in `.env` to use deployment resources or permit browser clients hosted on other origins. CSV uploads must include the dataset headers expected by the API.
