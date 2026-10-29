# MediPredict Rwanda

MediPredict monitors medicine availability through a React dashboard and FastAPI service. Inventory, consumption, and risk predictions currently use synthetic demonstration data; district indicators are unverified seed values. Do not use dashboard outputs for operational decisions.

For the staged Render, Vercel, and private AWS S3 deployment approach, see the [deployment plan](docs/deployment_plan.md). Hosting is separate from local development. Local development can use Aiven PostgreSQL and Cloudflare R2, or run the CSV-only dashboard without a database.

## Run locally

To use Aiven PostgreSQL (and Cloudflare R2 once its credentials are available):

1. Copy `backend/.env.example` to `backend/.env`. Uncomment the Aiven connection URL and replace `REPLACE_WITH_URL_ENCODED_PASSWORD` with your Aiven password (URL-encode special characters). The host, port, user, database, and TLS mode are prefilled from your Aiven service details. Keep credentials in the ignored `.env` file; never commit them or put them in frontend settings.
2. The screenshot provides no R2 bucket or S3 credentials, so keep `MEDIPREDICT_STORAGE_BACKEND=local` for now. When you have created an R2 bucket and S3 API token, enter those values, upload the dashboard CSV, set `MEDIPREDICT_DASHBOARD_DATA_KEY` to its object key, and then select `MEDIPREDICT_STORAGE_BACKEND=s3`.
3. If the Aiven database is new and empty, first confirm the connection URL points to the intended database, then apply the existing schema from the repository root:

   ```powershell
   .\backend\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini upgrade head
   ```

   The screenshot shows an existing Aiven service, but does not show whether `defaultdb` already contains application tables. Do not run migrations until its schema and migration state have been checked.
4. Start the API from the repository root. Settings are loaded from `backend/.env`:

   ```powershell
   .\backend\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --port 8000
   ```

5. In another PowerShell terminal, start the frontend:

   ```powershell
   Set-Location frontend
   npm run dev
   ```

6. Open `http://localhost:5173`. API docs are at `http://localhost:8000/docs`, and the OpenAPI schema is at `http://localhost:8000/openapi.json`.

To run only the local CSV dashboard without connecting to a database or R2, start the API in a PowerShell terminal at the repository root with `$env:MEDIPREDICT_DATABASE_ENABLED = "false"` followed by `.\backend\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --port 8000`. Start the frontend using the steps above. Database-backed features return HTTP 503 in this mode.

Install dependencies only if they are missing: `python -m pip install -r backend/requirements.txt` for the API, or `npm install` in `frontend/`. The legacy trainer is deprecated and must not be used; model serving is not enabled.

## API endpoints

All application routes use the `/api/v1` prefix:

- `GET /health` — check service status.
- `GET /inventory/summary` — retrieve current inventory totals.
- `GET /predictions/risk-register` — browse risk predictions; supports `risk`, `district`, `search`, and `limit` filters.
- `POST /data/upload-csv` — upload a CSV for risk recalculation (up to 20 MB).
- `GET /transfers/recommendations` — retrieve suggested stock transfers.
- `GET /analytics/trust-metrics` — retrieve model metrics and feature importance.

The API reads `datasets/medipredict_data/processed/medipredict_facility_timeseries_2026.csv` by default. Set `MEDIPREDICT_DATABASE_ENABLED=true` to enable the existing SQLite-backed dataset registry, provenance administration, and notification dispatch; the default remains true for deployments. Configure `MEDIPREDICT_CSV_PATH`, `MEDIPREDICT_DATABASE_URL`, `MEDIPREDICT_MODEL_PATH`, and `MEDIPREDICT_CORS_ORIGINS` when needed. Relative API file paths and SQLite database paths are resolved from the repository root. Existing repository-root `.env` settings remain supported, with `backend/.env` taking precedence. CSV uploads must include the dataset headers shown in the frontend upload view. Phase 4 training requires the output of the validated training-upload and feature-building workflow; the legacy `ML_ENGINE_TRAINING_DATA_PATH` trainer is disabled by default.

To run the current feature-building and training pipeline locally before real training data is available, run `.\backend\.venv\Scripts\python.exe -m ml.train_synthetic` from the repository root. It generates and retains a synthetic source dataset, builds features, and writes a candidate model under `ml/models/`. The source, feature table, and model metadata are marked synthetic; reported evaluation is only a pipeline smoke test, and the candidate cannot be promoted or served. Use the protected training-upload workflow below once approved real data is available.

## Aiven and Cloudflare R2 dataset workflow

