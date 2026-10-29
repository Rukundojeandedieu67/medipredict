# MediPredict Rwanda

MediPredict Rwanda is a medicine-supply monitoring prototype for exploring facility inventory, stock-cover risk, alerts, and possible inter-facility transfers. It combines a React dashboard with a FastAPI service and a CSV-based data workflow.

> **Important — demonstration system:** The default inventory, consumption, and risk data are synthetic; district indicators include unverified seed values. Live classifications use rule-based days-of-cover calculations. A validated machine-learning model is **not** served. Do not use this prototype or its outputs to make clinical, procurement, allocation, or emergency-response decisions.

## Start the dashboard

The quickest way to explore the demonstration is with Docker Compose:

```powershell
docker compose up --build
```

Then open:

- Dashboard: <http://localhost:8080>
- API health: <http://localhost:8000/api/v1/health>
- Interactive API documentation: <http://localhost:8000/docs>

Stop the services with `Ctrl+C` or `docker compose down`. The default Compose setup keeps API data in named Docker volumes. Do not run `docker compose down -v` unless you intend to delete those volumes.

For detailed screen-by-screen instructions, CSV preparation, interpretation guidance, and recommendations for responsible adoption, read the [End-User Guide](docs/user-guide.md).

## What users can do

- **Overview:** scan facility and medicine counts, the latest reporting date, unresolved alerts, and priority records.
- **Inventory:** search and filter facility-medicine records by district, risk, stock status, or data provenance; sort the list and inspect a record.
- **Stock Alerts:** review stock-out, low-cover, and unavailable-cover warnings. Acknowledge or resolve an alert in this browser.
- **Risk Register:** search records and filter by district or risk classification.
- **Stock Transfers:** review possible donor-recipient matches for a medicine.
- **Model Insights:** inspect model governance and methodology disclosures; this is not a live forecasting or clinical-performance report.
- **Upload Data:** validate and assess a daily-frequency CSV, view the result, and access the CSV schema. The assessment uses the uploaded file and does not replace the dashboard's shared inventory snapshot.

Use the **Refresh Data** button to reload the current dashboard snapshot. The displayed snapshot date is the latest reporting date in that data, not a guarantee that the data is current.

## Readiness and responsible use

- Treat all demonstration figures, rankings, projections, alerts, and transfer suggestions as examples—not verified stock positions or forecasts.
- Verify physical counts, units, reporting dates, consumption, incoming orders, batch expiry, and provenance with the responsible facility and source system before any action.
- Days of cover and 7-/14-day stock trajectories are arithmetic scenarios based on reported stock and consumption. They assume a constant consumption rate and do not account for deliveries or other real-world changes.
- Missing or zero consumption means cover may be unavailable; it does not mean the medicine is safe or adequately stocked.
- The default district indicators are unverified. Do not cite them as official statistics.
- Do not upload patient-identifiable or otherwise sensitive information. The CSV intake is for facility-item inventory observations.
- Dashboard alert acknowledgements and resolutions are saved in the current browser's local storage; they are not a shared or centrally audited workflow.

For limitations, CSV handling, interpretation, and recommended next steps, see the [End-User Guide](docs/user-guide.md). For system status and data provenance, see [Dataset provenance](ml_engine/datasets/PROVENANCE.md) and [Data contract](docs/data_contract.md).

For the staged Render, Vercel, and private AWS S3 deployment approach, see the [deployment plan](docs/deployment_plan.md). Hosting is separate from local development. Local development can use Aiven PostgreSQL and Cloudflare R2, or run the CSV-only dashboard without a database.

## Model Insights: methodology and governance

The dashboard's **Model Insights** page is a governance and methodology view, not a live forecasting or clinical-performance report.

- **Operational serving:** Live inventory risk classifications use transparent, rule-based days-of-cover logic. Predictive machine-learning serving is not enabled or authorized for live decisions. Confirm inventory against physical counts and source-maintained records.
- **Development benchmarks:** No validated model metrics are currently available. Any historical evaluation metrics or test scores are developmental baselines on demonstration data, not evidence of real-world clinical or operational performance.
- **Feature importance:** No feature-importance metrics are currently loaded from the repository artifact store. Missing signals do not mean zero importance or establish that a model is valid.
- **Data provenance:** Demonstration stock levels, consumption, and risk trajectories are synthetic; generated API records are marked `is_synthetic=true`. District indicators are unverified seed values and must not be cited as confirmed statistics.
- **Evaluation integrity:** Model training and evaluation require temporal out-of-time splits. Random train/test splits are prohibited to avoid leakage across inventory timelines.

Do not use the dashboard's outputs or any development results for clinical, procurement, allocation, or emergency-response decisions. See the [End-User Guide](docs/user-guide.md) for interpreting the dashboard and [Dataset provenance](ml_engine/datasets/PROVENANCE.md) for source details.

