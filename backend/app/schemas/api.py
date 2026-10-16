from pydantic import BaseModel, ConfigDict
from typing import Literal

class Summary(BaseModel):
    facilities: int
    districts: int
    medicines: int
    critical: int
    moderate: int
    stable: int
    stock_units: int
    reporting_date: str
    data_source: str | None = None
    is_synthetic: bool | None = None

class RiskRecord(BaseModel):
    model_config = ConfigDict(protected_namespaces=("model_dump",))

    facility: str
    district: str
    province: str
    medicine_code: str
    medicine: str
    stock_units: float
    daily_consumption: float
    lead_time_days: float
    risk_level: str
    confidence: float | None
    confidence_note: str
    method: str
    model_version: str | None
    model_validated: bool
    data_source: str
    is_synthetic: bool
    under5_population: int
    poverty_rate: float
    malaria_prevalence: float

class UploadResult(BaseModel):
    model_config = ConfigDict(protected_namespaces=("model_dump",))

    records_received: int
    predictions: int
    critical: int
    moderate: int
    stable: int
    method: str
    model_version: str | None
    model_validated: bool
    data_source: str
    is_synthetic: bool | None
    confidence_note: str
    items: list[RiskRecord]

class ValidationIssue(BaseModel):
    row_number: int | None
    column: str
    code: str
    message: str

class CsvValidationReport(BaseModel):
    valid: bool
    purpose: Literal["assessment", "training"]
    data_frequency: Literal["daily", "monthly"]
    row_count: int
    facility_item_count: int
    errors: list[ValidationIssue]
    warnings: list[ValidationIssue]
    total_counts: dict[str, int | bool]
    date_range: dict[str, str | None]
    is_synthetic: bool | None

class CsvAssessmentItem(BaseModel):
    model_config = ConfigDict(protected_namespaces=("model_dump",))

    facility_id: str
    item_id: str
    date: str
    stock_on_hand: float
    units_consumed: float
    units_received: float
    stockout_flag: bool
    lead_time_days: float | None
    risk_level: str
    confidence: float | None
    confidence_note: str
    method: Literal["rule_based_fallback"]
    model_version: None
    model_validated: Literal[False]
    data_source: Literal["uploaded"]
    is_synthetic: bool
    facility_type: str | None = None
    region: str | None = None
    reorder_level: float | None = None
    stockout_flag_assumption: str | None = None

class CsvAssessmentResult(BaseModel):
    model_config = ConfigDict(protected_namespaces=("model_dump",))

    records_received: int
    predictions: int
    critical: int
    moderate: int
    stable: int
    method: Literal["rule_based_fallback"]
    model_version: None
    model_validated: Literal[False]
    data_source: Literal["uploaded"]
    is_synthetic: bool | None
    confidence_note: str
    validation: CsvValidationReport
    items: list[CsvAssessmentItem]

class TrainingUploadResult(BaseModel):
    dataset_id: str
    sha256: str
    row_count: int
    date_range: dict[str, str | None]
    data_frequency: Literal["daily", "monthly"]
    is_synthetic: bool | None
    data_source: Literal["uploaded"]
    metadata_path: str

class TransferCandidate(BaseModel):
    donor_facility: str
    donor_district: str
    recipient_facility: str
    recipient_district: str
    medicine: str
    available_units: float
    requested_units: float
    donor_lead_time_days: float
    recipient_lead_time_days: float
    data_source: str
    is_synthetic: bool

class FeatureImportance(BaseModel):
    feature: str
    importance: float

class TrustMetrics(BaseModel):
    accuracy: float | None
    labels: list[str]
    precision: list[float]
    recall: list[float]
    confusion_matrix: list[list[int]]
    feature_importances: list[FeatureImportance]
    source: str
