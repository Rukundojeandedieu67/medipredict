# MediPredict deployment plan

**Staged deployment and implementation plan.** The current implementation status is recorded in the phase report at the end. Provider prices and limits below are a snapshot dated **2026-10-28**; recheck the linked official pages before choosing a plan or purchasing services. “Not verified” means the existing review did not confirm a reliable numeric value from the cited official page.

## One-page decision brief

| Area | Recommendation |
|---|---|
| Frontend | Vercel **Pro** for a production service; the Vite app is a static build. Keep Hobby for personal/non-commercial evaluation only. |
| API | A paid Render Docker web service running FastAPI and Uvicorn. Keep the web service stateless; use the existing health route for liveness and add a real readiness check during implementation. |
| Database | Neon Postgres on a paid Launch plan initially, with a separate production project from staging. Use Neon’s pooled connection URL for the runtime and the direct URL for Alembic. Select a non-sleeping paid compute configuration if first-request delay is unacceptable. |
| CSVs, evidence, models | **Cloudflare R2** is the owner-selected S3-compatible object store. Keep buckets private, use least-privilege tokens, immutable object keys, and independently verify SHA-256. Do not assume AWS Object Lock/WORM controls are available on R2. |
| Guide media | Cloudinary only for approved MediGuide videos, thumbnails, and caption files. No datasets, evidence, model files, or health information. No guide media files were found in this repository audit. |
| Training/build jobs | Separate, explicitly triggered job/worker with restricted read/write access to the private object store. Do not run `ml/build_dataset.py`, training, or dataset-building work in the FastAPI web service. Local development remains local. |
| Release gate | Do not put real facility, stock, consumption, patient, source-evidence, or mixed-provenance data into hosted environments until the data owner approves the data and its destination, and privacy/legal review resolves residency, processor, retention, and access questions. |

### Why this stack

**Owner decision (2026-10-28):** use Neon Postgres and Cloudflare R2 for the hosted database and object store. R2's S3-compatible API is suitable for the adapter, but compatibility does not establish feature parity with AWS. Do not rely on R2 for Object Lock/WORM or version retention unless those exact controls are independently confirmed for the account and tested. Keep buckets private and plan application-side integrity checks. AWS pages below remain a comparison, not the selected object-storage provider. Data residency, retention, cost, and owner approval remain release gates.

The current local workflow should remain the default and continue to use SQLite and the local filesystem. Hosting should be an explicit, separately configured deployment mode; it must not silently change local behavior.

### What to do next

The first useful hosted milestone should be a **synthetic-data staging deployment**, not a production launch:

1. Confirm the AWS region, organization/account ownership, budget, staging and production domains, and whether AWS, Render, Vercel, and Neon are approved providers. Do not upload existing mixed-provenance data while these decisions are open.
2. Keep the current local workflow as the baseline: SQLite, the configured local CSV, filesystem uploads, and the Vite `/api` proxy must continue working without cloud credentials.
3. Implement an explicit data/storage boundary. In local mode, keep reading `MEDIPREDICT_CSV_PATH` and writing under `MEDIPREDICT_UPLOADS_PATH`; in hosted mode, read approved, versioned data from private S3 and keep registry/audit metadata in Postgres. Preserve the existing upload, checksum, and provenance contracts.
4. Make schema upgrades a release step, add the hosted frontend API base URL while retaining the local Vite proxy, and bind the Render process to Render's assigned port.
5. Deploy Render and Vercel to staging with a dedicated private S3 bucket, isolated database, exact CORS origins, and a synthetic fixture explicitly marked `is_synthetic=true`. Verify a full browser-to-API flow, API restart, object checksum, authorization failures, and database/object restore before production planning.
6. Only after data-owner and privacy/legal approval, create separate production resources, credentials, domains, and retention policies. Treat training jobs and any guide-media service as later, separately approved work.

The existing Render image does not contain the default dashboard CSV: [Dockerfile](../Dockerfile) copies `backend/`, `config/`, and `ml/`, while local [docker-compose.yml](../docker-compose.yml) supplies the CSV through a bind mount. For the hosted dashboard, configure its source CSV as a private R2 object and set `MEDIPREDICT_DASHBOARD_DATA_KEY`; do not bake the repository's mixed-provenance dataset into the production image.

### Immediate deployment blockers

1. The admin interface currently trusts one shared API key, while uploader/verifier identity is accepted from caller-supplied headers. That is not production identity or separation of duties.
2. Newly uploaded dataset bytes and verification evidence now use the configured local/S3-compatible storage, while dataset metadata and verification/revocation events use the SQL registry. Render still requires Neon and R2 configuration; existing local files are not automatically migrated.
3. Postgres migration foundation exists, but it has not yet been verified against Neon/Postgres. Run the new Alembic migration in a disposable Postgres environment before hosting data.
4. The dashboard reads `MEDIPREDICT_CSV_PATH` from the API host's filesystem; it has no S3-backed primary-data reader. The existing image omits that CSV, so a healthy API alone does not make the hosted dashboard functional.
5. The frontend calls relative `/api/v1/...` paths. The checked-in Vercel rewrite must be deployed to the Vercel-connected branch before its live frontend can reach Render.
6. The configured legacy model path is not the versioned artifact output path used by the current `ml/train.py` workflow; the README says model serving is disabled.
7. Existing generated CSVs contain synthetic operational values, unverified seed indicators, and some mixed real/derived/fallback data without row-level provenance. They are not approved production datasets.
8. No MediGuide video, thumbnail, WebVTT, or SRT files were located.

## 1. What is really needed

### Observed repository state

| Area | What exists now | Deployment consequence |
|---|---|---|
| API and database | FastAPI, synchronous SQLAlchemy, SQLite default. The API retains `create_all()` on local SQLite only; Postgres startup does not create schema. ORM/migration foundations now include dataset registry, dataset event, and model release tables. | Current migrations are SQLite-tested but not yet verified against a live Postgres/Neon instance. Use Alembic, not web-process schema creation, in hosted environments. |
| Primary dashboard data | `load_rows()` reads `MEDIPREDICT_CSV_PATH` on API requests. CSV assessments are in memory. The assessment endpoint does not persist rows to the ORM tables. | A database migration alone will not move the dashboard’s primary data source. Decide which app data becomes relational tables and which remains an immutable source object. |
| Training-upload registry | `POST /api/v1/data/training-upload` writes dataset bytes through the configured local/S3-compatible store and records metadata in `datasets`. The 20 MiB limit remains. Local mode also keeps the existing `metadata.json` sidecar for compatibility. | Configure Render to use Neon and private R2 before accepting hosted uploads. Existing filesystem-only uploads are not automatically imported into the new registry. |
| Verification/evidence | New registry-backed dataset verification/revocation events are persisted in `dataset_events`; uploaded evidence bytes use the configured object store and are SHA-256 checked when read. Legacy filesystem-only datasets retain their existing JSONL behavior. | Database event rows are not database-enforced append-only and still use the existing shared-key/caller-supplied identity model. Do not treat this as production audit controls or verified human identity. |
| Admin access | [backend/app/main.py](../backend/app/main.py) uses `MEDIPREDICT_ADMIN_API_KEY` as a single shared secret and compares it in constant time in `X-Admin-API-Key`. `X-Uploader` and `X-Admin-Identity` are caller-provided identity labels. | Do not put the shared key in Vercel browser environment variables or frontend code. Introduce authenticated, role-based server-side identity before production intake or verification. |
| CORS | `MEDIPREDICT_CORS_ORIGINS` is parsed as comma-separated exact origins and used by FastAPI CORS middleware. Defaults are local Vite URLs. | Production origins must be explicit. CORS is not authentication. Avoid an unrestricted origin or credentials-enabled wildcard. |
| Model loading | [backend/app/ml_service.py](../backend/app/ml_service.py) reads a local `model_path` and metrics file, validates metadata and provenance, then calls `joblib.load()`. Current default path is under [ml_engine/models_store/](../ml_engine/models_store/). | The loader is file-path based, has no object-storage adapter, and deserializes executable pickle-derived content. Accept only trusted, access-controlled, hash-verified artifacts produced by the isolated training pipeline. |
| ML workflows | [ml/build_dataset.py](../ml/build_dataset.py) expects the registered upload files in the local uploads tree. The current Phase 4 flow runs `python -m ml.train <feature-build-id>` and writes versioned artifacts under [ml/models/](../ml/models/); the newer flow is explicitly distinct from the legacy trainer. | Build and train in a separate job with the approved dataset and the exact code/dependency version. Publish artifacts by immutable ID; never launch these jobs inside web requests or the API service. |
| Frontend | Vite/React build script is `npm run build`; API calls use relative `/api/v1/...`. [frontend/vite.config.ts](../frontend/vite.config.ts) proxies `/api` to localhost in development; [frontend/vercel.json](../frontend/vercel.json) rewrites `/api` to the Render API in Vercel deployments. | Commit and deploy the rewrite; use same-origin browser paths and keep API credentials out of the frontend. |
| MediGuide | Repository search found no guide video, thumbnail, WebVTT, or SRT assets, and no existing MediGuide implementation to configure. | Cloudinary work is future content delivery only. The content owner must provide approved media and captions; do not fabricate or upload them in this stage. |
| Existing data | [README.md](../README.md) says operational dashboard data is synthetic and district indicators are unverified seed values. [ml_engine/datasets/PROVENANCE.md](../ml_engine/datasets/PROVENANCE.md) also identifies real-source facility data, derived fields, unverified seed indicators, synthetic operational fields, and climate data with synthetic fallbacks not identified per row. | Do not infer consent or approval from a source URL or from a synthetic flag on only part of a mixed file. Review field-level provenance, license, and owner approval for every file before hosting. |

