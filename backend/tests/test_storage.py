import hashlib
import io

from botocore.exceptions import ClientError
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import main, storage
from backend.app.config import settings
from backend.app.database import Base, get_db
from backend.app import models
from backend.app.validation import ValidationConfig
from backend.app.storage import (
    ObjectStorageError,
    StorageConfigurationError,
    delete_object,
    read_dashboard_csv,
    read_object,
    write_object,
    write_verified_object,
)


def test_local_object_storage_writes_reads_and_deletes_immutable_objects(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "uploads_path", tmp_path / "uploads")

    write_object("v1/dataset/data.csv", b"dataset")

    assert read_object("v1/dataset/data.csv", max_bytes=20) == b"dataset"
    with pytest.raises(ObjectStorageError, match="already exists"):
        write_object("v1/dataset/data.csv", b"replacement")
    with pytest.raises(ObjectStorageError, match="size limit"):
        read_object("v1/dataset/data.csv", max_bytes=3)

    delete_object("v1/dataset/data.csv")
    assert not (tmp_path / "uploads" / "v1" / "dataset" / "data.csv").exists()


def test_verified_object_storage_accepts_identical_retries_and_rejects_changes(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "uploads_path", tmp_path / "uploads")
    content = b"dataset"

    digest = write_verified_object(
        "v1/dataset/data.csv",
        content,
        max_bytes=20,
    )
    repeated_digest = write_verified_object(
        "v1/dataset/data.csv",
        content,
        max_bytes=20,
    )

    assert digest == hashlib.sha256(content).hexdigest()
    assert repeated_digest == digest
    with pytest.raises(ObjectStorageError, match="different content"):
        write_verified_object(
            "v1/dataset/data.csv",
            b"changed",
            max_bytes=20,
        )


@pytest.mark.parametrize("key", ["../outside.csv", "v1/../../outside.csv"])
def test_local_object_storage_rejects_path_traversal(tmp_path, monkeypatch, key):
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "uploads_path", tmp_path / "uploads")

    with pytest.raises(StorageConfigurationError, match="outside"):
        write_object(key, b"unsafe")


def test_s3_object_storage_writes_reads_and_deletes(monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "object_store_bucket", "dataset-bucket")
    monkeypatch.setattr(
        settings,
        "object_store_endpoint_url",
        "https://account-id.r2.cloudflarestorage.com",
    )
    monkeypatch.setattr(settings, "object_store_region", "auto")
    monkeypatch.setattr(settings, "object_store_access_key_id", "test-access-key")
    monkeypatch.setattr(settings, "object_store_secret_access_key", "test-secret-key")
    objects = {}

    class Client:
        def head_object(self, *, Bucket, Key):
            if (Bucket, Key) not in objects:
                raise ClientError(
                    {"Error": {"Code": "404", "Message": "Missing object"}},
                    "HeadObject",
                )

        def put_object(self, *, Bucket, Key, Body, ContentLength):
            assert ContentLength == len(Body)
            objects[(Bucket, Key)] = Body

        def get_object(self, *, Bucket, Key):
            return {"Body": io.BytesIO(objects[(Bucket, Key)])}

        def delete_object(self, *, Bucket, Key):
            objects.pop((Bucket, Key), None)

    monkeypatch.setattr(storage.boto3, "client", lambda *args, **kwargs: Client())

    write_object("v1/dataset/data.csv", b"dataset")
    assert read_object("v1/dataset/data.csv", max_bytes=20) == b"dataset"
    with pytest.raises(ObjectStorageError, match="already exists"):
        write_object("v1/dataset/data.csv", b"replacement")
    delete_object("v1/dataset/data.csv")
    assert ("dataset-bucket", "v1/dataset/data.csv") not in objects


