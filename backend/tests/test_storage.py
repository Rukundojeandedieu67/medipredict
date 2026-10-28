import io

from botocore.exceptions import ClientError
import pytest
from fastapi.testclient import TestClient

from backend.app import main, storage
from backend.app.config import settings
from backend.app.storage import (
    ObjectStorageError,
    StorageConfigurationError,
    read_dashboard_csv,
)


def test_local_dashboard_storage_keeps_path_based_behavior(tmp_path, monkeypatch):
    csv_path = tmp_path / "dashboard.csv"
    csv_path.write_bytes(b"facility_name,is_synthetic\nExample,true\n")
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "csv_path", csv_path)

    assert read_dashboard_csv() == b"facility_name,is_synthetic\nExample,true\n"


def test_local_dashboard_storage_returns_none_for_missing_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "csv_path", tmp_path / "missing.csv")

    assert read_dashboard_csv() is None


def test_r2_dashboard_storage_reads_configured_object(monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "object_store_bucket", "staging-bucket")
    monkeypatch.setattr(
        settings,
        "object_store_endpoint_url",
        "https://account-id.r2.cloudflarestorage.com",
    )
    monkeypatch.setattr(settings, "object_store_region", "auto")
    monkeypatch.setattr(settings, "object_store_access_key_id", "test-access-key")
    monkeypatch.setattr(settings, "object_store_secret_access_key", "test-secret-key")
    monkeypatch.setattr(settings, "dashboard_data_key", "staging/dashboard.csv")

    class Client:
        def get_object(self, *, Bucket, Key):
            assert Bucket == "staging-bucket"
            assert Key == "staging/dashboard.csv"
            return {"Body": io.BytesIO(b"facility_name,is_synthetic\nExample,true\n")}

    def create_client(service, **kwargs):
        assert service == "s3"
        assert kwargs["endpoint_url"] == "https://account-id.r2.cloudflarestorage.com"
        assert kwargs["region_name"] == "auto"
        assert kwargs["aws_access_key_id"] == "test-access-key"
        assert kwargs["aws_secret_access_key"] == "test-secret-key"
        return Client()

    monkeypatch.setattr(storage.boto3, "client", create_client)

    assert read_dashboard_csv() == b"facility_name,is_synthetic\nExample,true\n"


def test_s3_storage_requires_all_credentials(monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "object_store_bucket", "staging-bucket")
    monkeypatch.setattr(
        settings,
        "object_store_endpoint_url",
        "https://account-id.r2.cloudflarestorage.com",
    )
    monkeypatch.setattr(settings, "object_store_access_key_id", "test-access-key")
    monkeypatch.setattr(settings, "object_store_secret_access_key", None)
    monkeypatch.setattr(settings, "dashboard_data_key", "staging/dashboard.csv")

    with pytest.raises(StorageConfigurationError, match="SECRET_ACCESS_KEY"):
        read_dashboard_csv()


def test_s3_object_read_failure_is_not_replaced_with_local_data(monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "object_store_bucket", "staging-bucket")
    monkeypatch.setattr(
        settings,
        "object_store_endpoint_url",
        "https://account-id.r2.cloudflarestorage.com",
    )
    monkeypatch.setattr(settings, "object_store_access_key_id", "test-access-key")
    monkeypatch.setattr(settings, "object_store_secret_access_key", "test-secret-key")
    monkeypatch.setattr(settings, "dashboard_data_key", "staging/dashboard.csv")

    class Client:
        def get_object(self, **kwargs):
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "Missing object"}},
                "GetObject",
            )

    monkeypatch.setattr(storage.boto3, "client", lambda *args, **kwargs: Client())

    with pytest.raises(ObjectStorageError, match="could not be read"):
        read_dashboard_csv()


def test_s3_dashboard_csv_enforces_size_limit(monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "object_store_bucket", "staging-bucket")
    monkeypatch.setattr(
        settings,
        "object_store_endpoint_url",
        "https://account-id.r2.cloudflarestorage.com",
    )
    monkeypatch.setattr(settings, "object_store_access_key_id", "test-access-key")
    monkeypatch.setattr(settings, "object_store_secret_access_key", "test-secret-key")
    monkeypatch.setattr(settings, "dashboard_data_key", "staging/dashboard.csv")

    class Body:
        closed = False

        def read(self, _size):
            raise AssertionError("Oversized object should be rejected before reading.")

        def close(self):
            self.closed = True

    body = Body()

    class Client:
        def get_object(self, **kwargs):
            return {"Body": body, "ContentLength": storage.MAX_DASHBOARD_CSV_BYTES + 1}

    monkeypatch.setattr(storage.boto3, "client", lambda *args, **kwargs: Client())

    with pytest.raises(ObjectStorageError, match="20 MiB"):
        read_dashboard_csv()
    assert body.closed is True


def test_dashboard_api_maps_storage_failure_to_service_unavailable(monkeypatch):
    def fail_read():
        raise ObjectStorageError("private storage detail")

    monkeypatch.setattr(main, "read_dashboard_csv", fail_read)

    with pytest.raises(main.HTTPException) as error:
        main.load_rows()

    assert error.value.status_code == 503
    assert error.value.detail == "Dashboard data is not available from configured storage."


def test_dashboard_api_serves_synthetic_r2_dataset_to_ui(monkeypatch):
    content = (
        "reporting_month,facility_name,facility_type,district,province,"
        "nisr_under_5_population,nisr_poverty_rate_pct,nisr_malaria_prevalence_pct,"
        "medicine_code,medicine_name,end_of_month_stock_units,"
        "avg_daily_consumption_units,rainy_season_active,is_synthetic\n"
        "2026-03-01,Example Facility,Health Center,Example District,Example Province,"
        "100,20,5,MED-1,Example Medicine,70,10,0,true\n"
    ).encode()
    monkeypatch.setattr(main, "read_dashboard_csv", lambda: content)

    with TestClient(main.app) as client:
        response = client.get("/api/v1/inventory/summary")

    assert response.status_code == 200
    assert response.json()["facilities"] == 1
    assert response.json()["medicines"] == 1
    assert response.json()["is_synthetic"] is True
    assert response.json()["provenance_status"] == "synthetic"
