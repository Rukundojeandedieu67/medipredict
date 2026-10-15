"""Build traceable facility and district reference tables from source files."""
from __future__ import annotations

import json
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
from shapely.geometry import Point, shape

ROOT = Path(__file__).resolve().parents[2]
DATASETS = ROOT / "ml_engine" / "datasets"
RAW = DATASETS / "raw"
FACILITY_SOURCE = RAW / "rwanda_healthsites.csv"
BOUNDARY_FILE = RAW / "rwanda_adm2.geojson"
DISTRICT_SOURCE = ROOT / "datasets" / "medipredict_data" / "processed" / "nisr_census_2022_districts.csv"
FACILITIES_OUT = DATASETS / "processed" / "facilities.csv"
INDICATORS_OUT = DATASETS / "nisr" / "district_indicators.csv"
BOUNDARY_API = "https://www.geoboundaries.org/api/current/gbOpen/RWA/ADM2/"


def ensure_boundaries(path: Path = BOUNDARY_FILE) -> Path:
    """Download current Rwanda ADM2 GeoJSON via metadata gjDownloadURL if absent/empty."""
    if path.exists() and path.stat().st_size > 0:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing.get("features"):
                return path
        except (json.JSONDecodeError, OSError):
            pass
    request = urllib.request.Request(BOUNDARY_API, headers={"User-Agent": "MediPredict reference-data pipeline"})
    with urllib.request.urlopen(request, timeout=30) as response:
        metadata = json.load(response)
    download_url = metadata.get("gjDownloadURL")
    if not download_url:
        raise RuntimeError("geoBoundaries API response has no gjDownloadURL")
    request = urllib.request.Request(download_url, headers={"User-Agent": "MediPredict reference-data pipeline"})
    with urllib.request.urlopen(request, timeout=60) as response:
        geojson = json.load(response)
    if not geojson.get("features"):
        raise RuntimeError("Downloaded geoBoundaries GeoJSON has no features")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(geojson), encoding="utf-8")
    return path


def _district_name(properties: dict[str, Any]) -> str:
    for key in ("shapeName", "NAME_2", "name", "district", "shapeGroup"):
        value = properties.get(key)
        if value:
            return str(value).strip()
    raise ValueError(f"District boundary has no recognized name: {properties}")


def load_district_geometries(path: Path = BOUNDARY_FILE) -> dict[str, Any]:
    geojson = json.loads(path.read_text(encoding="utf-8"))
    geometries = {}
    for feature in geojson.get("features", []):
        name = _district_name(feature.get("properties", {}))
        geometries[name.casefold()] = shape(feature["geometry"])
    if len(geometries) != 30:
        raise ValueError(f"Expected 30 district geometries; found {len(geometries)}")
    return geometries


def standardize_facility_type(amenity: Any, healthcare: Any) -> str:
    """Normalize Healthsites tags; precedence: healthcare tag, then amenity tag."""
    values = {str(value).strip().casefold().replace("_", " ") for value in (healthcare, amenity) if pd.notna(value) and str(value).strip()}
    if "pharmacy" in values or "drugstore" in values:
        return "Pharmacy"
    if values & {"hospital", "clinic", "hospice", "nursing home"}:
        return "Hospital" if "hospital" in values else "Health Center"
    if values & {"health post", "healthpost", "dispensary"}:
        return "Health Post" if values & {"health post", "healthpost"} else "Dispensary"
    if values & {"doctors", "doctor", "health centre", "health center", "centre", "clinic"}:
        return "Health Center"
    if values & {"pharmacy", "chemist"}:
        return "Pharmacy"
    return "Other"


def _province_by_district(path: Path = DISTRICT_SOURCE) -> dict[str, str]:
    data = pd.read_csv(path)
    return {str(row.district).strip().casefold(): str(row.province).strip() for row in data.itertuples()}


def assign_district(longitude: float, latitude: float, geometries: dict[str, Any]) -> str | None:
    point = Point(longitude, latitude)
    matches = [district for district, polygon in geometries.items() if polygon.covers(point)]
    return matches[0] if len(matches) == 1 else None


def build_facilities() -> tuple[int, int, dict[str, int]]:
    boundary_path = ensure_boundaries()
    geometries = load_district_geometries(boundary_path)
    district_display = {name.casefold(): name for name in (_district_name(feature.get("properties", {})) for feature in json.loads(boundary_path.read_text(encoding="utf-8")).get("features", []))}
    provinces = _province_by_district()
    data = pd.read_csv(FACILITY_SOURCE)
    records = []
    dropped = 0
    counts: Counter[str] = Counter()
    for row_number, row in data.iterrows():
        try:
            longitude, latitude = float(row["X"]), float(row["Y"])
            if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
                raise ValueError("coordinate out of range")
        except (KeyError, TypeError, ValueError):
            dropped += 1
            continue
        district_key = assign_district(longitude, latitude, geometries)
        if district_key is None:
            dropped += 1
            continue
        district = district_display[district_key]
        counts[district] += 1
        identifier = row.get("osm_id")
        if pd.isna(identifier) or not str(identifier).strip():
            identifier = row.get("uuid")
        if pd.isna(identifier) or not str(identifier).strip():
            identifier = f"row-{row_number + 1}"
        source_detail = row.get("source")
        source_detail = str(source_detail).strip() if pd.notna(source_detail) and str(source_detail).strip() else "unspecified in source record"
        records.append({
            "facility_id": str(identifier), "name": str(row.get("name", "")).strip(),
            "type": standardize_facility_type(row.get("amenity"), row.get("healthcare")),
            "district": district, "province": provinces.get(district_key, ""),
            "latitude": latitude, "longitude": longitude,
            "source": f"Healthsites/HDX; feature source: {source_detail}",
        })
    FACILITIES_OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(records, columns=["facility_id", "name", "type", "district", "province", "latitude", "longitude", "source"]).to_csv(FACILITIES_OUT, index=False)
    print(f"Dropped facilities with invalid or unmatched coordinates: {dropped}")
    for district in sorted(district_display.values()):
        print(f"{district}: {counts[district]}")
    return len(records), dropped, dict(counts)


def build_district_indicators() -> None:
    source = pd.read_csv(DISTRICT_SOURCE)
    if len(source) != 30:
        raise ValueError(f"Expected 30 district seed rows, found {len(source)}")
    output = pd.DataFrame({
        "district": source["district"], "province": source["province"],
        "population": source["population_2022"], "under5_population": source["under_5_pop"],
        "women_15_49": source["women_15_49"], "poverty_rate_pct": source["poverty_rate_pct"],
        "health_insurance_pct": source["mutuelle_pct"], "malaria_prevalence_pct": source["malaria_prev_pct"],
        "facility_delivery_pct": source["delivery_facility_pct"],
    })
    output["source_name"] = "unverified repository seed"
    output["source_year"] = 2022
    output["verified"] = False
    output["notes"] = "seed value, needs verification against the official publication"
    INDICATORS_OUT.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(INDICATORS_OUT, index=False)


def main() -> None:
    build_district_indicators()
    build_facilities()


if __name__ == "__main__":
    main()


