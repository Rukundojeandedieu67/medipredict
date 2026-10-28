import hashlib
import io
import json
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from backend.app.provenance import (
    ProvenanceError,
    resolve_provenance,
    revoke_verification,
    verify_dataset,
)
from backend.app import main, storage
from backend.app import models
from backend.app.database import Base, get_db
from backend.app.validation import ValidationConfig
from backend.app.storage import read_object
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker


TEST_DATASET_ID = "v1-20260101T000000Z-" + "a" * 32
TEST_SOURCE_ID = "TEST-SOURCE-001"


@pytest.fixture
def dataset(tmp_path):
    uploads = tmp_path / "uploads"
    directory = uploads / "v1" / TEST_DATASET_ID
    directory.mkdir(parents=True)
    content = (
        "facility_id,item_id,date,stock_on_hand,units_consumed,units_received,is_synthetic\n"
        "TEST-FAC-001,TEST-ITEM-001,0001-01-01,10,1,0,false\n"
        "TEST-FAC-001,TEST-ITEM-001,0001-01-02,9,1,0,false\n"
    ).encode()
    (directory / "data.csv").write_bytes(content)
    (directory / "metadata.json").write_text(
        json.dumps(
            {
                "dataset_id": TEST_DATASET_ID,
                "sha256": hashlib.sha256(content).hexdigest(),
                "is_synthetic": False,
                "uploader": "TEST-UPLOADER-001",
            }
        ),
        encoding="utf-8",
    )
    sources = tmp_path / "approved_sources.json"
    sources.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_id": TEST_SOURCE_ID,
                        "name": "TEST SOURCE",
                        "organization": "TEST ORGANIZATION",
                        "system": "TEST SYSTEM",
                        "contact": "",
                        "accepted_verification_methods": ["direct_export_from_system"],
                        "notes": "",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return uploads, directory, sources, content


def _verify(dataset, **overrides):
    uploads, _, sources, _ = dataset
    values = {
        "source_id": TEST_SOURCE_ID,
        "verification_method": "direct_export_from_system",
        "verification_reference": "TEST-REF-001",
        "reporting_period_start": "0001-01-01",
        "reporting_period_end": "0001-01-02",
        "verified_by": "TEST-VERIFIER-001",
        "approved_sources_path": sources,
    }
    values.update(overrides)
    return verify_dataset(TEST_DATASET_ID, uploads, **values)


def test_new_non_synthetic_upload_defaults_to_unverified(dataset):
    uploads, _, sources, _ = dataset

    result = resolve_provenance(
        TEST_DATASET_ID, uploads, approved_sources_path=sources
    )

    assert result["provenance_status"] == "uploaded_unverified"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"source_id": "TEST-SOURCE-UNKNOWN"}, "Unknown approved source_id"),
        ({"verification_reference": "  "}, "must not be empty"),
        ({"reporting_period_start": "0001-01-02"}, "must cover"),
        ({"verified_by": "TEST-UPLOADER-001"}, "different person"),
    ],
)
def test_verification_rejects_invalid_claims(dataset, overrides, message):
    with pytest.raises(ProvenanceError, match=message):
        _verify(dataset, **overrides)


def test_verification_rejects_hash_mismatch(dataset):
    uploads, directory, sources, _ = dataset
    (directory / "data.csv").write_bytes(b"modified")

    with pytest.raises(ProvenanceError, match="hash does not match"):
        verify_dataset(
            TEST_DATASET_ID,
            uploads,
            source_id=TEST_SOURCE_ID,
            verification_method="direct_export_from_system",
            verification_reference="TEST-REF-001",
            reporting_period_start="0001-01-01",
            reporting_period_end="0001-01-02",
            verified_by="TEST-VERIFIER-001",
            approved_sources_path=sources,
        )


def test_synthetic_dataset_cannot_be_verified(dataset):
    uploads, directory, sources, _ = dataset
    content = (
        "facility_id,item_id,date,stock_on_hand,units_consumed,units_received,is_synthetic\n"
        "TEST-FAC-001,TEST-ITEM-001,0001-01-01,10,1,0,true\n"
        "TEST-FAC-001,TEST-ITEM-001,0001-01-02,9,1,0,true\n"
    ).encode()
    (directory / "data.csv").write_bytes(content)
    metadata_path = directory / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["sha256"] = hashlib.sha256(content).hexdigest()
    metadata["is_synthetic"] = True
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ProvenanceError, match="Synthetic datasets cannot be verified"):
        _verify(dataset)


