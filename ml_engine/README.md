# MediPredict model pipeline

The `ml_engine/pipeline/train.py` trainer is deprecated. Its random row split and same-row label leakage make its metrics invalid evidence. Do not use its metrics or artifact for evaluation or serving.

Phase 4 training is `python -m ml.train <feature-build-id>` from the repository root. It requires an explicitly built and validated feature table from `ml.build_dataset` and stores immutable model/evaluation artifacts in `ml/models/`. The legacy artifact is retained but is not valid evidence and is not served.