Aiven PostgreSQL stores registry metadata, hashes, and archive/model records. CSV sources, verification evidence, feature bundles, and model bundles are stored in the configured Cloudflare R2 bucket. Configure `MEDIPREDICT_DATABASE_ENABLED=true`, the Aiven `MEDIPREDICT_DATABASE_URL`, `MEDIPREDICT_STORAGE_BACKEND=s3`, and all R2 settings in the ignored `backend/.env`. After archiving the dashboard CSV, set `MEDIPREDICT_DASHBOARD_DATA_KEY` to the R2 key printed by the archive command so the dashboard reads that same object.

After confirming `defaultdb` is empty and the URL is correct, create the application schema with Alembic from the repository root:

```powershell
.\backend\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini upgrade head
```

This applies schema migrations only; it does not connect to or upload data from this repository automatically. To archive the existing dashboard CSV byte-for-byte to R2 and register its synthetic provenance and SHA-256 metadata in Aiven, run:

```powershell
.\backend\.venv\Scripts\python.exe -m ml.archive_dashboard_csv
```

The existing dashboard CSV is explicitly synthetic, has only 10 monthly periods, and does not have the training pipeline's required schema or minimum history. It is archived for reference only and must not be used to train or validate a production model. Do not convert it into training labels or treat its predictions as real-world results.

For an inventory-history CSV, include the required columns and the correct `is_synthetic` value, then submit it through the protected `POST /api/v1/data/training-upload` endpoint. A successful upload automatically queues feature building and candidate training. The response includes `training_status: "queued"`. Check progress and the final candidate using the protected status endpoint:

```powershell
$datasetId = "paste-the-dataset-id-from-the-upload-response"
Invoke-RestMethod "http://localhost:8000/api/v1/data/datasets/$datasetId/training-status" `
  -Headers @{ "X-Admin-API-Key" = $env:MEDIPREDICT_ADMIN_API_KEY }