def test_verification_returns_record_and_marks_unknown_identity_single_party(dataset):
    result = _verify(dataset, verified_by=None)

    assert result["provenance_status"] == "verified"
    assert result["verification"]["source"]["source_id"] == TEST_SOURCE_ID
    assert result["verification"]["dataset_sha256"]
    assert result["verification_summary"]["single_party"] is True


def test_tampering_drops_status_to_unverified_and_logs_warning(dataset, caplog):
    _verify(dataset)
    _, directory, sources, _ = dataset
    with (directory / "data.csv").open("ab") as destination:
        destination.write(b"#changed\n")

    with caplog.at_level("WARNING"):
        result = resolve_provenance(
            TEST_DATASET_ID, dataset[0], approved_sources_path=sources
        )

    assert result["provenance_status"] == "uploaded_unverified"
    assert "hash no longer matches" in caplog.text


def test_revocation_appends_history_and_drops_status(dataset):
    verified = _verify(dataset)
    history_path = dataset[1] / "verification.json"
    first_line = history_path.read_text(encoding="utf-8").splitlines()[0]

    result = revoke_verification(
        TEST_DATASET_ID,
        dataset[0],
        reason="TEST-REVOCATION-001",
        revoked_by="TEST-ADMIN-001",
        approved_sources_path=dataset[2],
    )

    history = history_path.read_text(encoding="utf-8").splitlines()
    assert verified["provenance_status"] == "verified"
    assert result["provenance_status"] == "uploaded_unverified"
    assert history[0] == first_line
    assert len(history) == 2
    assert json.loads(history[1])["event"] == "revocation"


def test_same_known_verifier_and_uploader_is_rejected(dataset):
    with pytest.raises(ProvenanceError, match="different person"):
        _verify(dataset, verified_by="TEST-UPLOADER-001")


