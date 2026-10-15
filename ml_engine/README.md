# MediPredict model pipeline

Run `python ml_engine/pipeline/train.py` from the repository root. Training reads the processed facility time-series CSV and stores the fitted scikit-learn pipeline and evaluation metrics in `ml_engine/models_store/`. The pipeline includes numeric population, poverty, malaria and rainfall features plus categorical medicine, district and facility type features.
