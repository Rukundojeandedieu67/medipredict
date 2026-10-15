export interface Summary {
  facilities: number;
  districts: number;
  medicines: number;
  critical: number;
  moderate: number;
  stable: number;
  stock_units: number;
  reporting_date: string;
}

export interface RiskRecord {
  facility: string;
  district: string;
  province: string;
  medicine_code: string;
  medicine: string;
  stock_units: number;
  daily_consumption: number;
  lead_time_days: number;
  risk_level: string;
  confidence: number;
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
}

export interface FeatureImportance {
  feature: string;
  importance: number;
}

export interface TrustMetrics {
  accuracy: number;
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
  items: RiskRecord[];
}
