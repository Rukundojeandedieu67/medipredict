# MediPredict model pipeline

The `ml_engine/pipeline/train.py` trainer is deprecated. Its random row split and same-row label leakage make its metrics invalid evidence. Do not use its metrics or artifact for evaluation or serving.

Phase 4 preparation and training are run from the repository root, in order:

For a real, non-synthetic CSV accepted by the protected training-upload endpoint and stored locally, run `python -m ml.train_uploaded_dataset <dataset-id>`. It verifies the upload hash, builds validated features, and writes an immutable candidate/evaluation bundle under `ml/models/<model-version>/`. The lower-level commands remain available separately: `python -m ml.build_dataset <dataset-id>` writes a feature table, then `python -m ml.train <feature-build-id>` trains from that build.

Until approved real data is available, `python -m ml.train_synthetic` runs the same feature and evaluation pipeline on generated synthetic supply histories without requiring cloud storage or a training upload. It retains the synthetic source and writes a candidate bundle, but the result is explicitly labeled synthetic, is not evidence of real-world performance, and cannot be promoted or served. Do not use the generated candidate as a real model. For uploads stored in Aiven/R2, use `python -m ml.train_registered_dataset <dataset-id>` instead; it persists hashed bundles and registry metadata to those services.

The bundle metadata records SHA-256 hashes for its model, calibrator, and feature-builder state. A candidate is eligible for promotion only when its `model_validated` field is exactly `true` and its real-data provenance is verified. Neither command promotes or deploys a model. The legacy artifact is retained but is not valid evidence and is not served. When using Docker Compose, run the `feature-build` and `training` one-off services with the `ml` profile; see the root README for their inputs and commands.
