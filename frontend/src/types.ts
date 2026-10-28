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
  facility_type: string | null;
  region: string | null;
  reorder_level: number | null;
  stockout_flag_assumption: string | null;
}