### Components and deployment placement

| Component | Where it runs | Why it is needed | Minimum viable setup | Recommended production setup |
|---|---|---|---|---|
| Browser frontend | Vercel static site | Serves the React dashboard and static assets. | Vercel preview deployment against a staging API with synthetic-only data. | Vercel Pro project/team owned by the responsible organization; separate staging and production environments, exact API origins, protected previews. |
| FastAPI API | Render web service | Owns business rules, authentication, validation, database access, presigned URL issuance, and audit events. | Paid Render instance for a staging API; no production data. | Paid Docker service, health/readiness probes, bounded concurrency, request limits, monitoring, and no durable files on its writable layer. |
| Relational database | Neon Postgres | Stores application entities, dataset registry metadata, verification/revocation events, and audit metadata. | A dedicated non-production Neon branch/project with migration tests and synthetic fixtures. | Separate paid staging and production projects; pooled runtime connection, direct migration connection, restore/export plan, budget alerts, and access separation. |
| Private object storage | Cloudflare R2 (owner-selected) | Stores dashboard data, registered CSVs, evidence, approved feature builds, and model releases as later phases are implemented. | Dedicated private staging bucket and S3-compatible API token with synthetic fixtures and checksums. | Separate staging/production buckets and tokens, public access disabled, immutable keys, least privilege, checksum verification, and tested backup/restore. Do not assume Object Lock/WORM. |
| Guide-media delivery | Cloudinary | Video transcoding/CDN delivery for approved guide content only. | One non-production product environment with public-safe demo guide media. | Separate production environment; signed server-side uploads, controlled public delivery for approved media, transformations and captions, usage alerts. |
| Training/build pipeline | Separate Render job/worker or controlled CI job | Performs feature building, training, validation, and artifact publication without consuming web-service resources. | Run locally against synthetic data until a repeatable job and isolated Postgres/object-store tests exist. | Restricted one-off/worker job with explicit approval, resource limits, pinned dependencies, input/output hashes, immutable artifact publication, and human promotion gate. |
| Secrets and identity | Render/Vercel provider secret stores; external identity provider still to be selected | Keeps credentials out of Git and browser bundles and identifies actors. | Local `.env` files remain untracked; staging-only secrets in service secret stores. | Managed identity (OIDC/SSO with MFA), scoped service credentials, regular key rotation, separate environments, and a documented break-glass process. |
| DNS/TLS and observability | Domain registrar/DNS, Vercel, Render, Neon, AWS | Provides stable origins, encrypted transport, health monitoring, and operational investigation. | Provider-managed TLS and platform logs for staging. | Organization-owned domain, verified DNS/TLS, redacted structured logs, alerts, independent audit trail, budget alerts, and incident ownership. |

## 2. Storage decision: CSVs, evidence, and model artifacts

### Recommended design

Use **Cloudflare R2** through its S3-compatible API, subject to owner approval and data-residency review. Divide private object namespaces and API tokens by environment and object class:

The backend reads/writes dataset and evidence objects through the selected local or S3-compatible storage, and persists dataset registry metadata plus verification/revocation event records through the SQLAlchemy models. Local mode remains the default. In hosted mode, configure a Neon database, apply migrations through revision `0004`, and set the private R2 endpoint/bucket credentials before accepting uploads. ML artifacts and the dashboard's prediction source remain separate paths; changing storage settings does not import old uploads or make current synthetic data real.

```text
staging/
  datasets/{dataset_id}/{sha256}/data.csv
  evidence/{sha256}
  feature-builds/{build_id}/...
  model-releases/{release_id}/...
production/
  datasets/{dataset_id}/{sha256}/data.csv
  evidence/{sha256}
  feature-builds/{build_id}/...
  model-releases/{release_id}/...
```

The prefix is organizational, not an access boundary by itself. Use separate buckets/accounts or policies for the actual boundary. Keep original filenames and personal identifiers out of keys. Store the object key, immutable digest, byte length, media type, and provider version ID in the registry.

1. Keep R2 buckets private and do not enable public bucket access. Scope API tokens to the required bucket and operations; application listings should come from authorized database rows rather than broad bucket listing.
2. Require TLS. Confirm the selected Cloudflare account's at-rest encryption, version retention, and recovery guarantees before relying on them; do not describe them as AWS SSE-KMS or Object Lock.
3. Use immutable, content-addressed keys and verify the object's SHA-256 on read/write. Do not rely on R2 versioning or WORM retention until the exact feature is confirmed for this account and tested; R2 key naming alone is not provider-enforced immutability.
4. Issue server-generated presigned `PUT`/`GET` URLs for one exact object and operation, normally expiring in **5 minutes**. URLs are bearer tokens; never log them, put them in analytics, or expose them in error messages. An S3 presigned URL can be reused before expiry, so use server-generated one-time keys, validate the resulting object, and prevent overwrites through policy/version checks.
5. Include SHA-256 in the upload/checksum workflow. On ingest, stream the complete object and compute SHA-256 before registering it. On every API/job read that will be parsed or loaded, stream and recompute SHA-256; compare to the immutable database record before processing. Do not treat an ETag as SHA-256.
6. Give each dataset, evidence attachment, and model build a new immutable key. Reject content mismatches and never overwrite a published key. Keep model-object read permission separate from upload permission.
7. Keep verification and revocation records append-only in Postgres. If an immutable audit export is required, use a separately controlled service with verified WORM support; do not assume R2 provides Object Lock. A database table constraint alone is not protection against a database owner.
8. Apply application upload ceilings, not just provider maximums. Start by preserving the current 20 MiB CSV/evidence ceiling until requirements justify a change; enforce it both before buffering and at the reverse-proxy/API boundary. Add quotas, timeouts, row limits, and job resource ceilings.

### Provider comparison against the requirements

The requirements column describes what is provider-native versus what MediPredict would still need to enforce. “Not verified” is intentional; do not interpret it as a product guarantee.

| Option | Private by default / no public listing | Versioning / immutability | Short-lived signed access | SHA-256 verification | Server-side encryption | Size limits / fit |
|---|---|---|---|---|---|---|
| Render persistent disk | Files are on the attached service disk, not a public object URL. Your application still controls any access/listing it exposes. | Disk snapshots are daily and retained seven days per the official disk page; this is not per-object versioning or a WORM guarantee. | No provider S3-style presigned object URL. | Application must hash files itself. | Render documents encryption at rest. | Paid services only; disk size price and current minimum were **not verified**. It is a mounted filesystem, not the right shared object store for multiple services/jobs. Useful only for scratch/cache. |
| Cloudflare R2 | R2 buckets are private unless public access is explicitly enabled. | Official versioning/Object Lock guarantee **not verified** in the reviewed docs. Immutable key naming is application-managed and is not equivalent to provider WORM. | Yes; S3 presigned URL docs specify 1 second to 7 days. | Application must hash/read and compare. | Confirm and configure the currently supported encryption guarantees before selection; not used as the basis for this recommendation. | Official R2 page documents Standard and Infrequent Access pricing, free operation/storage allowance, and no egress fees. The application still sets the 20 MiB intake cap. |
| Backblaze B2 | Private bucket configuration is available; verify bucket ACL and policy in deployment. | Official Object Lock documentation describes immutable retention; B2 versions can be retained. Verify current S3 API coverage and retention behavior in an implementation test. | S3-compatible presigned download and upload are documented; browser presigned POST is not supported. | Application-side SHA-256 remains required. | S3-compatible API documents SSE-B2 or SSE-C. | Strong cost candidate; exact upload caps/region choice still require confirmation. Compatibility differences and object lock behavior must be integration-tested. |
| AWS S3 (comparison) | Keep Block Public Access on and omit `ListBucket` from the web role. No anonymous object access. | Versioning is documented; Object Lock provides WORM retention and requires deliberate configuration. | Yes; AWS documents presigned URLs for upload/download with configurable expiry. | SigV4 presigned requests support SHA-256 checksums; still recompute SHA-256 after upload and before sensitive processing. | SSE-S3 is the documented default for new objects; SSE-KMS can be selected where key controls are required. | S3 object maximums are not the application limit. Keep a conservative MediPredict byte cap and quotas. Per-GB/request rates depend on region and tier; exact estimate is **not verified**. |
| Supabase Storage | Buckets are private by default; private downloads require access control or a signed URL. | Native versioning/WORM semantics were **not verified** in the reviewed Storage docs. Separate immutable object keys remain necessary. | Yes, signed URLs are supported. | Application must hash/read and compare. | Current at-rest encryption specifics were not verified in the reviewed pages. | Convenient private bucket controls, but storage allowance is smaller on Free and paid storage is metered. Not the preferred durable evidence/WORM store. |
| Cloudinary raw files | Upload-type `upload` is publicly delivered by default. Private/authenticated delivery options exist, but media delivery protection is not a replacement for a private data archive. | Versioning and WORM guarantee were **not verified**. | Signed/authenticated media delivery exists; paid access-control features and link-sharing behavior require review. | MediPredict must hash and compare; do not rely on media URLs or asset IDs. | Not verified as meeting this data-store requirement. | Do not use for CSVs, evidence, features, or model artifacts. Scope it to approved guide videos, thumbnails, and captions only. |

