"""Load and validate MediPredict reference tables."""
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
FACILITIES_PATH = ROOT / "ml_engine" / "datasets" / "processed" / "facilities.csv"
DISTRICT_INDICATORS_PATH = ROOT / "ml_engine" / "datasets" / "nisr" / "district_indicators.csv"
PERCENTAGE_COLUMNS = ["poverty_rate_pct", "health_insurance_pct", "malaria_prevalence_pct", "facility_delivery_pct"]


def _read_required(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Required reference table not found: {path}")
    return pd.read_csv(path)


def load_facilities(path: Path = FACILITIES_PATH) -> pd.DataFrame:
    table = _read_required(path)
    required = ["facility_id", "name", "type", "district", "province", "latitude", "longitude", "source"]
    _validate_columns(table, required, "facilities")
    if table[[column for column in required if column != "name"]].isnull().any().any():
        raise ValueError("Facilities table contains null required values")
    if not table["type"].isin(["Hospital", "Health Center", "Health Post", "Dispensary", "Pharmacy", "Other"]).all():
        raise ValueError("Facilities table contains an unrecognized standardized type")
    return table


def load_district_indicators(path: Path = DISTRICT_INDICATORS_PATH) -> pd.DataFrame:
    table = _read_required(path)
    required = ["district", "province", "population", "under5_population", "women_15_49", *PERCENTAGE_COLUMNS,
                "source_name", "source_year", "verified", "notes"]
    _validate_columns(table, required, "district indicators")
    if len(table) != 30 or table["district"].nunique() != 30:
        raise ValueError(f"District indicators must contain 30 unique districts; found {table['district'].nunique()}")
    if table[required].isnull().any().any():
        raise ValueError("District indicators contain null required values")
    for column in PERCENTAGE_COLUMNS:
        values = pd.to_numeric(table[column], errors="coerce")
        if values.isnull().any() or not values.between(0, 100).all():
            raise ValueError(f"{column} must contain percentages between 0 and 100")
    if not table["verified"].astype(str).str.casefold().isin(["false", "0"]).all():
        raise ValueError("Seed district indicator rows must remain unverified")
    return table


def _validate_columns(table: pd.DataFrame, required: list[str], label: str) -> None:
    missing = [column for column in required if column not in table.columns]
    if missing:
        raise ValueError(f"{label} missing required columns: {', '.join(missing)}")


def load_reference_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (facilities, district indicators), validating both before return."""
    return load_facilities(), load_district_indicators()



