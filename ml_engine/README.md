# MediPredict model pipeline

The `ml_engine/pipeline/train.py` trainer is deprecated. Its random row split and same-row label leakage make its metrics invalid evidence. Do not use its metrics or artifact for evaluation or serving.

Phase 4 preparation and training are run from the repository root, in order:

1. `python -m ml.build_dataset <dataset-id>` consumes a registered upload from the configured `MEDIPREDICT_UPLOADS_PATH` and writes a validated, hashed feature table under `ml/artifacts/feature_tables/`.
2. `python -m ml.train <feature-build-id>` consumes that exact feature build and writes an immutable model/evaluation bundle under `ml/models/<model-version>/`.

The bundle metadata records SHA-256 hashes for its model, calibrator, and feature-builder state. A candidate is eligible for promotion only when its `model_validated` field is exactly `true` and its real-data provenance is verified. Neither command promotes or deploys a model. The legacy artifact is retained but is not valid evidence and is not served. When using Docker Compose, run the `feature-build` and `training` one-off services with the `ml` profile; see the root README for their inputs and commands.
