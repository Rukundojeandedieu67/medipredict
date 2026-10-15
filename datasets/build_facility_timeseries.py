#!/usr/bin/env python3
"""
MediPredict Rwanda — Advanced Facility-Level Time-Series Engine
--------------------------------------------------------------
Author: Rukundo Jean De Dieu & Team

Transforms district data into 500+ mapped health facilities with 
10-month time-series logs (Jan 2026 - Oct 2026) for ML model training.
"""

import os
import pandas as pd
import numpy as np
from datetime import datetime

DATA_DIR = "medipredict_data"
raw_healthsites_path = f"{DATA_DIR}/raw/rwanda_healthsites.csv"
nisr_districts_path = f"{DATA_DIR}/processed/nisr_census_2022_districts.csv"

print("==========================================================================")
print("🚀 MEDIPREDICT: BUILDING FACILITY-LEVEL TIME-SERIES DATASET (2026)")
print("==========================================================================")

# Load facilities whose district was assigned by the Phase 1 point-in-polygon join.
facilities_path = "../ml_engine/datasets/processed/facilities.csv"
if not os.path.exists(facilities_path):
    raise FileNotFoundError("Spatially joined facility reference table missing; run python ml_engine/pipeline/build_reference_data.py first")
df_facilities = pd.read_csv(facilities_path).rename(columns={"name": "facility_name", "type": "facility_type"})
# Merge with NISR Census Baselines
df_merged_facs = pd.merge(df_facilities, df_nisr, on="district", how="left")

# 3. Generate 10-Month Historical Time Series (Jan 2026 to Oct 2026)
months_2026 = [
    "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", 
    "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"
]

essential_medicines = [
    {"code": "AL-20120", "name": "Artemether/Lumefantrine 20/120mg Tabs"},
    {"code": "AMX-250", "name": "Amoxicillin 250mg Dispersible Tabs"},
    {"code": "OXY-10", "name": "Oxytocin Injection 10IU/ml Ampoule"},
    {"code": "ORS-100", "name": "Oral Rehydration Salts + Zinc"}
]

time_series_records = []
np.random.seed(42)

print("⏳ Generating time-series monthly inventory trajectories...")

for idx, f_row in df_merged_facs.iterrows():
    fac_name = f_row['facility_name']
    district = f_row['district']
    under5_pop = f_row['under_5_pop']
    poverty_rate = f_row['poverty_rate_pct']
    malaria_rate = f_row['malaria_prev_pct']
    
    for med in essential_medicines:
        base_stock = np.random.randint(500, 3000)
        
        for m_idx, month in enumerate(months_2026):
            # Rainy season surge multiplier (April-May & Sept-Oct in Rwanda)
            seasonal_multiplier = 1.35 if month in ["2026-04", "2026-05", "2026-09", "2026-10"] else 1.0
            
            monthly_consumption = int((under5_pop * 0.02) * seasonal_multiplier * np.random.uniform(0.8, 1.2))
            daily_cons = max(1, int(monthly_consumption / 30))
            
            # Stock fluctuation logic over time
            stock_end_month = max(50, base_stock - monthly_consumption + np.random.choice([0, 1000, 2000]))
            base_stock = stock_end_month # Carry over to next month
            
            lead_time_days = round(stock_end_month / daily_cons, 1)
            
            if lead_time_days < 7:
                risk = "CRITICAL"
            elif lead_time_days <= 14:
                risk = "MODERATE"
            else:
                risk = "STABLE"
                
            time_series_records.append({
                "reporting_month": month,
                "facility_name": fac_name,
                "facility_type": f_row['facility_type'],
                "district": district,
                "province": f_row['province'],
                "nisr_district_population": f_row['population_2022'],
                "nisr_under_5_population": under5_pop,
                "nisr_poverty_rate_pct": poverty_rate,
                "nisr_malaria_prevalence_pct": malaria_rate,
                "medicine_code": med['code'],
                "medicine_name": med['name'],
                "end_of_month_stock_units": stock_end_month,
                "avg_daily_consumption_units": daily_cons,
                "lead_time_days_remaining": lead_time_days,
                "stockout_risk_label": risk,
                "rainy_season_active": 1 if seasonal_multiplier > 1.0 else 0
            })

df_ts = pd.DataFrame(time_series_records)
ts_csv_path = f"{DATA_DIR}/processed/medipredict_facility_timeseries_2026.csv"
df_ts.to_csv(ts_csv_path, index=False)

print(f"✅ Successfully created Facility Time-Series Dataset!")
print(f"📁 File saved: {ts_csv_path}")
print(f"📊 Total Records: {len(df_ts):,} monthly observations across facilities in Rwanda.")


