from pathlib import Path

import pytest
from shapely.geometry import Point, shape

from ml_engine.pipeline.build_reference_data import BOUNDARY_FILE, assign_district, load_district_geometries
from ml_engine.pipeline.data_loader import load_district_indicators, load_facilities



def test_reference_tables_have_facilities_and_30_unverified_districts():
    facilities = load_facilities()
    districts = load_district_indicators()
    assert not facilities.empty
    assert len(districts) == 30
    assert districts["district"].nunique() == 30
    assert not districts["verified"].astype(str).str.casefold().isin(["true", "1"]).any()


def test_kigali_coordinates_map_to_expected_districts():
    geometries = load_district_geometries(BOUNDARY_FILE)
    known_points = {
        "Gasabo": (30.13, -1.88),
        "Nyarugenge": (30.05, -1.95),
        "Kicukiro": (30.10, -1.98),
    }
    district_keys = {name.casefold(): name for name in geometries}
    for expected, coordinates in known_points.items():
        assert Point(*coordinates).within(geometries[expected.casefold()]) or geometries[expected.casefold()].covers(Point(*coordinates))
        assert assign_district(*coordinates, geometries) == expected.casefold()


def test_loader_rejects_out_of_range_percentages(tmp_path):
    path = tmp_path / "districts.csv"
    table = load_district_indicators().copy()
    table.loc[0, "poverty_rate_pct"] = 101
    table.to_csv(path, index=False)
    with pytest.raises(ValueError, match="between 0 and 100"):
        load_district_indicators(path)