@pytest.mark.parametrize("storage_backend", ["local", "s3"])
def test_admin_only_api_verify_revoke_detail_and_list(
    tmp_path, monkeypatch, storage_backend
):
    monkeypatch.setattr(main.settings, "storage_backend", storage_backend)
    uploads = tmp_path / "uploads"
    monkeypatch.setattr(main.settings, "uploads_path", uploads)
    monkeypatch.setattr(main.settings, "admin_api_key", "test-admin-key")
    monkeypatch.setattr(
        main,
        "_validation_config",
        lambda: ValidationConfig(
            minimum_records_per_facility_item=1,
            minimum_facility_items=1,
        ),
    )
    sources = tmp_path / "approved_sources.json"
    sources.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_id": TEST_SOURCE_ID,
                        "name": "TEST SOURCE",
                        "organization": "TEST ORGANIZATION",
                        "system": "TEST SYSTEM",
                        "contact": "",
                        "accepted_verification_methods": ["direct_export_from_system"],
                        "notes": "",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    from backend.app import provenance

    monkeypatch.setattr(provenance, "ROOT", tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "approved_sources.json").write_text(
        sources.read_text(encoding="utf-8"), encoding="utf-8"
    )
    objects = {}
    if storage_backend == "s3":
        monkeypatch.setattr(main.settings, "object_store_bucket", "dataset-bucket")
        monkeypatch.setattr(
            main.settings,
            "object_store_endpoint_url",
            "https://account-id.r2.cloudflarestorage.com",
        )
        monkeypatch.setattr(main.settings, "object_store_region", "auto")
        monkeypatch.setattr(main.settings, "object_store_access_key_id", "test-access-key")
        monkeypatch.setattr(
            main.settings, "object_store_secret_access_key", "test-secret-key"
        )

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
    content = (
        "facility_id,item_id,date,stock_on_hand,units_consumed,units_received,is_synthetic\n"
        "TEST-FAC-001,TEST-ITEM-001,0001-01-01,10,1,0,false\n"
        "TEST-FAC-001,TEST-ITEM-001,0001-01-02,9,1,0,false\n"
    ).encode()

    test_engine = create_engine(
        f"sqlite:///{(tmp_path / 'registry.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(test_engine)
    test_session = sessionmaker(bind=test_engine, expire_on_commit=False)

    def override_get_db():
        session = test_session()
        try:
            yield session
        finally:
            session.close()

    main.app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(main.app) as client:
            uploaded = client.post(
                "/api/v1/data/training-upload",
                files={"file": ("dataset.csv", content, "text/csv")},
                headers={"X-Admin-API-Key": "test-admin-key", "X-Uploader": "TEST-UPLOADER-001"},
            )
            assert uploaded.status_code == 200
            dataset_id = uploaded.json()["dataset_id"]
            assert uploaded.json()["provenance_status"] == "uploaded_unverified"

            forbidden = client.post(
                f"/api/v1/data/datasets/{dataset_id}/verify",
                data={
                    "source_id": TEST_SOURCE_ID,
                    "verification_method": "direct_export_from_system",
                    "verification_reference": "TEST-REF-001",
                    "reporting_period_start": "0001-01-01",
                    "reporting_period_end": "0001-01-02",
                },
            )
            assert forbidden.status_code == 403

            headers = {
                "X-Admin-API-Key": "test-admin-key",
                "X-Admin-Identity": "TEST-VERIFIER-001",
            }
            same_person = client.post(
                f"/api/v1/data/datasets/{dataset_id}/verify",
                data={
                    "source_id": TEST_SOURCE_ID,
                    "verification_method": "direct_export_from_system",
                    "verification_reference": "TEST-REF-SAME-PERSON",
                    "reporting_period_start": "0001-01-01",
                    "reporting_period_end": "0001-01-02",
                },
                headers={**headers, "X-Admin-Identity": "TEST-UPLOADER-001"},
            )
            assert same_person.status_code == 422
            assert "different person" in same_person.text

            verified = client.post(
                f"/api/v1/data/datasets/{dataset_id}/verify",
                data={
                    "source_id": TEST_SOURCE_ID,
                    "verification_method": "direct_export_from_system",
                    "verification_reference": "TEST-REF-001",
                    "reporting_period_start": "0001-01-01",
                    "reporting_period_end": "0001-01-02",
                },
                headers=headers,
                files={
                    "evidence_file": (
                        "evidence.txt",
                        b"TEST-EVIDENCE",
                        "text/plain",
                    )
                },
            )
            assert verified.status_code == 200
            assert verified.json()["provenance_status"] == "verified"
            assert verified.json()["verification"]["source"]["name"] == "TEST SOURCE"
            assert verified.json()["verification_summary"]["single_party"] is False

            detail = client.get(
                f"/api/v1/data/datasets/{dataset_id}", headers=headers
            )
            listing = client.get("/api/v1/data/datasets", headers=headers)
            provenance = client.get(
                f"/api/v1/data/datasets/{dataset_id}/provenance", headers=headers
            )
            assert detail.json()["provenance_status"] == "verified"
            assert listing.json()[0]["provenance_status"] == "verified"
            assert provenance.json()["provenance_status"] == "verified"

            revoked = client.post(
                f"/api/v1/data/datasets/{dataset_id}/revoke-verification",
                data={"reason": "TEST-REVOCATION-001"},
                headers=headers,
            )
            assert revoked.status_code == 200
            assert revoked.json()["provenance_status"] == "uploaded_unverified"

        with test_session() as session:
            stored_dataset = session.get(models.DatasetRecord, dataset_id)
            events = session.scalars(
                select(models.DatasetEvent)
                .where(models.DatasetEvent.dataset_id == dataset_id)
                .order_by(models.DatasetEvent.occurred_at, models.DatasetEvent.event_id)
            ).all()
            assert stored_dataset is not None
            assert stored_dataset.sha256 == hashlib.sha256(content).hexdigest()
            assert [event.event_type for event in events] == [
                "upload",
                "verification",
                "revocation",
            ]
            evidence_details = events[1].details
            assert evidence_details["evidence_file_sha256"] == hashlib.sha256(
                b"TEST-EVIDENCE"
            ).hexdigest()
            assert read_object(
                evidence_details["evidence_object_key"],
                max_bytes=1024,
                backend=evidence_details["evidence_storage_backend"],
            ) == b"TEST-EVIDENCE"
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        test_engine.dispose()


def test_verification_stores_and_hashes_supporting_evidence(dataset):
    result = verify_dataset(
        TEST_DATASET_ID,
        dataset[0],
        source_id=TEST_SOURCE_ID,
        verification_method="direct_export_from_system",
        verification_reference="TEST-REF-EVIDENCE-001",
        reporting_period_start="0001-01-01",
        reporting_period_end="0001-01-02",
        verified_by="TEST-VERIFIER-001",
        evidence_file=b"TEST EVIDENCE",
        approved_sources_path=dataset[2],
    )
    expected_hash = hashlib.sha256(b"TEST EVIDENCE").hexdigest()

    assert result["verification"]["evidence_file_sha256"] == expected_hash
    assert (dataset[1] / "evidence" / expected_hash).read_bytes() == b"TEST EVIDENCE"