**Decision:** Cloudflare R2 is the selected provider by owner direction and will be accessed through the S3-compatible API. This is a provider choice, not a finding that R2 satisfies WORM or immutable-retention requirements. If those controls are mandatory, verify them with Cloudflare or select a service that explicitly supports the approved retention policy before storing evidence or regulated data.

## 3. Database plan: SQLite to Neon Postgres

### Current SQLite-specific behavior and migration work

| Location | Current behavior | Postgres implementation requirement |
|---|---|---|
| [backend/app/config.py](../backend/app/config.py) | `database_url` defaults to an absolute SQLite path. A validator resolves relative SQLite URLs against the repo root. | Keep that exact default for local mode. Configure deployment only through environment. Do not coerce Postgres URLs through filesystem/path handling. |
| [backend/app/database.py](../backend/app/database.py) | Adds SQLite-only `check_same_thread=False`; creates a synchronous SQLAlchemy engine with `pool_pre_ping=True`. | Implemented: conditional SQLite args, psycopg v3, and bounded non-SQLite runtime pooling. Live Neon connectivity remains to be tested. |
| [backend/migrations/env.py](../backend/migrations/env.py) | Reads `settings.database_url`, configures Alembic, and uses `NullPool`; it already omits SQLite connection args for non-SQLite URLs. | Use the direct Neon URL for migrations. Preserve local SQLite upgrade support. |
| [backend/alembic.ini](../backend/alembic.ini) | Hardcodes `sqlite:///./medipredict.db`. | Treat this as the local default only; the migration environment currently overrides it from settings. Never put a production URL in the file. |
| [backend/migrations/versions/0002_add_provenance_columns.py](../backend/migrations/versions/0002_add_provenance_columns.py) | Uses a SQLAlchemy Boolean expression for the provenance backfill. | Offline PostgreSQL SQL rendering passes; live Postgres migration testing is still required. |
| [backend/app/main.py](../backend/app/main.py) | Calls `Base.metadata.create_all()` only when the configured engine is SQLite. | For Postgres, run `alembic -c backend/alembic.ini upgrade head` as a release/migration task with the direct connection string. |
| Existing ORM/migrations | Baseline creates facilities, medicines, logs, and predictions; later revisions add provenance, alert state, and dataset, event, and model-release registry tables. Baseline downgrade deliberately raises and must not drop application tables. | Apply forward with Alembic. Verify migrations on a disposable Postgres/Neon branch; do not attempt to downgrade past the intentionally non-destructive baseline. |
| Tests | Several backend tests explicitly use SQLite in-memory engines. | Preserve these local fast tests and add an isolated Postgres integration suite; do not mistake SQLite green tests for Postgres migration compatibility. |

### Driver and Neon connection policy

- Use SQLAlchemy’s synchronous `postgresql+psycopg://` driver with **psycopg 3**, declared in [backend/requirements.txt](../backend/requirements.txt).
- Runtime API: use Neon’s **pooled** connection string (PgBouncer/transaction pooling) to avoid exhausting backend connections. Set a small SQLAlchemy pool, keep transactions short, and do not rely on session-level settings or prepared statements that are incompatible with transaction pooling.
- Alembic/release task: use Neon’s **direct** connection string, not the pooler. Current [migration `env.py`](../backend/migrations/env.py) uses `NullPool`, which is suitable for a short migration connection; verify it with the selected Neon endpoint/driver.
- Keep both URLs in the Render secret store. The web service needs only the runtime URL; the migration task receives the direct URL only during a controlled release.
- Neon Free compute scales to zero after inactivity and the first request can wait for compute startup. Paid Launch can still scale to zero unless configured otherwise. For an interactive production dashboard, decide whether to disable scale-to-zero and budget for always-on compute. Do not treat sleep/wake as an API health failure without an explicit timeout/retry policy.

### Registry schema and remaining audit controls

The initial SQLAlchemy/Alembic registry is implemented. Dataset bytes/evidence are objects; metadata and verification/revocation event details are stored in the database. Current columns:

| Table | Implemented fields |
|---|---|
| `datasets` | `dataset_id` primary key, source SHA-256, unique object key, storage backend, byte and row counts, date range, frequency, synthetic flag, source, uploader label, upload timestamp, and structured metadata JSON. |
| `dataset_events` | UUID event ID, dataset ID and checksum, event type, actor label, timestamp, and event details JSON. New verification/revocation history is reconstructed from these event rows. |
| `model_releases` | Model version, source dataset reference/hash, artifact key/hash, metadata JSON, synthetic/validation flags, status, and creation timestamp. Existing model workflows do not yet write/read this table. |

The API currently inserts events, but the schema does not enforce append-only access or separate the application and migration roles. Actor fields still come from caller-supplied headers; they are labels, not authenticated identity. Before production, grant the runtime role only required permissions, deny event update/delete, add database-side guards, and use authenticated actor claims. If immutable audit export is required, use a separately controlled service with verified WORM support; do not assume R2 provides Object Lock.

### Migration test plan

1. Create a disposable Postgres test database/Neon branch with production-equivalent PostgreSQL major version and extensions.
2. Run `alembic upgrade head` from an empty database using the direct URL. Verify all revisions, indexes, foreign keys, defaults, booleans, uniqueness constraints, and timestamp behavior.
3. Insert and read fixture rows for every current model and each proposed registry event; check UTF-8 data, duplicate hashes, missing evidence objects, and database transactions.
4. Exercise `alembic downgrade 0001_baseline` from the latest provenance revision and upgrade to `head` again. Confirm the baseline’s intentional refusal to downgrade further; never test rollback by dropping baseline tables.
5. Repeat upgrade from a copy of the real local SQLite schema/data only after owner approval, first on a disposable copy. Compare row counts, primary/foreign keys, unique keys, provenance flags, and hashes. Do not connect a migration test to production.
6. Test pooled runtime URL behavior, connection exhaustion/recovery, idle wake behavior, and direct migration URL separately.

## 4. Backend on Render

### Build and process

**Recommendation: use the existing root [Dockerfile](../Dockerfile)** with repository root as the build context so the backend package, migrations, and shared `ml/` source are available. The [docker-compose.yml](../docker-compose.yml) and [frontend/Dockerfile](../frontend/Dockerfile) are local/container options; Vercel should build the frontend as a static Vite project instead of deploying the Nginx container.

#### Render Dockerfile path

The root `Dockerfile` exists at the repository root. If Render reports `failed to read dockerfile: open Dockerfile: no such file or directory`, its configured build context/root directory does not include that file, or the deployed branch/commit does not contain it. For this repository's root Dockerfile, configure the Render service as follows:

| Render setting | Value |
|---|---|
| Root Directory | Leave blank (repository root); do not set it to `backend` or `frontend`. |
| Dockerfile Path | `./Dockerfile` |
| Docker Build Context Directory | `.` (repository root), if shown as a separate setting. |
| Branch | The branch containing the committed root `Dockerfile` and `.dockerignore`. |

Save the settings and trigger a new deploy. If the Render service is intentionally rooted in a subdirectory, either change its root back to the repository root or set a Dockerfile path and context that are both valid relative to that root; the current root Dockerfile also needs the root-level `backend/`, `config/`, `ml/`, and requirements files, so simply pointing at it from a subdirectory is not sufficient. Check that the selected branch has the Dockerfile committed and that `.dockerignore` does not exclude it.

