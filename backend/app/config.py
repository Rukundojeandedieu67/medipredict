from pathlib import Path
from urllib.parse import urlencode
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "MediPredict Rwanda"
    database_url: str = f"sqlite:///{(ROOT / 'backend' / 'medipredict.db').as_posix()}"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    model_path: Path = ROOT / "ml_engine/models_store/medipredict_rf_model.pkl"
    metrics_path: Path = ROOT / "ml_engine/models_store/medipredict_metrics.json"
    csv_path: Path = ROOT / "datasets/medipredict_data/processed/medipredict_facility_timeseries_2026.csv"

    model_config = SettingsConfigDict(
        env_prefix="MEDIPREDICT_",
        env_file=(ROOT / ".env", ROOT / "backend" / ".env"),
        extra="ignore",
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def resolve_relative_sqlite_urls(cls, value: str) -> str:
        url = make_url(value)
        if url.get_backend_name() != "sqlite" or not url.database:
            return value
        database_path = Path(url.database).expanduser()
        if database_path.is_absolute() or url.database == ":memory:":
            return value
        resolved_path = (ROOT / database_path).resolve().as_posix()
        query = urlencode(url.query, doseq=True)
        return f"{url.drivername}:///{resolved_path}" + (f"?{query}" if query else "")

    @field_validator("model_path", "metrics_path", "csv_path", mode="before")
    @classmethod
    def resolve_paths_from_repository_root(cls, value: str | Path) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else (ROOT / path).resolve()

    @property
    def allowed_origins(self):
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


settings = Settings()
