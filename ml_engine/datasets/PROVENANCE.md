# Reference data provenance

Retrieval/build date for this Phase 1 refresh: **2026-10-15**. The facility source was already present in the repository and was copied without changing records. District indicators were migrated from values embedded in the repository's dataset generator. District indicator values remain unverified seeds; no statistical claim should treat them as verified. Facility geometry assignment is derived by spatial join.

| Dataset / fields | URL or origin | Retrieval date | License | Field status |
|---|---|---|---|---|
| Rwanda health facilities (`raw/rwanda_healthsites.csv`): `osm_id`, `name`, `amenity`, `healthcare`, `X`, `Y`, and source attributes | https://data.humdata.org/dataset/67ca8390-678a-4eb0-8c06-a12d86df1033/resource/752482cc-e7a0-4898-8653-113d0373fba6/download/rwanda.csv ; repository source `datasets/medipredict_data/raw/rwanda_healthsites.csv` | Source-file date is not recorded; repository copy date 2026-10-15 | ODbL 1.0 per Healthsites dataset listing; attribute OpenStreetMap contributors | Facility tags and coordinates: real as supplied by source, not independently verified; records with unusable/out-of-boundary coordinates are dropped |
| Rwanda ADM2 boundaries (`raw/rwanda_adm2.geojson`) | API metadata: https://www.geoboundaries.org/api/current/gbOpen/RWA/ADM2/ ; downloader follows the `gjDownloadURL` field | 2026-10-15 when fetched; boundary vintage 2012; API metadata and downloaded GeoJSON retrieved 2026-10-15 | Creative Commons Attribution 4.0 International (CC BY 4.0), boundary source Open Data Rwanda | Boundary geometries: real source data; district assignment to facilities: derived |
| `processed/facilities.csv`: `facility_id`, `name`, `type`, coordinates, source | Derived from Rwanda Healthsites source; `district` assigned by point-in-polygon against geoBoundaries ADM2; `province` joined from current seed district table | Build date 2026-10-15 | Inherits source licenses; attribution retained in source field and this document | Names/IDs/tags/coordinates: real as supplied; standardized `type`, district and province: derived; type mapping documented below |
| `nisr/district_indicators.csv`: population, under-five population, women 15–49, poverty, insurance, malaria, facility delivery | Seed values from `datasets/download_and_build_medipredict_data.py` and corresponding processed CSV; no official publication URL/table citation is available in repository | Migrated 2026-10-15; underlying source year field is 2022 | Unknown until the exact publication and its terms are verified | All numeric indicators: unverified-seed; `verified=false`; do not present as official/verified statistics |
| Facility type normalization | Implemented in `pipeline/build_reference_data.py` from Healthsites `amenity` and `healthcare` tags | Mapping recorded 2026-10-15 | Derived mapping; inherits source dataset terms | Derived: pharmacy/drugstore → Pharmacy; hospital → Hospital; clinic/hospice/nursing home → Health Center (except explicit hospital); health post/healthpost → Health Post; dispensary → Dispensary; doctor/health centre/health center/centre → Health Center; all remaining or absent tags → Other. When tags conflict, pharmacy takes precedence, then hospital, then health-center class, then health-post/dispensary class. |
| Existing generated operational and climate datasets under `datasets/medipredict_data/processed/` | Repository generator scripts; no provenance manifest, stable source URLs, or row-level synthetic marker | Existing generated files; precise retrieval dates are not recorded | Mixed/unknown | Operational stock, consumption and risk fields: synthetic; hardcoded demographic fields: unverified-seed; climate feed/fallback fields: mixed real/derived/synthetic and not distinguishable per row in existing files |

The current geoBoundaries API response for this run reported boundaryYearRepresented=2012, boundarySource=Open Data Rwanda, and CC BY 4.0. The API response is mutable, so later refreshes may return different metadata. Source licenses and publication references for the seeded district indicator values remain unresolved; all values are explicitly marked unverified.


## Field-level status