- Image build: the current root Dockerfile uses `python:3.12-slim` and installs [backend requirements](../backend/requirements.txt) and [ml_engine requirements](../ml_engine/requirements.txt). Review/pin the base image and dependencies for production. Do not copy `.env`, databases, `datasets/uploads`, training inputs, or developer virtual environments into the image.
- Web start command: the Docker image honors Render's assigned `PORT` and defaults to `8000` for local Compose. Confirm the service binds to Render's assigned port.
- Migration command: a controlled release/one-off job invoking `alembic -c backend/alembic.ini upgrade head` against the direct Neon URL before new API code is promoted. The Compose equivalent is `docker compose --profile deploy run --rm database-migrate`; set `MEDIPREDICT_DATABASE_URL` to the intended migration target before running it. Do not run that job against an already-created local SQLite database.
- Liveness: current route is `GET /api/v1/health`, returning a static `{"status":"ok"}`. It does not test the database or object store. Preserve a lightweight liveness endpoint and add a separate readiness check with bounded DB connectivity; avoid exposing credentials or bucket details in health output.
- Do not write durable state into the image or Render service filesystem. A persistent disk is not a substitute for shared object storage, database backup, or append-only evidence.

### Render environment variables

“Secret” indicates whether the value must remain confidential. Set API secrets in the Render service/job secret store, not in Git, an image, or Vercel.

| Name | Purpose | Secret? | Where set |
|---|---|---:|---|
| `MEDIPREDICT_APP_NAME` | Service label. | No | Render web service and local `.env`. |
| `MEDIPREDICT_DATABASE_URL` | Neon pooled PostgreSQL runtime connection string; SQLite URL remains local default. | Yes | Render web service; separate value per environment. |
| `MEDIPREDICT_CORS_ORIGINS` | Comma-separated exact browser origins allowed by FastAPI. | No | Render web service per environment. |
| `MEDIPREDICT_STORAGE_BACKEND` | `local` or `s3`; implemented default is `local`. `s3` mode reads the dashboard CSV and stores new dataset/evidence objects. | No | Local `.env` or Render per environment. |
| `MEDIPREDICT_UPLOADS_PATH` | Local storage root in local mode; not durable hosted storage. | No | Local `.env`; do not point at service ephemeral disk for production. |
| `MEDIPREDICT_OBJECT_STORE_BUCKET` | Private R2 bucket name. | No | Render service, separate bucket per environment. |
| `MEDIPREDICT_OBJECT_STORE_REGION` | S3 API region; `auto` for R2. | No | Render service. |
| `MEDIPREDICT_OBJECT_STORE_ENDPOINT_URL` | R2 S3 API endpoint, `https://<account-id>.r2.cloudflarestorage.com`. | No | Render service; account ID is not a credential. |
| `MEDIPREDICT_OBJECT_STORE_ACCESS_KEY_ID`, `MEDIPREDICT_OBJECT_STORE_SECRET_ACCESS_KEY` | R2 S3 API token credentials. | Yes | Render secret store; bucket-scoped token per service/environment. |
| `MEDIPREDICT_DASHBOARD_DATA_KEY` | Private CSV object key read by the dashboard API; if absent and a local source CSV exists, the backend uploads it once and verifies its SHA-256. | No | Render service, e.g. `staging/dashboard.csv`. |
| `MEDIPREDICT_ADMIN_API_KEY` | Existing temporary shared-key mechanism. | Yes | Render secret store only while legacy endpoint exists; do not expose to Vercel. Retire after user/role authentication is in place. |
| `MEDIPREDICT_MODEL_PATH`, `MEDIPREDICT_METRICS_PATH` | Current local model and metrics path settings. | No | Local only until the loader supports object storage; do not rely on deployed ephemeral paths. |
| `MEDIPREDICT_CSV_PATH` | Current local operational CSV path. | No | Local mode only. Hosted data should be explicitly registered and fetched by storage service, not baked into a deployment. |
| `MEDIPREDICT_TRAINING_MIN_RECORDS`, `MEDIPREDICT_TRAINING_MIN_RECORDS_MONTHLY`, `MEDIPREDICT_TRAINING_MIN_FACILITY_ITEMS`, `MEDIPREDICT_DATA_FREQUENCY` | Existing validation/training thresholds and frequency. | No | Local `.env` and Render job; review against approved data contract. |
| `MEDIPREDICT_ALERT_SMTP_HOST`, `MEDIPREDICT_ALERT_SMTP_PORT`, `MEDIPREDICT_ALERT_SMTP_STARTTLS`, `MEDIPREDICT_ALERT_SMTP_USERNAME`, `MEDIPREDICT_ALERT_SMTP_PASSWORD`, `MEDIPREDICT_ALERT_EMAIL_FROM`, `MEDIPREDICT_ALERT_EMAIL_TO` | Existing optional email alerts. | Credentials: Yes; other values: No | Render secret store/config only when alert dispatch is approved and enabled. |
| `MEDIPREDICT_ALERT_TWILIO_ACCOUNT_SID`, `MEDIPREDICT_ALERT_TWILIO_AUTH_TOKEN`, `MEDIPREDICT_ALERT_TWILIO_FROM`, `MEDIPREDICT_ALERT_SMS_TO` | Existing optional SMS alerts. | Account/auth token: Yes; other values: No | Render secret store/config only when approved and enabled. |
| Cloudinary API credentials *(proposed)* | Server-side signing/upload only for guide media. | API secret: Yes; cloud name/API key: public identifier or restricted | Render secret store; never Vercel browser env except explicitly public cloud name. |

For migrations, set `MEDIPREDICT_DATABASE_URL` to the Neon direct connection in the isolated release job; configure the API service separately with the pooled runtime connection. Any new imported Python package must be added to the matching requirements file.

For Render, set `MEDIPREDICT_STORAGE_BACKEND=s3`, the private R2 bucket, HTTPS endpoint, `auto` region, bucket-scoped R2 credentials, and `MEDIPREDICT_DASHBOARD_DATA_KEY` for the dashboard's source CSV. If the hosted service has no local CSV, upload the source object to that key before the first dashboard request; if a local CSV is present, the backend seeds a missing key and verifies its hash. Valid assessment uploads, training-upload CSVs, verification evidence, and generated feature/model bundles use the configured storage backend; training-upload metadata and provenance events require `MEDIPREDICT_DATABASE_URL` pointed at Neon after running Alembic through head. The API accesses R2 server-side; the browser never receives its credentials. Leave the backend's default `MEDIPREDICT_STORAGE_BACKEND=local` for existing local development. Existing local uploads are not migrated to R2 automatically when switching storage backends.

The checked-in dashboard time series has 50,160 rows and every row has `is_synthetic=true`; provenance also identifies unverified-seed district indicators and synthetic operational values. It can only be used as clearly disclosed demonstration data. It is not owner-verified operational data and is not suitable for training or advertising a real-data-trained model. Training requires a distinct reviewed source with independently valid target labels and an approved temporal evaluation.

### Free-tier behavior and jobs

Render documents that a free web service spins down after 15 minutes without inbound traffic and can take about one minute to spin back up. Free services have an ephemeral filesystem; local changes are lost on restart, redeploy, and spin-down. Free services cannot attach persistent disks or run one-off jobs. Free Render Postgres has a 1 GB limit, expires after 30 days, and does not support backups. These limitations make free Render unsuitable for production data or reliable upload/verification.

Run [ml/build_dataset.py](../ml/build_dataset.py), [ml/train.py](../ml/train.py), reference-data builders, and any CSV validation/scan pipeline as a **separate job**. For development, run them locally against approved synthetic data. For hosted training, use a separately provisioned worker/one-off job or controlled CI runner with explicit input IDs, execution approval, time/memory limits, private object permissions, captured logs, and immutable outputs. Never start a training subprocess from the web service or request handler.

## 5. Frontend on Vercel

### Build settings

| Setting | Value |
|---|---|
| Framework preset | Vite |
| Root directory | `frontend` |
| Install command | `npm ci` |
| Build command | `npm run build` |
| Output directory | `dist` |
| API endpoint | Public `VITE_API_URL` for the target backend origin; browser requests append `/api/v1/...`. |

The app makes relative requests. [frontend/vercel.json](../frontend/vercel.json) rewrites `/api/*` to Render on Vercel, while [frontend/vite.config.ts](../frontend/vite.config.ts) keeps local requests proxied to `http://localhost:8000`. Ensure the rewrite is present in the deployed Vercel branch. Never put API credentials in frontend configuration.