def test_s3_training_upload_uses_object_storage_and_database_registry(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "object_store_bucket", "dataset-bucket")
    monkeypatch.setattr(
        settings,
        "object_store_endpoint_url",
        "https://account-id.r2.cloudflarestorage.com",
    )
    monkeypatch.setattr(settings, "object_store_region", "auto")
    monkeypatch.setattr(settings, "object_store_access_key_id", "test-access-key")
    monkeypatch.setattr(settings, "object_store_secret_access_key", "test-secret-key")
    monkeypatch.setattr(settings, "uploads_path", tmp_path / "uploads")
    monkeypatch.setattr(settings, "admin_api_key", "test-admin-key")
    monkeypatch.setattr(
        main,
        "_validation_config",
        lambda: ValidationConfig(
            minimum_records_per_facility_item=1,
            minimum_facility_items=1,
        ),
    )
    monkeypatch.setattr(main, "_run_automatic_training", lambda dataset_id: None)
    objects = {}

    class Client:
        def head_object(self, *, Bucket, Key):
            if (Bucket, Key) not in objects:
                raise ClientError(
                    {"Error": {"Code": "404", "Message": "Missing object"}},
                    "HeadObject",
                )

        def put_object(self, *, Bucket, Key, Body, ContentLength):
            assert ContentLength == len(Body)
            objects[(Bucket, Key)] = Body

        def get_object(self, *, Bucket, Key):
            return {"Body": io.BytesIO(objects[(Bucket, Key)])}

        def delete_object(self, *, Bucket, Key):
            objects.pop((Bucket, Key), None)

    monkeypatch.setattr(storage.boto3, "client", lambda *args, **kwargs: Client())
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'registry.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        session = test_session()
        try:
            yield session
        finally:
            session.close()

    main.app.dependency_overrides[get_db] = override_get_db
    content = (
        "facility_id,item_id,date,stock_on_hand,units_consumed,units_received,is_synthetic\n"
        "TEST-FAC-001,TEST-ITEM-001,2026-01-01,10,1,0,true\n"
        "TEST-FAC-001,TEST-ITEM-001,2026-01-02,9,1,0,true\n"
    ).encode()
    headers = {"X-Admin-API-Key": "test-admin-key"}
    try:
        with TestClient(main.app) as client:
            response = client.post(
                "/api/v1/data/training-upload",
                files={"file": ("dataset.csv", content, "text/csv")},
                headers=headers,
            )
            assert response.status_code == 200
            dataset_id = response.json()["dataset_id"]
            assert response.json()["metadata_path"] == f"database://datasets/{dataset_id}"
            detail = client.get(
                f"/api/v1/data/datasets/{dataset_id}",
                headers=headers,
            )
            assert detail.status_code == 200
            assert detail.json()["provenance_status"] == "synthetic"
        with test_session() as session:
            record = session.get(models.DatasetRecord, dataset_id)
            events = session.query(models.DatasetEvent).filter_by(
                dataset_id=dataset_id
            ).all()
            assert record is not None
            assert record.storage_backend == "s3"
            assert record.byte_size == len(content)
            assert {event.event_type for event in events} == {
                "upload",
                "training_queued",
            }
        assert objects[("dataset-bucket", f"v1/{dataset_id}/data.csv")] == content
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        engine.dispose()


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


def test_r2_dashboard_storage_seeds_missing_object_from_local_csv(tmp_path, monkeypatch):
    content = b"facility_name,is_synthetic\nExample,true\n"
    csv_path = tmp_path / "dashboard.csv"
    csv_path.write_bytes(content)
    objects = {}
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
    monkeypatch.setattr(settings, "csv_path", csv_path)

    class Client:
        def get_object(self, *, Bucket, Key):
            assert Bucket == "staging-bucket"
            if (Bucket, Key) not in objects:
                raise ClientError(
                    {"Error": {"Code": "NoSuchKey", "Message": "Missing object"}},
                    "GetObject",
                )
            return {"Body": io.BytesIO(objects[(Bucket, Key)])}

        def head_object(self, *, Bucket, Key):
            if (Bucket, Key) not in objects:
                raise ClientError(
                    {"Error": {"Code": "404", "Message": "Missing object"}},
                    "HeadObject",
                )

        def put_object(self, *, Bucket, Key, Body, ContentLength):
            assert ContentLength == len(Body)
            objects[(Bucket, Key)] = Body

    monkeypatch.setattr(storage.boto3, "client", lambda *args, **kwargs: Client())

    assert read_dashboard_csv() == content
    assert objects[("staging-bucket", "staging/dashboard.csv")] == content


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
    monkeypatch.setattr(settings, "csv_path", settings.csv_path.parent / "missing-dashboard.csv")

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


def test_dashboard_api_surfaces_safe_storage_configuration_error(monkeypatch, caplog):
    detail = "MEDIPREDICT_DASHBOARD_DATA_KEY must identify the dashboard CSV object."

    def fail_read():
        raise StorageConfigurationError(detail)

    monkeypatch.setattr(main, "read_dashboard_csv", fail_read)

    with pytest.raises(main.HTTPException) as error:
        main.load_rows()

    assert error.value.status_code == 503
    assert error.value.detail == detail
    assert detail in caplog.text


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
