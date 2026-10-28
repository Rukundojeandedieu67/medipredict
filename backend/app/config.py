from pathlib import Path
from typing import Literal
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
    uploads_path: Path = ROOT / "datasets/uploads"
    admin_api_key: str | None = None
    training_min_records: int = 90
    training_min_records_monthly: int = 24
    training_min_facility_items: int = 12
    data_frequency: Literal["daily", "monthly"] = "daily"
    alert_smtp_host: str | None = None
    alert_smtp_port: int = 587
    alert_smtp_starttls: bool = True
    alert_smtp_username: str | None = None
    alert_smtp_password: str | None = None
    alert_email_from: str | None = None
    alert_email_to: str = ""
    alert_twilio_account_sid: str | None = None
    alert_twilio_auth_token: str | None = None
    alert_twilio_from: str | None = None
    alert_sms_to: str = ""
    alert_cooldown_hours: int = 24

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

    @field_validator("model_path", "metrics_path", "csv_path", "uploads_path", mode="before")
    @classmethod
    def resolve_paths_from_repository_root(cls, value: str | Path) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else (ROOT / path).resolve()

    @field_validator("alert_smtp_port")
    @classmethod
    def validate_alert_smtp_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("Alert SMTP port must be between 1 and 65535.")
        return value

    @field_validator("alert_cooldown_hours")
    @classmethod
    def validate_alert_cooldown(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Alert cooldown must be at least one hour.")
        return value

    @property
    def allowed_origins(self):
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


settings = Settings()