| Environment | `VITE_API_URL` | Data target |
|---|---|---|
| Local | Vite `/api` proxy to `http://localhost:8000`. | Local SQLite and local filesystem by default. |
| Preview | Vercel rewrite to the configured Render staging API. | Staging database and bucket only; synthetic data only. |
| Production | Vercel rewrite to the configured Render production API. | Production Neon project and private R2 bucket only, after approval gates. |

### CORS, previews, and plan terms

- Set `MEDIPREDICT_CORS_ORIGINS` to the exact production Vercel domain(s), exact staging domain(s), and only preview domains that are intentionally allowed. Do not allow arbitrary origins or rely on CORS to secure admin endpoints.
- Use a stable staging/preview hostname where possible. If per-branch Vercel preview URLs are needed, permit only a controlled pattern after verifying how the origin is validated; previews must never point at production write endpoints by default.
- Keep branch preview deployments on synthetic staging data. Protect preview URLs and avoid embedding production configuration into preview build environments.
- Vercel’s current Hobby plan is described as for personal projects; its fair-use page states Hobby is for non-commercial, personal use. MediPredict’s intended organizational/public-service use should therefore use a paid plan and have the account owned by the responsible organization. The official Vercel Terms were last updated **2026-10-19** when checked; review them and the applicable DPA before launch. This is a hosting-plan recommendation, not a legal conclusion.
- Vercel terms put responsibility on the customer for its content and services. Complete processor/subprocessor, international-transfer, security, and acceptable-use review before sending any health-related or otherwise sensitive data through Vercel.

## 6. Cloudinary: MediGuide scope only

Cloudinary is reserved for **approved MediGuide videos, thumbnails, and caption files**. It is not the registry or storage location for CSVs, model artifacts, verification evidence, source data, personal data, or any health data.

### Proposed organization

```text
medipredict/
  guide/
    staging/
      {guide_id}/v{content_version}/video
      {guide_id}/v{content_version}/thumbnail
      {guide_id}/v{content_version}/captions/{language}
    production/
      {guide_id}/v{content_version}/video
      {guide_id}/v{content_version}/thumbnail
      {guide_id}/v{content_version}/captions/{language}
```

Use non-identifying guide IDs, versioned asset names, documented language codes, and separate Cloudinary product environments/credentials for staging and production. Keep the approved source media and caption source files in the repository’s chosen content workflow or another approved content store; Cloudinary is a delivery copy, not the only archive.

### Upload and delivery policy

- Create a named, **signed** upload preset for approved guide media with fixed folder, allowed media types, upload size ceiling, deterministic versioning/no-overwrite behavior, and any required eager low-bandwidth renditions. Sign uploads on a trusted backend; keep the API secret server-side.
- Do not use an unsigned browser upload preset for production guide management. Cloudinary documents unsigned presets for client-side upload, but anyone with the preset details may attempt uploads; use that only for a separately reviewed constrained flow, not as the default.
- Public CDN delivery is acceptable only for content the content owner has approved as public. Cloudinary documents that normal `upload` assets are publicly accessible by default. Do not upload sensitive or restricted media on the assumption that an obscure public ID is private.
- Use responsive image/video outputs, capped dimensions, adaptive streaming where supported, and low-bandwidth quality/format transformations. Provide caption tracks (for example WebVTT) and a transcript; test quality and download sizes on low-bandwidth phones before release. Lock allowed transformations or pre-generate expected renditions to control cost/abuse.
- Offline packs should be a deliberate, user-triggered cache/download of approved guide-only media with a visible pack size, version, expiry/update behavior, and storage cleanup. Offline caching must never include CSV uploads, evidence, account tokens, personal records, or API responses containing health data.
- Set Cloudinary usage alerts and test captions, fallback poster images, and playback before production. No guide assets were found in the repository; asset ownership, language, release rights, and exact package contents remain open.

## 7. Security plan

| Risk/control | Plan |
|---|---|
| Secrets | Keep database URLs, object-store credentials, signing keys, OAuth client secrets, SMTP/Twilio secrets, and legacy admin key only in provider secret stores or untracked local env files. Use environment-specific, least-privilege credentials and rotate/revoke on staff changes or exposure. Never commit secrets, copy them into frontend `VITE_*` variables, or bake them into Docker images. |
| Admin identity | Replace the single shared API key with an identity provider (OIDC/SSO) and MFA for human administrators. Enforce roles for upload, verification, revocation, and download; derive actor identity from verified claims, not `X-Uploader`/`X-Admin-Identity`. Require independent uploader/verifier identities and record the authenticated principal. Keep separate machine identities for job services. |
| Rate limiting | Add edge/API limits by IP and authenticated actor, stricter limits for authentication, upload initiation, verification, revocation, and presigned URL issuance. Use per-user quotas and concurrency limits; return bounded retry guidance and monitor abuse. CORS does not prevent non-browser requests. |
| Upload validation | Preserve 20 MiB CSV/evidence limits initially; enforce request body limits before full buffering. Set content type and extension allowlists, generated object keys, request/row/column/time limits, schema validation, strict date/number bounds, and per-actor quotas. Treat user filename/MIME as untrusted. Do not allow arbitrary archive extraction or path-derived object keys. |
| Scanning | For CSV, parse with a strict CSV parser, reject malformed/oversized rows, validate encoding/headers/types, and check formula-like cells before any later spreadsheet export. For evidence, use an allowlist of reviewed formats, magic-byte detection, antivirus/malware scanning in an isolated job (for example ClamAV), and quarantine until scan/validation completes. Define failure behavior; never register a file as clean when scanning is unavailable. |
| CSV injection | Preserve original source bytes and their SHA-256. When rendering or exporting CSV values to spreadsheet-compatible formats, escape cells beginning with formula-trigger characters such as `=`, `+`, `-`, or `@`, and test leading whitespace/control-character variants. Do not mutate the source object to sanitize output. |
| Object integrity | Use private buckets, unique immutable keys, provider version IDs, object checksums, and independent streamed SHA-256 verification on both upload completion and every later read before parser/model use. Quarantine failures; emit a security event without logging file contents. |
| Model artifacts | Only load a model artifact published by the controlled training pipeline after signature/manifest and SHA-256 verification, metadata/provenance validation, dependency compatibility checks, and human promotion. Never load a model or `joblib` file from a user upload. Treat deserialization as code execution. |
| Logs and audit | Use structured logs with request ID, actor ID/role, action, status, and object/dataset IDs or hashes. Never log CSV rows, evidence bytes/text, tokens, presigned URLs, passwords, health data, or full request bodies. Restrict log access/retention; keep security audit events separately protected and append-only. |
| Dependencies | Preserve lockfiles and pin the backend/runtime and ML dependencies for the deploy image; use hashes/lock tooling where practical. Run vulnerability/license scanning and update review. Keep [backend/requirements.txt](../backend/requirements.txt) and [ml_engine/requirements.txt](../ml_engine/requirements.txt) accurate for imports in their respective code. Build immutable images and record the Git revision and dependency manifest with each model. |
| Network and IAM | TLS only; least privilege by environment and operation. Web service can read registered objects and request narrowly scoped uploads; training job can read approved inputs and write only its artifact prefixes; migration job can use DDL credentials only during release. Deny bucket listing to normal API principals. |
| Recovery | Test database restore and object retrieval against stored hashes. Alert on backup failures, hash mismatches, unexpected policy changes, unusual downloads, storage thresholds, and budget limits. Document incident handling and key revocation. |

## 8. Data governance and approval gates

This section raises issues for the data owner and qualified Rwanda counsel; it is **not legal advice or a conclusion about compliance**.

### Rwanda, residency, and processors

Before any real facility or health information is hosted, ask the data owner and local counsel to assess Rwanda’s Data Protection and Privacy Law and implementing requirements, the sensitivity/classification of facility and stock data, controller/processor roles, lawful authority and purpose, notices/consents where relevant, retention, data-subject rights, security, breach reporting, and cross-border transfer requirements. Confirm whether the selected Vercel, Render, Neon, AWS, and Cloudinary regions/subprocessors and support-access locations are acceptable. Confirm backup, log, CDN, telemetry, and support data locations too; a database region alone does not answer residency.

No hosting region is selected in this plan. Ask whether data must remain in Rwanda, whether approved regional hosting is acceptable, whether encrypted backups can leave the primary region, and whether contractual residency commitments are required. Do not assume a provider’s “region” covers support, logs, edge caching, replication, or subprocessors.

### Data classification before upload

Do not upload to staging or production until the owner has approved the specific file, fields, purpose, recipient service, region, license, and retention. In particular:

