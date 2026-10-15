from pydantic import BaseModel, ConfigDict

class Summary(BaseModel):
    facilities: int
    districts: int
    medicines: int
    critical: int
    moderate: int
    stable: int
    stock_units: int
    reporting_date: str

class RiskRecord(BaseModel):
    facility: str
    district: str
    province: str
    medicine_code: str
    medicine: str
    stock_units: float
    daily_consumption: float
    lead_time_days: float
    risk_level: str
    confidence: float
    under5_population: int
    poverty_rate: float
    malaria_prevalence: float

class UploadResult(BaseModel):
    records_received: int
    predictions: int
    critical: int
    moderate: int
    stable: int
    items: list[RiskRecord]

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

class FeatureImportance(BaseModel):
    feature: str
    importance: float

class TrustMetrics(BaseModel):
    accuracy: float
    labels: list[str]
    precision: list[float]
    recall: list[float]
    confusion_matrix: list[list[int]]
    feature_importances: list[FeatureImportance]
    source: str
