from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
class Settings(BaseSettings):
    app_name: str = "MediPredict Rwanda"
    database_url: str = f"sqlite:///{(ROOT / 'backend' / 'medipredict.db').as_posix()}"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    model_path: Path = ROOT / "ml_engine/models_store/medipredict_rf_model.pkl"
    metrics_path: Path = ROOT / "ml_engine/models_store/medipredict_metrics.json"
    csv_path: Path = ROOT / "datasets/medipredict_data/processed/medipredict_facility_timeseries_2026.csv"
    model_config = SettingsConfigDict(env_prefix="MEDIPREDICT_", env_file=ROOT / ".env", extra="ignore")
    @property
    def allowed_origins(self): return [item.strip() for item in self.cors_origins.split(",") if item.strip()]
settings = Settings()