- Do not upload patient-level or otherwise directly/indirectly identifying health records, facility-level operational stock/consumption records, user accounts, source correspondence, signed letters, agreements, or evidence files without explicit owner approval and privacy/legal review.
- Do not upload mixed generated CSVs from [`datasets/medipredict_data/processed/`](../datasets/medipredict_data/processed/) as “real” or verified data. The repository [dataset provenance](../ml_engine/datasets/PROVENANCE.md) says these include synthetic operational fields, unverified seed indicators, real/derived facility attributes, and climate rows where the synthetic fallback is not distinguishable.
- Do not upload [`ml_engine/datasets/nisr/`](../ml_engine/datasets/nisr/) seed indicators as verified official statistics; the provenance record says no official publication URL is recorded and these values are unverified.
- Do not upload raw facility identifiers/coordinates or source evidence from [`datasets/medipredict_data/`](../datasets/medipredict_data/) to a new provider until the owner confirms the license, attribution, allowed processing, and whether the data is sensitive in context. A public source URL is not equivalent to owner authorization for this use.
- Do not upload any CSV, evidence, model, or health data to Cloudinary. MediGuide guide assets must also be approved for publication and rights-cleared.
- Do not copy production data into preview branches, developer laptops, training logs, analytics, crash reports, browser storage, or screenshots. Do not mix synthetic/demo and production records in a bucket, database, or model build.

### Roles, retention, and deletion

Define named roles and approval flow before enabling uploads:

| Action | Suggested permitted role | Required control |
|---|---|---|
| Upload dataset | Approved data steward/uploader | Authenticated account, owner-approved source, declared `is_synthetic`, schema scan, immutable checksum, audit record. |
| Verify dataset | Independent verifier | Must be a different authenticated person from uploader; source/method must be approved; verification bound to exact dataset hash and reporting period. |
| Revoke verification | Authorized verifier/data steward with revocation role | Reason required, append-only revocation event, alert and audit. |
| Download raw data/evidence | Explicitly authorized reviewer or job identity | Per-object authorization, short-lived URL or controlled stream, logged actor and purpose, no broad bucket list permission. |
| Publish/promote model | Model approver distinct from trainer where feasible | Verify source data status, temporal evaluation, provenance, immutable artifact hash, and release approval. |
| Delete/expire | Data owner/privacy administrator through approved process | Retention and deletion decision recorded; account for database copies, object versions, Object Lock retention, backups, logs, and derived models. |

Set separate retention periods for raw CSVs, evidence, verification/revocation records, audit events, training builds, model releases, backups, and Cloudinary media. No durations are assumed here. Any provider-enforced retention can conflict with deletion obligations; agree lawful basis, minimum period, legal-hold policy, and exception procedure before enabling such a control. Do not assume R2 offers Object Lock or version retention.

## 9. Environments and local compatibility

| Environment | Database | Object storage | Media | Data policy |
|---|---|---|---|---|
| Local | Existing `backend/medipredict.db` SQLite path and current Alembic behavior. | `local` storage adapter pointing at the existing `datasets/uploads` tree. Existing JSON metadata/verification files continue to work until a later migration plan changes that behavior. | No cloud media service required. | Keep “works exactly as today” as an acceptance criterion. Do not require cloud credentials; the Vite `/api` proxy must continue targeting localhost. |
| Staging | Separate Neon project/branch or staging database, never a production connection. | Dedicated private Cloudflare R2 bucket and scoped credentials. | Separate staging Cloudinary environment. | Synthetic fixtures only, each marked `is_synthetic=true` and labeled synthetic wherever displayed. No production copy. |
| Production | Separate production Neon project and credentials. | Separate production R2 bucket and scoped token; document retention and backup behavior without assuming WORM. | Separate production Cloudinary environment for approved public guide assets. | Only owner-approved, classified data; all inputs have explicit provenance. Synthetic demo data is never mixed into production. |

Introduce an explicit storage interface with a local implementation as the unchanged default and an S3-compatible implementation selected only by deployment configuration. Keep existing filesystem tests for local mode and add provider-backed integration tests for staging. Never fall back silently from a failed cloud operation to local or synthetic data; return/log a clear service error and preserve provenance.

## 10. Cost and limits snapshot

Values below are an official-page snapshot accessed on **2026-10-28**, not a quote. Region, taxes, overage, network, compute size, support, and data-retention choices can materially alter total cost.

| Provider/component | Free or minimum tier observed | Paid tier/current rates observed | When free stops being adequate / notes |
|---|---|---|---|
| Render web service | Free web services; spin down after 15 minutes idle, approximately one-minute spin-up, 750 free instance hours per workspace/month; ephemeral filesystem. | Current exact web instance and persistent-disk prices **not verified** from the reviewed page. Persistent disks are paid-service attachments. | Inadequate for any durable upload registry, always-available API, production database, or separate one-off job. Use paid service; disks still are not object storage. |
| Neon Postgres | Free: $0; 100 CU-hours/project, 1 GB/project and 20 GB/account storage, 5 GB public egress/project; auto-suspends after 5 minutes. Free history window 6 hours (1 GB limit). | Launch: $0.106/CU-hour, $0.35/GB-month storage, $0.20/GB-month instant-restore history (up to 7 days), 500 GB/project public egress included then $0.10/GB. | Upgrade when DB storage, CU-hours, egress, history/backup, support, or no-sleep availability is needed. Free hitting storage/compute/egress limits can block writes or suspend compute. Costs vary with usage. |
| AWS S3 | A current universally applicable free allowance **not verified** from the official pricing page; eligibility varies and must not be assumed. | Region/storage-class/request/data-transfer pricing is calculator-driven; numeric total **not verified** until region, GB-month, requests, retention/version count, restore volume, and encryption choice are known. | Pay from the selected region/class and request pattern. Budget for noncurrent versions, Object Lock retention, reads, backups, and egress. |
| Cloudflare R2 | Standard: 10 GB-month, 1 million Class A requests and 10 million Class B requests/month; egress free. | Standard: $0.015/GB-month; Class A $4.50/million, Class B $0.36/million; egress free. Infrequent Access: $0.01/GB-month, $9/million A, $0.90/million B, $0.01/GB retrieval; free tier does not apply to it. | Free stops when monthly storage/operation allowances are exceeded. Class A includes writes/list operations; Class B includes reads. Versioning/Object Lock suitability remains unverified. |
| Backblaze B2 | Free egress up to 3× average monthly stored volume; no free storage quota confirmed from the page. | Official page states $6.95/TB per 30 days and $0.01/GB beyond included egress; free egress through listed partners/CDNs is available. | Storage is paid from the first stored byte; egress beyond threshold, API behavior, and region requirements must be included in estimate. Strong lower-cost candidate if residency and Object Lock tests pass. |
| Supabase Storage | Free: 1 GB file storage and 5 GB egress; Free projects pause after one week of inactivity. | Pro from $25/month includes 100 GB file storage, then $0.0213/GB; includes 250 GB egress then $0.09/GB. | Free stops being adequate after storage/egress limits or if inactivity pause is unacceptable. Reviewed docs do not establish WORM/versioning for this requirement. |
| Cloudinary (guide assets only) | $0 Free plan, 25 monthly credits. One credit can be used as 1 GB managed storage, 1 GB bandwidth, or 1,000 transformations (video bandwidth uses the plan’s stated credit weighting). | Plus displayed at $99/month month-to-month ($89/month annual billing), 225 monthly credits; other tiers and enterprise terms vary. | Free is inadequate when guide storage/bandwidth/transforms exceed credits, production support/access controls are needed, or budget alerts are required. Do not put health or dataset files here. |
| Vercel frontend | Hobby $0 for personal/non-commercial use. | Pro displayed at $20/month; usage/region details and current terms apply. | Hobby is not suitable for MediPredict’s intended organizational/non-commercially personal context. Select Pro (or an approved organizational plan) before production. |

### Pricing sources and official limits pages

All links below are official provider pages; accessed **2026-10-28**.

