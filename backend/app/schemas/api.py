from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

ProvenanceStatus = Literal["synthetic", "uploaded_unverified", "verified"]


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class CreateUserRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)


class AuthUserResponse(BaseModel):
    id: str
    email: str
    role: Literal["admin", "user"]


class AuthSessionResponse(BaseModel):
    user: AuthUserResponse
    csrf_token: str


class VerificationSummary(BaseModel):
    source_id: str | None = None
    source_name: str | None = None
    verification_method: str | None = None
    verified_by: str | None = None
    verified_at: str | None = None
    single_party: bool | None = None
    identity_note: str | None = None


class ProvenanceResponse(BaseModel):
    dataset_id: str
    provenance_status: ProvenanceStatus
    verification: dict | None = None
    verification_summary: VerificationSummary | None = None
    warning: str | None = None


class DatasetDetail(BaseModel):
    dataset_id: str
    sha256: str | None
    row_count: int | None
    date_range: dict[str, str | None]
    data_frequency: Literal["daily", "monthly"] | None
    is_synthetic: bool | None
    data_source: Literal["uploaded"]
    uploader: str | None = None
    uploaded_at_utc: str | None = None
    provenance_status: ProvenanceStatus
    verification: dict | None = None
    verification_summary: VerificationSummary | None = None
    warning: str | None = None
    training_status: Literal["queued", "running", "completed", "failed"] | None = None
    candidate_model_version: str | None = None
    candidate_model_validated: bool | None = None
    training_error: str | None = None


class Summary(BaseModel):
    facilities: int
    districts: int
    medicines: int
    critical: int
    moderate: int
    stable: int
    unknown: int = 0
    stock_units: int
    reporting_date: str
    data_source: str | None = None
    is_synthetic: bool | None = None
    provenance_status: ProvenanceStatus = "uploaded_unverified"

class RiskRecord(BaseModel):
    model_config = ConfigDict(protected_namespaces=("model_dump",))

    facility: str
    district: str
    province: str
    medicine_code: str
    medicine: str
    stock_units: float
    daily_consumption: float
    lead_time_days: float | None
    estimated_stock_after_7_days: float | None
    estimated_stock_after_14_days: float | None
    risk_level: str
    confidence: float | None
    confidence_note: str
    method: Literal["rule_based_fallback"]
    model_version: None
    model_validated: Literal[False]
    data_source: str
    is_synthetic: bool | None
    under5_population: int
    poverty_rate: float
    malaria_prevalence: float
    provenance_status: ProvenanceStatus = "uploaded_unverified"

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
    provenance_status: ProvenanceStatus = "uploaded_unverified"
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
    provenance_status: Literal["synthetic", "uploaded_unverified"]

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
    estimated_stock_after_7_days: float | None
    estimated_stock_after_14_days: float | None
    risk_level: str
    confidence: float | None
    confidence_note: str
    method: Literal["rule_based_fallback"]
    model_version: None
    model_validated: Literal[False]
    data_source: Literal["uploaded"]
    is_synthetic: bool | None
    provenance_status: Literal["synthetic", "uploaded_unverified"]
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
    unknown: int = 0
    method: Literal["rule_based_fallback"]
    model_version: None
    model_validated: Literal[False]
    data_source: Literal["uploaded"]
    is_synthetic: bool | None
    provenance_status: Literal["synthetic", "uploaded_unverified"]
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
    provenance_status: ProvenanceStatus
    verification_summary: VerificationSummary | None = None
    training_status: Literal["queued"] = "queued"


class TrainingJobStatus(BaseModel):
    model_config = ConfigDict(protected_namespaces=("model_dump",))

    dataset_id: str
    status: Literal["queued", "running", "completed", "failed"]
    model_version: str | None = None
    model_validated: bool | None = None
    is_synthetic: bool | None = None
    error: str | None = None
    updated_at: str

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
    provenance_status: ProvenanceStatus = "uploaded_unverified"

class StockAlert(BaseModel):
    alert_id: str
    alert_type: Literal["stockout", "critical_stock", "low_stock", "cover_unavailable", "invalid_data"]
    severity: Literal["critical", "warning"]
    facility: str
    district: str
    medicine: str
    medicine_code: str
    reporting_date: str
    stock_units: float | None
    daily_consumption: float | None
    lead_time_days: float | None
    estimated_stock_after_7_days: float | None
    estimated_stock_after_14_days: float | None
    risk_level: str
    data_source: str
    is_synthetic: bool
    provenance_status: ProvenanceStatus = "uploaded_unverified"
    message: str

class FeatureImportance(BaseModel):
    feature: str
    importance: float

class TrustMetrics(BaseModel):
    model_config = ConfigDict(protected_namespaces=("model_dump",))

    accuracy: float | None
    labels: list[str]
    precision: list[float]
    recall: list[float]
    confusion_matrix: list[list[int]]
    feature_importances: list[FeatureImportance]
    source: str
    provenance_status: ProvenanceStatus = "uploaded_unverified"
    verification: dict | None = None
    model_validated: bool = False
