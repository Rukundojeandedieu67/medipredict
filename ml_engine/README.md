# MediPredict model pipeline

Copy `ml_engine/.env.example` to `ml_engine/.env` to configure the training CSV with `ML_ENGINE_TRAINING_DATA_PATH` and the artifact directory with `ML_ENGINE_ARTIFACTS_DIR`. Relative paths are resolved from `ml_engine`; without an input override, training searches `ml_engine/datasets` and `datasets/medipredict_data/processed`.

Run `python ml_engine/pipeline/train.py` from the repository root. Training stores the fitted scikit-learn pipeline and evaluation metrics in `ml_engine/models_store/` by default. The pipeline includes numeric population, poverty, malaria and rainfall features plus categorical medicine, district and facility type features.