## Run locally (development)

To use Aiven PostgreSQL (and Cloudflare R2 once its credentials are available):

1. Copy `backend/.env.example` to `backend/.env` and configure the Aiven connection URL with the values from your database provider. URL-encode special characters in the password. Keep credentials in the ignored `.env` file; never commit them or put them in frontend settings.
2. Local file storage is the default. To use Cloudflare R2, create a bucket and S3 API token, configure the R2 settings in the ignored `backend/.env`, set `MEDIPREDICT_DASHBOARD_DATA_KEY` to the dashboard CSV object key, and then select `MEDIPREDICT_STORAGE_BACKEND=s3`. In hosted Docker deployments, the dashboard CSV included in the image seeds and verifies a missing object on first read.
3. If the Aiven database is new and empty, first confirm the connection URL points to the intended database, then apply the existing schema from the repository root:

   ```powershell
   .\backend\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini upgrade head
   ```

   Do not run migrations against a database containing existing application tables until its schema and migration state have been checked.
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
- `GET /alerts` — retrieve current in-app stock warnings (does not send notifications).
- `GET /transfers/recommendations` — retrieve suggested stock transfers.
- `GET /analytics/trust-metrics` — retrieve model metrics and feature importance.
- `POST /data/assess-csv` — validate and assess a daily-frequency CSV (up to 20 MB).
- `POST /data/validate-csv` — return a structured CSV validation report.
- `POST /data/training-upload` — admin-key-protected registration that queues candidate training; it does not promote or serve a model.

The deprecated `POST /data/upload-csv` route remains an alias for `/data/assess-csv`.

The API reads `datasets/medipredict_data/processed/medipredict_facility_timeseries_2026.csv` by default. Dashboard, summary, risk, alerts, transfer, and trust-metric calculations run in the backend; the frontend consumes these API responses. With S3 storage selected, a missing dashboard object is seeded from `MEDIPREDICT_CSV_PATH` on first read when that local CSV is available, then SHA-256 verified. If the deployment has no local CSV, upload the source object once to the configured key. Valid CSVs assessed through the UI are stored with a SHA-256-addressed metadata record in the configured storage backend. Set `MEDIPREDICT_DATABASE_ENABLED=true` to enable the existing SQLite-backed dataset registry, provenance administration, and notification dispatch; the default remains true for deployments. Configure `MEDIPREDICT_CSV_PATH`, `MEDIPREDICT_DATABASE_URL`, `MEDIPREDICT_MODEL_PATH`, and `MEDIPREDICT_CORS_ORIGINS` when needed. Relative API file paths and SQLite database paths are resolved from the repository root. Existing repository-root `.env` settings remain supported, with `backend/.env` taking precedence. CSV uploads must include the dataset headers shown in the frontend upload view. Phase 4 training requires the output of the validated training-upload and feature-building workflow; the legacy `ML_ENGINE_TRAINING_DATA_PATH` trainer is disabled by default.

To run the current feature-building and training pipeline locally before real training data is available, run `.\backend\.venv\Scripts\python.exe -m ml.train_synthetic` from the repository root. It generates and retains a synthetic source dataset, builds features, and writes a candidate model under `ml/models/`; the source, feature bundle, and model bundle are also saved through the configured storage backend with immutable keys and SHA-256 verification. The source, feature table, and model metadata are marked synthetic; reported evaluation is only a pipeline smoke test, and the candidate cannot be promoted or served. Use the protected training-upload workflow below once approved real data is available.

## Aiven and Cloudflare R2 dataset workflow

Aiven PostgreSQL stores registry metadata, hashes, and archive/model records. CSV sources, verification evidence, feature bundles, and model bundles are stored in the configured Cloudflare R2 bucket. Configure `MEDIPREDICT_DATABASE_ENABLED=true`, the Aiven `MEDIPREDICT_DATABASE_URL`, `MEDIPREDICT_STORAGE_BACKEND=s3`, and all R2 settings in the ignored `backend/.env`. On first dashboard read, the backend uploads and verifies the local dashboard CSV if the configured object key does not yet exist; on hosted deployments without a local copy, upload the source CSV to that exact key first. Existing keys are immutable and are never overwritten.

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

Docker Compose builds the API and static frontend. The API reads the repository dashboard CSV from its read-only bind mount and uses local storage; Compose does not require or use R2 credentials. The API database/uploads, feature tables, and model bundles use persistent Docker volumes. The `ml` profile provides separate feature-build and training entry points. Copy `.env.example` to `.env` before starting Compose if you need to configure the protected training-upload API key or ports. The API image includes only the approved dashboard CSV needed for hosted startup; with R2 configured, it seeds and verifies a missing `MEDIPREDICT_DASHBOARD_DATA_KEY` from that file on first read.

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
