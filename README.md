# MediPredict Rwanda

MediPredict supports medicine availability monitoring through facility level stock risk estimates, alert triage, CSV recalculation, transfer matching, and printable briefings.

## Run locally

1. Install the API dependencies: `python -m pip install -r backend/requirements.txt`.
2. Train the model: `python ml_engine/pipeline/train.py`.
3. Start the API at the repository root: `uvicorn backend.app.main:app --reload --port 8000`.
4. Install and start the dashboard: `cd frontend`, `npm install`, then `npm run dev`.

The API reads the processed facility dataset at `datasets/medipredict_data/processed/medipredict_facility_timeseries_2026.csv`. Configure `MEDIPREDICT_CSV_PATH`, `MEDIPREDICT_DATABASE_URL`, `MEDIPREDICT_MODEL_PATH`, and comma-separated `MEDIPREDICT_CORS_ORIGINS` values to use deployment resources. The UI runs in offline demonstration mode if the API is unavailable. Configure `VITE_API_URL` to point to a deployed API base ending in `/api/v1`.

Uploaded files use the dataset headers documented on the Upload & Recalculate screen. The upload endpoint accepts CSV files up to 20 MB. API reference is served at `/docs`.