| Ref | Source |
|---|---|
| [R1] | Render pricing: <https://render.com/pricing> |
| [R2] | Render disks, persistence, encryption, snapshots: <https://render.com/docs/disks> |
| [R3] | Render free services, sleep, ephemeral filesystem, limits: <https://render.com/docs/free> |
| [N1] | Neon pricing/limits: <https://neon.com/pricing> |
| [N2] | Neon pooled connection documentation: <https://neon.com/docs/connect/connection-pooling> |
| [N3] | Neon backup and restore options: <https://neon.com/docs/postgres/backup-restore/backups> |
| [R2-OBJ] | Cloudflare R2 pricing: <https://developers.cloudflare.com/r2/pricing/> |
| [R2-URL] | Cloudflare R2 presigned URLs: <https://developers.cloudflare.com/r2/api/s3/presigned-urls/> |
| [R2-PRIVATE] | Cloudflare R2 public-bucket controls: <https://developers.cloudflare.com/r2/buckets/public-buckets/> |
| [B1] | Backblaze B2 pricing: <https://www.backblaze.com/cloud-storage/pricing> |
| [B2] | Backblaze Object Lock: <https://www.backblaze.com/docs/cloud-storage-object-lock> |
| [B3] | Backblaze S3-compatible API, presigned URL and SSE notes: <https://www.backblaze.com/docs/cloud-storage-s3-compatible-api> |
| [A1] | AWS S3 pricing: <https://aws.amazon.com/s3/pricing/> |
| [A2] | AWS S3 versioning: <https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html> |
| [A3] | AWS S3 Object Lock/WORM: <https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html> |
| [A4] | AWS S3 server-side encryption: <https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingServerSideEncryption.html> |
| [A5] | AWS S3 presigned URLs and checksums: <https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html> |
| [S1] | Supabase pricing: <https://supabase.com/pricing> |
| [S2] | Supabase private buckets and signed access: <https://supabase.com/docs/guides/storage/buckets/fundamentals> |
| [C1] | Cloudinary pricing: <https://cloudinary.com/pricing> |
| [C2] | Cloudinary upload presets and signed/unsigned options: <https://cloudinary.com/documentation/upload_presets> |
| [C3] | Cloudinary media access controls and default public delivery behavior: <https://cloudinary.com/documentation/control_access_to_media> |
| [V1] | Vercel pricing: <https://vercel.com/pricing> |
| [V2] | Vercel Hobby plan: <https://vercel.com/docs/plans/hobby> |
| [V3] | Vercel fair-use guidelines, commercial-usage limits: <https://vercel.com/docs/limits/fair-use-guidelines#commercial-usage> |
| [V4] | Vercel Terms of Service (page showed “Last Updated October 19, 2026”): <https://vercel.com/legal/terms> |
| [V5] | Vercel deployment environments: <https://vercel.com/docs/deployments/environments> |

## 11. Staged implementation plan

The completed implementation slice is recorded in the phase report; remaining work should proceed in this order.

| Stage | Work | Exit criteria |
|---|---|---|
| 0. Approvals | Resolve the questions in §13; classify datasets; obtain written data-owner and counsel decisions on residency, service providers, approved uses, retention, access, and retention locks. | Approved data inventory, data-flow diagram, hosting region, provider/processor approval, retention schedule, budget owner. |
| 1. Local boundary | Dashboard data and new dataset/evidence objects use the storage abstraction; `local` remains the unchanged default. New dataset metadata and verification/revocation events use the database registry. | Local SQLite/files workflows and tests pass; no cloud credentials are required in local mode. Existing filesystem-only dataset records remain supported; no bulk migration is performed. |
| 2. Postgres compatibility | **Foundation and registry integration implemented:** psycopg 3, PostgreSQL URL normalization, bounded pool, dialect-neutral backfill, no Postgres `create_all()`, registry schema, and dataset metadata/event writes. | Still require a disposable/live Neon migration and transaction test, separate least-privilege app/migration roles, database-enforced append-only controls, and a tested backup/restore. |
| 3. Object store | Dashboard CSV, new dataset upload and evidence bytes use backend-only S3-compatible storage; dataset reads validate SHA-256 and object keys are server-generated. | Mocked S3 tests pass. Live R2 permission, upload/recovery, size, and role tests remain necessary. Model artifacts and existing uploads are not automatically moved. |
| 4. Auth and audit | Adopt OIDC/SSO/MFA; authorize upload/verify/revoke/download roles; derive actor identity from claims; add rate limits and redacted audit events. | Negative authorization tests pass; uploader/verifier separation is enforced; no secrets enter browser bundles or logs. |
| 5. ML jobs and artifact release | Containerize build/train as a separate job; pin dependencies; read approved object IDs; write immutable artifacts with manifests/checksums; secure promotion and loader verification. | Temporal validation and data provenance gates pass; no job runs in web process; serving path is tested against trusted release only. |
| 6. Frontend/API staging | Use the same-origin `/api` Vercel rewrite to Render while preserving the local Vite proxy; configure staging preview, Render staging API, exact origins, readiness, observability, and a synthetic fixture served from R2. | End-to-end browser-to-API staging, upload, admin auth, restart, object checksum, and preview isolation tests pass. |
| 7. Media and production readiness | Add approved guide media/captions to Cloudinary, offline guide-only cache, production security configuration, budget alerts, backups and restore drills. | Content owner signs off; accessibility/low-bandwidth checks pass; production readiness and incident/rollback exercises are approved. |
| 8. Production cutover | Deploy production schema and API, import only explicitly approved data, verify object hashes/provenance, enable controlled uploads, observe before traffic expansion. | Owner acceptance, migration/backup checks, known-good rollback rehearsal, monitoring, and on-call ownership in place. |

## 12. Rollback plan and remaining risks

### Rollback plan

1. **Frontend:** Vercel deployment rollback to the last known-good static build. Keep the previous frontend build compatible with the current API during the release window.
2. **API:** Render rollback to the last known-good image. Do not assume a database downgrade is safe. Use expand/contract migrations; first releases should be backward-compatible. Apply a forward fix for production schema changes.
3. **Database:** Before each migration, verify Neon restore point/history window and export a separate `pg_dump` to an approved private bucket. Test restore to a separate project/branch. Neon documents instant restore/PITR plan-dependent windows; the current Free plan offers only a short history window and is not a production backup strategy.
4. **Objects:** Never overwrite dataset/evidence/model keys. Do not depend on R2 version IDs or Object Lock unless confirmed for the account and tested. To roll back a model, point the release registry to the previous immutable model release after verifying its checksum and source dataset; do not mutate artifacts.
5. **Data import:** Keep source files and their hashes unchanged until the owner signs off on row counts, provenance, hashes, and the target. For a failed migration, disable intake, retain logs and object versions, restore only into an isolated recovery target, reconcile, and obtain owner approval before switching service pointers.
6. **Security incident:** Revoke the affected IAM/API/identity credentials, disable signed URL issuance, suspend uploads/downloads if required, preserve audit evidence, and follow the approved incident and notification process.

### Remaining risks

- No data owner, privacy lead, legal counsel, residency decision, user volume, data volume, or budget information was available in the repository.
- ML artifacts, feature-building, and some legacy dataset flows remain local-path oriented; neither R2 nor Neon has been integration-tested against the owner's accounts.
- SQLite migration tests and PostgreSQL offline SQL rendering pass, but migrations have not been applied to a live Postgres/Neon branch.
- Postgres API startup does not create tables; deployment must run Alembic through revision `0004` before starting the API.
- The current shared admin key and caller-supplied identity headers do not provide real user identity or robust separation of duties.
- Dataset object writes and database registry writes are coordinated with rollback cleanup for ordinary request failures, but a process crash can still leave an orphan object; a reconciliation/cleanup job is not implemented. Existing filesystem-only uploads are not auto-imported.
- The currently configured model loader, artifact outputs, and provenance registry do not share one storage contract. `joblib.load()` must only see trusted artifacts.
- Render free sleep, ephemeral filesystem, Neon Free compute sleep/limits, Vercel Hobby commercial restrictions, and provider service availability make free-tier composition unsuitable for production.
- R2 pricing, account configuration, backup/recovery, retention, and any separate WORM service costs still require owner review.
- An immutable evidence policy may conflict with deletion/retention obligations. Do not enable provider-enforced retention until counsel and the owner agree.
- Open or wildcard Vercel preview domains, public Cloudinary upload presets, mis-scoped presigned URLs, leaked S3 listing rights, secrets in frontend bundles, and unscanned evidence uploads are material exposure risks.
- Current repo generated datasets have mixed and incomplete provenance; uploads of those files could make synthetic or unverified values appear operationally authoritative.
- No guide assets or content licensing/approval records are currently present.

## 13. Open questions for the owner

These are intentional decision gates, not assumptions. Please answer before implementation or hosted data upload.

1. **Data volumes:** What are expected and maximum CSV sizes, datasets/month, rows/dataset, evidence files/month, total retained GB/year, model artifact size, and monthly downloads?
2. **Users and concurrency:** How many viewers, uploaders, verifiers, reviewers, and simultaneous API users are expected? Is the service public, restricted to partner facilities, or staff-only?
3. **Residency:** Must primary data, backups, logs, and support access stay in Rwanda? Which countries/regions are acceptable for processors, disaster recovery, and CDN delivery?
4. **Data authorization:** Who owns each CSV/evidence dataset, who can approve hosting, what legal basis/agreements exist, and which real operational or health fields are approved for which purpose?
5. **Budget:** What monthly budget is acceptable for the Render API/job, Vercel organizational plan, Neon, Cloudflare R2 requests/storage/egress, any separately approved immutable audit store, Cloudinary, monitoring, backups, and support? Is there a required maximum/spend alert?
6. **Availability:** What uptime target, response-time target, maintenance window, RPO/RTO, and maximum acceptable cold-start time are required?
7. **Retention/deletion:** How long may raw datasets, evidence, verification history, model artifacts, logs, and backups be retained? Are any records subject to legal hold or deletion request? Who approves lock retention?
8. **Identity:** Which organization identity provider (if any) must be used? Is MFA/SSO available? Who holds uploader, verifier, revocation, download, trainer, and release-approver roles?
9. **Training cadence:** Is training manual or scheduled, what is the expected runtime/CPU/RAM, which approved source datasets are eligible, and who approves model promotion?
10. **Media:** Who owns MediGuide content and publication rights? Which videos, languages, caption formats, thumbnail sizes, offline-pack scope, and maximum download sizes are required?
11. **Domains and previews:** What production/staging domains will be used? Should preview deployments be enabled, and which API/data may they access?
12. **Provider constraints:** Are Cloudflare, Neon, Render, Vercel, and Cloudinary approved organizational processors? Are there procurement, billing, support, or contractual security requirements?