| Table | Field(s) | Status |
|---|---|---|
| `raw/rwanda_healthsites.csv` | `osm_id`, `uuid` | Real source identifiers; not independently verified |
| `raw/rwanda_healthsites.csv` | `name`, `amenity`, `healthcare`, `operator`, `speciality`, `operator_type`, `operational_status`, `opening_hours`, `beds`, `staff_doctors`, `staff_nurses`, `health_amenity_type`, `dispensing`, `wheelchair`, `emergency`, `insurance`, `water_source`, `electricity`, `is_in_health_area`, `is_in_health_zone`, `addr_housenumber`, `addr_street`, `addr_postcode`, `addr_city` | Real as supplied by source; nulls mean not supplied |
| `raw/rwanda_healthsites.csv` | `X`, `Y` | Real source coordinates; treated as longitude/latitude and filtered against Rwanda ADM2 polygons |
| `raw/rwanda_healthsites.csv` | `osm_type`, `completeness`, `source`, `changeset_id`, `changeset_version`, `changeset_timestamp`, `url` | Real source metadata; source values may be absent |
| `raw/rwanda_adm2.geojson` | Feature properties and geometry | Real; geoBoundaries source vintage 2012 |
| `processed/facilities.csv` | `facility_id` | Real source ID (`osm_id`, then `uuid`); generated row fallback only if both are absent |
| `processed/facilities.csv` | `name` | Real source name; missing names remain blank |
| `processed/facilities.csv` | `type` | Derived using the documented tag mapping |
| `processed/facilities.csv` | `district` | Derived point-in-polygon join; ambiguous/outside points are dropped |
| `processed/facilities.csv` | `province` | Derived lookup from the unverified district seed table |
| `processed/facilities.csv` | `latitude`, `longitude` | Real source coordinates, axis names derived from source X=longitude and Y=latitude |
| `processed/facilities.csv` | `source` | Derived attribution string, retaining the source field when present |
| `nisr/district_indicators.csv` | `district`, `province` | Unverified-seed identifiers/administrative labels copied from repository values |
| `nisr/district_indicators.csv` | `population`, `under5_population`, `women_15_49`, `poverty_rate_pct`, `health_insurance_pct`, `malaria_prevalence_pct`, `facility_delivery_pct` | Unverified-seed values; no official source table or URL available |
| `nisr/district_indicators.csv` | `source_name`, `source_year` | Unverified-seed metadata copied/assigned from repository context; source name is `unverified repository seed`, year is 2022 |
| `nisr/district_indicators.csv` | `verified` | Derived validation flag, always false |
| `nisr/district_indicators.csv` | `notes` | Derived warning text, not a statistical observation |

## Existing generated source tables

These repository data files are also upstream inputs or outputs covered by this reference refresh:

| Dataset | URL or origin | Retrieval/build date | License | Field status |
|---|---|---|---|---|
| `datasets/medipredict_data/processed/nisr_census_2022_districts.csv` | Embedded seed table in `datasets/download_and_build_medipredict_data.py`; no official publication URL is recorded | Existing file date not verified | Unknown | `province`, `district`, `population_2022`, `under_5_pop`, `women_15_49`, `poverty_rate_pct`, `mutuelle_pct`, `malaria_prev_pct`, `delivery_facility_pct`: unverified-seed |
| `datasets/medipredict_data/processed/medipredict_master_rwanda_dataset.csv` | Built by `datasets/download_and_build_medipredict_data.py`; source inputs include unverified district seed table | Existing file date not verified | Unknown/mixed | Administrative and demographic columns: unverified-seed; `current_stock_units`, `avg_daily_consumption_units`, `estimated_lead_time_days`, `pending_depot_orders_units`: synthetic; `predicted_risk_level`: derived from synthetic operational values; `data_source_verification`: unsupported source assertion, not a verified flag |
| `datasets/medipredict_data/processed/medipredict_facility_timeseries_2026.csv` | Built by `datasets/build_facility_timeseries.py` from source facilities, district seed values, and generated trajectories | Existing file date not verified | Mixed/inherited/unknown | Facility names/tags/coordinates: real source; facility district after Phase 1: derived from point-in-polygon; district demographics: unverified-seed; stocks, consumption, and seasonality trajectories: synthetic; `lead_time_days_remaining` and `stockout_risk_label`: derived from synthetic values |
| `datasets/medipredict_data/processed/district_climate_rainfall.csv` | Open-Meteo API URL template in generator: https://api.open-meteo.com/v1/forecast (latitude, longitude, daily precipitation and temperature parameters) | Retrieval date not stored with existing CSV | Open-Meteo terms apply; verify for reuse | District names: derived; `weekly_avg_rainfall_mm`: real API response for successful requests, otherwise synthetic fallback value 4.5; existing CSV does not identify which rows used fallback |
| `datasets/medipredict_data/raw/rwanda_healthsites.csv` | HDX download URL shown above | Source file retrieval date not recorded | ODbL 1.0; attribute OpenStreetMap contributors | Source fields described in field-level table above |

For each listed field, `real` means carried from a source without independent verification; `derived` means calculated or joined from other columns/geometries; `synthetic` means generated by simulation or fallback; `unverified-seed` means hardcoded repository values with no verified publication reference. Existing generated datasets have no row-level `is_synthetic` marker, so their synthetic columns must not be presented as verified operational data.

