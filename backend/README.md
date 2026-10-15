# MediPredict API

This project exposes its functionality through a FastAPI backend and a React dashboard in `frontend/`. The Vite development server proxies `/api` requests to the FastAPI backend.

From the repository root:

1. Copy `backend/.env.example` to `backend/.env` and adjust settings if needed.
2. Install dependencies with `python -m pip install -r backend/requirements.txt`.
3. Train the classifier with `python ml_engine/pipeline/train.py`.
4. Start the API with `uvicorn backend.app.main:app --reload --port 8000`.
5. In another terminal, run `cd frontend`, `npm install`, and `npm run dev`.
6. Open `http://localhost:5173` for the dashboard, `http://localhost:8000/docs` for Swagger UI, or `http://localhost:8000/openapi.json` for the OpenAPI schema.

API routes are under `/api/v1`. The development frontend uses `http://localhost:8000` as its API proxy target. Set `MEDIPREDICT_CORS_ORIGINS` only when browser clients on other origins need access. Inventory, consumption, and risk predictions currently use synthetic demonstration data; district indicators are unverified seed values.
