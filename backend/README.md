# MediPredict API

This project exposes its functionality through a FastAPI backend. There is no frontend dashboard; use Swagger UI to explore and call the endpoints.

From the repository root:

1. Install dependencies with `python -m pip install -r backend/requirements.txt`.
2. Train the classifier with `python ml_engine/pipeline/train.py`.
3. Start the API with `uvicorn backend.app.main:app --reload --port 8000`.
4. Open `http://localhost:8000/docs` for Swagger UI or `http://localhost:8000/openapi.json` for the OpenAPI schema.

API routes are under `/api/v1`. Set `MEDIPREDICT_CORS_ORIGINS` only when browser clients on other origins need access; Swagger UI served by this API is same-origin.
