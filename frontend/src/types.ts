export type ProvenanceStatus = "synthetic" | "uploaded_unverified" | "verified";

export interface VerificationBlock {
  event: "verification";
  source_id: string;
  verification_method: string;
  verification_reference: string;
  reporting_period_start: string;
  reporting_period_end: string;
  dataset_id: string;
  dataset_sha256: string;
  verified_by: string | null;
  verified_at: string;
  single_party: boolean;
  identity_note?: string | null;
  evidence_file_sha256?: string;
  source: {
    source_id: string;
    name: string | null;
    organization: string | null;
    system: string | null;
  };
}

export interface VerificationSummary {
  source_id: string | null;
  source_name: string | null;
  verification_method: string | null;
  verified_by: string | null;
  verified_at: string | null;
  single_party: boolean | null;
  identity_note: string | null;
}

export interface DatasetProvenance {
  dataset_id: string;
  provenance_status: ProvenanceStatus;
  verification: VerificationBlock | null;
  verification_summary: VerificationSummary | null;
  warning: string | null;
}

export interface DatasetDetail extends DatasetProvenance {
  sha256: string | null;
  row_count: number | null;
  date_range: { start: string | null; end: string | null };
  data_frequency: "daily" | "monthly" | null;
  is_synthetic: boolean | null;
  data_source: "uploaded";
  uploader: string | null;
  uploaded_at_utc: string | null;
}

export interface TrainingUploadResult extends DatasetProvenance {
  sha256: string;
  row_count: number;
  date_range: { start: string | null; end: string | null };
  data_frequency: "daily" | "monthly";
  is_synthetic: boolean | null;
  data_source: "uploaded";
  metadata_path: string;
}

export interface Summary {
  facilities: number;
  districts: number;
  medicines: number;
  critical: number;
  moderate: number;
  stable: number;
  unknown: number;
  stock_units: number;
  reporting_date: string;
  data_source: "real" | "synthetic" | "uploaded" | null;
  is_synthetic: boolean | null;
  provenance_status: ProvenanceStatus;
}

export interface RiskRecord {
  facility: string;
  district: string;
  province: string;
  medicine_code: string;
  medicine: string;
  stock_units: number;
  daily_consumption: number;
  lead_time_days: number | null;
  estimated_stock_after_7_days: number | null;
  estimated_stock_after_14_days: number | null;
  risk_level: string;
  confidence: number | null;
  confidence_note: string;
  method: "rule_based_fallback";
  model_version: null;
  model_validated: false;
  data_source: "real" | "synthetic" | "uploaded";
  is_synthetic: boolean;
  under5_population: number;
  poverty_rate: number;
  malaria_prevalence: number;
  provenance_status: ProvenanceStatus;
  verification?: VerificationBlock | null;
}

export interface TransferCandidate {
  donor_facility: string;
  donor_district: string;
  recipient_facility: string;
  recipient_district: string;
  medicine: string;
  available_units: number;
  requested_units: number;
  donor_lead_time_days: number;
  recipient_lead_time_days: number;
  data_source: "real" | "synthetic" | "uploaded";
  is_synthetic: boolean;
  provenance_status: ProvenanceStatus;
}

export interface FeatureImportance {
  feature: string;
  importance: number;
}

export interface TrustMetrics {
  accuracy: number | null;
  labels: string[];
  precision: number[];
  recall: number[];
  confusion_matrix: number[][];
  feature_importances: FeatureImportance[];
  source: string;
  provenance_status: ProvenanceStatus;
  verification: VerificationBlock | null;
  model_validated: boolean;
}

export interface UploadResult {
  records_received: number;
  predictions: number;
  critical: number;
  moderate: number;
  stable: number;
  unknown: number;
  method: "rule_based_fallback";
  model_version: string | null;
  model_validated: boolean;
  data_source: "real" | "synthetic" | "uploaded";
  is_synthetic: boolean | null;
  provenance_status: "synthetic" | "uploaded_unverified";
  confidence_note: string;
  validation: CsvValidationReport;
  items: CsvAssessmentItem[];
}

export interface StockAlert {
  alert_id: string;
  alert_type: "stockout" | "critical_stock" | "low_stock" | "cover_unavailable" | "invalid_data";
  severity: "critical" | "warning";
  facility: string;
  district: string;
  medicine: string;
  medicine_code: string;
  reporting_date: string;
  stock_units: number | null;
  daily_consumption: number | null;
  lead_time_days: number | null;
  estimated_stock_after_7_days: number | null;
  estimated_stock_after_14_days: number | null;
  risk_level: string;
  data_source: "real" | "synthetic" | "uploaded";
  is_synthetic: boolean;
  provenance_status: ProvenanceStatus;
  message: string;
}

export interface ValidationIssue {
  row_number: number | null;
  column: string;
  code: string;
  message: string;
}

export interface CsvValidationReport {
  valid: boolean;
  purpose: "assessment" | "training";
  data_frequency: "daily" | "monthly";
  row_count: number;
  facility_item_count: number;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
  total_counts: {
    errors: number;
    warnings: number;
    returned_errors: number;
    returned_warnings: number;
    errors_truncated: boolean;
    warnings_truncated: boolean;
  };
  date_range: { start: string | null; end: string | null };
  is_synthetic: boolean | null;
  provenance_status: "synthetic" | "uploaded_unverified";
}

export interface CsvAssessmentItem {
  facility_id: string;
  item_id: string;
  date: string;
  stock_on_hand: number;
  units_consumed: number;
  units_received: number;
  stockout_flag: boolean;
  lead_time_days: number | null;
  estimated_stock_after_7_days: number | null;
  estimated_stock_after_14_days: number | null;
  risk_level: string;
  confidence: number | null;
  confidence_note: string;
  method: "rule_based_fallback";
  model_version: null;
  model_validated: false;
  data_source: "uploaded";
  is_synthetic: boolean;
  provenance_status: "synthetic" | "uploaded_unverified";
  facility_type: string | null;
  region: string | null;
  reorder_level: number | null;
  stockout_flag_assumption: string | null;
}