```

The job verifies the registered CSV hash, uses the existing time-aware feature/training pipeline, and writes SHA-256-checked candidate bundles to configured local storage or R2 with release metadata in the database. Training status is also included in the protected dataset detail response. Training failures are recorded with an error message. Candidates are never automatically promoted or served; synthetic and unverified sources retain their provenance labels and cannot pass the promotion gate.

The admin-key-protected retrieval endpoints are:

- `GET /api/v1/data/archives`, `GET /api/v1/data/archives/{archive_id}/download`, and `GET /api/v1/data/archives/{archive_id}/manifest` — list and retrieve the original dashboard CSV archive and its manifest.
- `GET /api/v1/data/datasets` and `GET /api/v1/data/datasets/{dataset_id}/download` — list and retrieve registered training sources.
- `GET /api/v1/models` — list candidate release metadata.
- `GET /api/v1/models/{model_version}/artifacts` and `GET /api/v1/models/{model_version}/features` — retrieve model and feature ZIP bundles.

Every download verifies the content SHA-256 against its Aiven registry record before returning bytes. Send `X-Admin-API-Key` with the configured `MEDIPREDICT_ADMIN_API_KEY`. These routes and commands require configured Aiven and R2 access; they have not been run against the user's cloud services from this workspace.

## Where AI runs

The current facility time-series CSV is about 7.5 MB and has 50,160 rows. Its operational stock and consumption values are synthetic, and district indicators are unverified seed values; see [`ml_engine/datasets/PROVENANCE.md`](ml_engine/datasets/PROVENANCE.md). The resource figures below are initial capacity-planning estimates for a single CPU-only run at about this scale, not measured benchmarks or service guarantees. They assume one job or one API instance at a time; measure representative approved data before setting an SLA or scaling up.

| Workload | Recommended runtime | Initial CPU / memory / time budget | Artifact handling and fallback |
|---|---|---|---|
| Training | Run locally for development with synthetic fixtures. Run real-data training as an isolated, one-off Render job only after approval; use CI for tests/builds, not for unapproved real data. | 2–4 vCPU, 4–8 GiB RAM; plan for minutes to tens of minutes for one feature table of roughly 50,000 rows. This is an unbenchmarked estimate; log actual wall time and peak memory for each approved run. | Keep inputs under `ml/artifacts/feature_tables/<build_id>/` and immutable model/evaluation bundles under `ml/models/<model_version>/`. Training verifies the feature-table SHA-256 and records SHA-256 values for `model.joblib`, `calibrators.joblib`, and `feature_builder_state.json` in `metadata.json`. A candidate is not promoted unless its metadata says `model_validated: true`, its source provenance is verified, and its artifact hash matches. Missing, invalid, or mismatched bundles are rejected; the API uses the rule-based assessment. |
| Batch scoring | Use a separate, scheduled Render job; do not run long batch work inside the interactive web service. Batch scoring is not currently implemented as a command. | For a future implementation, start with 1–2 vCPU and 2–4 GiB RAM. Expect seconds to minutes for a single pass over about 50,000 rows as a planning estimate only; benchmark the actual scoring pipeline before scheduling. | Read a pinned, immutable model bundle and verify its recorded SHA-256 before scoring. Store outputs and provenance separately from the input table, with a run ID and the model/data hashes. A missing or mismatched model must stop model scoring and use the explicit rule-based assessment instead; do not emit model scores. |
| Live inference | The existing FastAPI web service. Today it uses rule-based stock-cover assessments; validated-model inference is not enabled. | Start with 1–2 vCPU and 1–2 GiB RAM per instance for the current CSV scale. Seconds-level responses are an initial interactive budget, not a measured latency; load-test and record p95 latency before setting an SLO. | Deploy a versioned model bundle and its metadata together. The loader accepts it only when `model_validated` is exactly `true`, source provenance is verified, and the SHA-256 for the configured model file matches. Missing or invalid metadata, a failed hash, or an unreadable model results in `method: "rule_based_fallback"` and `model_validated: false`; this fallback is surfaced in the API response. |
| Future LLM calls | No LLM integration is currently enabled. If approved, call a separately controlled web service with data minimization, access controls, and a documented owner-approved purpose; do not route such calls through notebooks or CI. | No local model resources are allocated. For a remote service, CPU/RAM are provider-managed; request latency and limits are provider-dependent and must be measured for the chosen service. | Do not treat LLM output as a promoted model artifact. Keep prompts/responses out of logs unless explicitly approved, and verify any locally stored prompt template or configuration by revision/hash. On a disabled or unavailable integration, retain the rule-based assessment. |

**Real or unverified data must not be sent to third-party notebook or AI services without the data owner's approval.** CI and local examples should use synthetic data unless that approval explicitly covers the data and service.

Model promotion is a separate, reviewed release step: run the existing Phase 4 gate, require `model_validated: true` and verified real-data provenance, verify the recorded model-file SHA-256, then publish the immutable version. A failed gate, missing file, or hash mismatch must never replace a currently approved bundle. The Docker training profile writes candidate artifacts only; it does not promote or activate them. The live API remains on the rule-based assessment unless an approved model bundle is explicitly mounted and passes validation.

## Run with Docker Compose

Docker Compose builds the API and static frontend. The API reads the repository dashboard CSV from its read-only bind mount and uses local storage; Compose does not require or use R2 credentials. The API database/uploads, feature tables, and model bundles use persistent Docker volumes. The `ml` profile provides separate feature-build and training entry points. Copy `.env.example` to `.env` before starting Compose if you need to configure the protected training-upload API key or ports. For a hosted deployment using R2, upload the dashboard CSV to the configured bucket and set `MEDIPREDICT_DASHBOARD_DATA_KEY` to its exact object key in the hosting service.

```powershell
docker compose up --build
```

Open the dashboard at `http://localhost:8080` and API documentation at `http://localhost:8000/docs`. To stop the services while retaining their data, run `docker compose down` (do not add `-v` unless you intend to remove the persistent volume).

Training data intake at `POST /api/v1/data/training-upload` requires `MEDIPREDICT_ADMIN_API_KEY` to be set in `.env`; send that key as `X-Admin-API-Key`. A successful upload automatically queues candidate training. Check its status at `GET /api/v1/data/datasets/{dataset_id}/training-status`. To manually rebuild features or rerun training, use the one-off jobs below.

```powershell
$env:FEATURE_DATASET_ID = "v1-<timestamp>-<dataset-id>"
docker compose --profile ml run --rm feature-build
```

Use the feature build ID printed by that command for training:

```powershell
$env:FEATURE_BUILD_ID = "v1-<timestamp>-<feature-build-id>"
docker compose --profile ml run --rm training
```

Both jobs read uploaded data from `api_data`; feature tables and versioned model candidates persist in the `ml_artifacts` and `ml_models` Docker volumes. Review the evaluation report, promotion gate, provenance, and hashes before deployment. Candidates are never automatically promoted. Only set `MODEL_VERSION` to a reviewed bundle whose metadata records `model_validated: true`; an absent or invalid model continues to use the rule-based assessment. Selecting a version does not enable model scoring: current live assessments remain rule-based. Neither job sends data to third-party services. Set `API_PORT` or `FRONTEND_PORT` in `.env` to change published ports.
# medipredict-V001