## Phase report

- **Phase:** Backend storage foundation; local mode remains the default.
- **Files changed:** `backend/app/config.py`, `backend/app/storage.py`, `backend/app/main.py`, `backend/requirements.txt`, `backend/.env.example`, `.env.example`, `backend/tests/test_storage.py`, `docs/deployment_plan.md`.
- **Code/schema/database changes:** Added backend-only S3-compatible R2 reads for the configured dashboard CSV; retained local path reads by default. Added bounded reads (20 MiB maximum) and clear service-unavailable reporting rather than silently falling back when configured R2 reads fail. No database schema was changed and no credentials, buckets, or objects were provisioned.
- **Commands run:**
  - `& .\backend\.venv\Scripts\python.exe -m pip install "boto3>=1.35.74,<2" "botocore>=1.35.74,<2"`: passed; installed boto3 `1.43.120` and botocore `1.43.120`.
  - `& .\backend\.venv\Scripts\python.exe -m pytest backend\tests\test_storage.py backend\tests\test_csv_endpoints.py`: passed; `15 passed in 7.11s`.
  - `& .\backend\.venv\Scripts\python.exe -m pytest backend\tests`: passed; `130 passed in 92.24s`.
  - `Push-Location frontend; npm.cmd run build; $buildExitCode = $LASTEXITCODE; Pop-Location; exit $buildExitCode`: passed; Vite `6.4.4`, `42 modules transformed`, build completed in `1.76s`.
  - Vercel rewrite JSON validation: passed; `frontend/vercel.json: valid JSON`.
  - Workspace CSV inspection: `50,160` rows; `is_synthetic` counts were `True: 50,160`.
- **Known limitations:** R2 access has not been tested against the owner's account and requires Render environment configuration plus an uploaded CSV object. Upload intake, evidence/provenance journal, metadata registry, ML artifacts, and Neon/Postgres migrations are not yet moved off local files/SQLite. Repository data is synthetic/mixed provenance; no real-data model can be trained or claimed from it. Existing provider prices/terms remain the dated snapshot described in §10.

## Phase report

- **Phase:** Neon/Postgres migration foundation and Docker deployment wiring; local SQLite remains unchanged.
- **Files changed:** `backend/app/config.py`, `backend/app/database.py`, `backend/app/main.py`, `backend/app/models/entities.py`, `backend/app/models/__init__.py`, `backend/migrations/versions/0002_add_provenance_columns.py`, `backend/migrations/versions/0004_dataset_and_model_registry.py`, `backend/requirements.txt`, `backend/tests/test_database_config.py`, `backend/tests/test_migrations.py`, `backend/.env.example`, `.env.example`, `Dockerfile`, `docker-compose.yml`, `docs/deployment_plan.md`.
- **Code/schema changes:** Added psycopg 3 and normalized standard PostgreSQL URLs to its SQLAlchemy driver; bounded the non-SQLite connection pool; made the provenance backfill use portable Boolean values; retained local SQLite startup table creation but skipped `create_all()` for PostgreSQL; added dataset, dataset-event, and model-release registry schema; added an opt-in Compose migration job; and made the Docker image honor Render's `PORT`. Local Compose remains pinned to its `/data/medipredict.db` volume. The new metadata tables are not yet connected to upload, verification, dashboard, or model-serving routes.
- **Commands run:**
  - `& .\backend\.venv\Scripts\python.exe -m pytest backend\tests\test_migrations.py backend\tests\test_database_config.py`: passed; `4 passed in 2.11s`.
  - `& .\backend\.venv\Scripts\python.exe -m pytest backend\tests`: passed; `133 passed in 146.55s`.
  - `& .\backend\.venv\Scripts\python.exe -m pip install "psycopg[binary]>=3.2.3,<4"`: passed; installed psycopg and psycopg-binary `3.3.6`.
  - PostgreSQL offline migration render using `MEDIPREDICT_DATABASE_URL=postgresql://medipredict:dummy-pass@db.example.test/app` and `python -m alembic -c backend\alembic.ini upgrade head --sql`: passed; Alembic selected `PostgresqlImpl` and rendered all revisions through `0004_dataset_and_model_registry`.
  - `docker compose config --quiet`: passed after fixing Compose indentation.
  - `docker build -t medipredict-api:phase-db .`: could not run because Docker Desktop's Linux engine was unavailable (`dockerDesktopLinuxEngine` named pipe not found).
  - `git diff --check`: passed; Git reported only existing/configured LF-to-CRLF working-copy warnings.
- **Known limitations:** No Neon/Postgres server or credentials were available, so no live migration, pool, or transaction test was run. Docker image build/runtime could not be verified because the local Docker daemon is stopped/unavailable. At this earlier phase, the dataset registry tables were schema-only; this is superseded by the durable dataset/provenance persistence phase report below. Current source data remains synthetic/mixed provenance; real-data training is still blocked pending an approved labeled dataset.

## Phase report

- **Phase:** Durable dataset and provenance persistence; local SQLite/files remain the default.
- **Files changed:** `backend/app/main.py`, `backend/app/storage.py`, `backend/tests/test_csv_endpoints.py`, `backend/tests/test_provenance.py`, `backend/tests/test_storage.py`, `docker-compose.yml`, `docs/deployment_plan.md`.
- **Code/schema changes:** Dataset upload now writes CSV bytes through the configured local or S3-compatible object store, verifies the stored SHA-256, and saves metadata plus upload events in `datasets`/`dataset_events`. Dataset detail, listing, and provenance resolution read from the registry; verification and revocation events are persisted in the database, and evidence bytes are stored as checksum-verified objects. Local storage preserves the existing files and `metadata.json` sidecar. CSV reads are bounded at 20 MiB, and local object keys reject path traversal. Compose passes object-store settings while keeping SQLite and local storage as defaults.
- **Commands run:**
  - `& .\backend\.venv\Scripts\python.exe -m pytest backend\tests\test_csv_endpoints.py backend\tests\test_provenance.py backend\tests\test_storage.py`: passed; `35 passed in 5.25s`.
  - `& .\backend\.venv\Scripts\python.exe -m pytest backend\tests`: passed; `139 passed in 82.03s`.
  - `docker compose config --quiet`: passed.
  - `& .\backend\.venv\Scripts\python.exe -m py_compile backend\app\main.py backend\app\storage.py backend\app\models\entities.py`: passed.
  - `Push-Location frontend; npm.cmd run build; $buildExitCode = $LASTEXITCODE; Pop-Location; exit $buildExitCode`: passed; TypeScript check succeeded and Vite built 42 modules in 3.20s.
  - `docker build -t medipredict-api:durable-storage .`: could not run because Docker Desktop's Linux engine pipe was unavailable (`dockerDesktopLinuxEngine` named pipe not found).
  - `git diff --check`: passed; Git emitted its configured LF-to-CRLF working-copy warning.
  - Live checks with `curl.exe`: Render `/api/v1/health`, `/api/v1/inventory/summary`, `/api/v1/predictions/risk-register?limit=1`, `/api/v1/alerts`, `/api/v1/transfers/recommendations`, and `/api/v1/analytics/trust-metrics` each returned HTTP `200`; Vercel frontend returned HTTP `200`. These reflect the deployment before the new changes are pushed.
- **Known limitations:** S3/R2 behavior is mocked in tests; no live R2 bucket or Neon database credentials were available. Configure Render with the Neon runtime URL, run Alembic through revision `0004` using the direct URL, configure private R2 credentials, then deploy these changes. Existing local uploads are not auto-migrated. A process crash between object write and DB commit can leave an orphan object; reconciliation is not implemented. Dataset event writes are not protected by database-enforced append-only grants, and actor identity remains caller-supplied. The dashboard's operational source remains synthetic demonstration data and current risk output remains rule-based; this work does not create genuine data or a trained model.
