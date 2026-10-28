from __future__ import annotations

import csv
from datetime import date, datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Any, Literal
import uuid

from .config import ROOT

logger = logging.getLogger(__name__)

DATASET_ID_PATTERN = re.compile(r"^v1-\d{8}T\d{6}Z-[0-9a-f]{32}$")
VERIFICATION_METHODS = frozenset(
    {
        "direct_export_from_system",
        "signed_transmittal_letter",
        "data_sharing_agreement_reference",
        "checksum_confirmed_by_data_owner",
        "other_documented",
    }
)
ProvenanceStatus = Literal["synthetic", "uploaded_unverified", "verified"]


class ProvenanceError(ValueError):
    """A validation error while verifying or resolving a stored dataset."""


def _dataset_directory(dataset_id: str, uploads_root: Path) -> Path:
    if not DATASET_ID_PATTERN.fullmatch(dataset_id):
        raise ProvenanceError("Invalid training-upload dataset ID.")
    directory = uploads_root / "v1" / dataset_id
    if not (directory / "metadata.json").is_file() or not (directory / "data.csv").is_file():
        raise FileNotFoundError(f"Dataset '{dataset_id}' is missing data or metadata.")
    return directory


def _read_metadata(dataset_dir: Path, dataset_id: str) -> dict[str, Any]:
    try:
        metadata = json.loads((dataset_dir / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProvenanceError("Dataset metadata could not be read.") from exc
    if not isinstance(metadata, dict) or metadata.get("dataset_id") != dataset_id:
        raise ProvenanceError("Dataset registry ID does not match its metadata.")
    return metadata


def _sha256(data_path: Path) -> str:
    digest = hashlib.sha256()
    with data_path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_history(history_path: Path) -> list[dict[str, Any]]:
    if not history_path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        with history_path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError(f"Record on line {line_number} is not an object.")
                records.append(record)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ProvenanceError("Dataset verification history is invalid.") from exc
    return records


def _approved_sources(path: Path | None = None) -> dict[str, dict[str, Any]]:
    registry_path = path or ROOT / "config" / "approved_sources.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProvenanceError("Approved sources registry could not be read.") from exc
    sources = registry.get("sources") if isinstance(registry, dict) else None
    if not isinstance(sources, list):
        raise ProvenanceError("Approved sources registry must contain a sources list.")
    result: dict[str, dict[str, Any]] = {}
    for source in sources:
        if not isinstance(source, dict):
            raise ProvenanceError("Approved source entries must be objects.")
        required_fields = (
            "source_id",
            "name",
            "organization",
            "system",
            "contact",
            "accepted_verification_methods",
            "notes",
        )
        if any(field not in source for field in required_fields):
            raise ProvenanceError("Approved source entry is missing required fields.")
        if not all(
            isinstance(source[field], str)
            for field in ("source_id", "name", "organization", "system", "contact", "notes")
        ):
            raise ProvenanceError("Approved source text fields must be strings.")
        methods = source["accepted_verification_methods"]
        if not isinstance(methods, list) or not all(
            isinstance(method, str) and method in VERIFICATION_METHODS
            for method in methods
        ):
            raise ProvenanceError("Approved source verification methods are invalid.")
        source_id = source["source_id"].strip()
        if not source_id or source_id in result:
            raise ProvenanceError("Approved source IDs must be non-empty and unique.")
        result[source_id] = source
    return result


def _dataset_date_range(data_path: Path) -> tuple[date, date]:
    try:
        with data_path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if not reader.fieldnames or "date" not in reader.fieldnames:
                raise ProvenanceError("Stored dataset has no date column.")
            dates = []
            for row in reader:
                date_text = (row.get("date") or "").strip()
                parsed = date.fromisoformat(date_text)
                if parsed.isoformat() != date_text:
                    raise ValueError("Stored dataset dates must use YYYY-MM-DD format.")
                dates.append(parsed)
    except (OSError, UnicodeError, csv.Error, ValueError) as exc:
        if isinstance(exc, ProvenanceError):
            raise
        raise ProvenanceError("Stored dataset contains an invalid date range.") from exc
    if not dates:
        raise ProvenanceError("Stored dataset contains no dated records.")
    return min(dates), max(dates)


def _dataset_synthetic_flag(data_path: Path) -> bool | None:
    try:
        with data_path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if not reader.fieldnames or "is_synthetic" not in reader.fieldnames:
                return None
            flags: list[bool] = []
            for row in reader:
                value = (row.get("is_synthetic") or "").strip().casefold()
                if value not in ("true", "false"):
                    return None
                flags.append(value == "true")
    except (OSError, UnicodeError, csv.Error):
        return None
    if not flags or any(flag != flags[0] for flag in flags):
        return None
    return flags[0]


def _valid_verification(
    record: dict[str, Any],
    source: dict[str, Any],
    *,
    dataset_id: str,
    current_hash: str,
    dataset_dir: Path,
    date_range: tuple[date, date],
) -> bool:
    if (
        record.get("dataset_id") != dataset_id
        or record.get("dataset_sha256") != current_hash
        or record.get("source_id") != source.get("source_id")
        or record.get("verification_method") not in VERIFICATION_METHODS
        or not isinstance(record.get("verification_reference"), str)
        or not record["verification_reference"].strip()
        or not isinstance(record.get("verified_by"), (str, type(None)))
        or not isinstance(record.get("single_party"), bool)
    ):
        return False
    methods = source.get("accepted_verification_methods")
    if isinstance(methods, list) and record["verification_method"] not in methods:
        return False
    try:
        start = _date_field(record.get("reporting_period_start"), "reporting_period_start")
        end = _date_field(record.get("reporting_period_end"), "reporting_period_end")
        verified_at = datetime.fromisoformat(record.get("verified_at", ""))
    except (ProvenanceError, TypeError, ValueError):
        return False
    if (
        start > end
        or start > date_range[0]
        or end < date_range[1]
        or verified_at.tzinfo is None
    ):
        return False
    evidence_hash = record.get("evidence_file_sha256")
    if evidence_hash is not None:
        if not isinstance(evidence_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", evidence_hash):
            return False
        evidence_path = dataset_dir / "evidence" / evidence_hash
        if not evidence_path.is_file() or _sha256(evidence_path) != evidence_hash:
            return False
    return True


def _date_field(value: str, field: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ProvenanceError(f"{field} must use YYYY-MM-DD format.") from exc
    if parsed.isoformat() != value:
        raise ProvenanceError(f"{field} must use YYYY-MM-DD format.")
    return parsed


def _verification_block(
    record: dict[str, Any], source: dict[str, Any]
) -> dict[str, Any]:
    return {
        **record,
        "source": {
            "source_id": source.get("source_id"),
            "name": source.get("name") or None,
            "organization": source.get("organization") or None,
            "system": source.get("system") or None,
        },
    }


def resolve_provenance(
    dataset_id: str,
    uploads_root: Path,
    *,
    approved_sources_path: Path | None = None,
) -> dict[str, Any]:
    dataset_dir = _dataset_directory(dataset_id, uploads_root)
    metadata = _read_metadata(dataset_dir, dataset_id)
    data_path = dataset_dir / "data.csv"
    current_hash = _sha256(data_path)
    if current_hash != metadata.get("sha256"):
        logger.warning(
            "Dataset %s hash no longer matches upload metadata; verification status revoked.",
            dataset_id,
        )
        return {
            "dataset_id": dataset_id,
            "provenance_status": "uploaded_unverified",
            "verification": None,
            "verification_summary": None,
            "warning": "Stored file hash does not match the upload record.",
        }

    is_synthetic = _dataset_synthetic_flag(data_path)
    if is_synthetic is True:
        return {
            "dataset_id": dataset_id,
            "provenance_status": "synthetic",
            "verification": None,
            "verification_summary": None,
            "warning": None,
        }
    if is_synthetic is not False or metadata.get("is_synthetic") is not False:
        return {
            "dataset_id": dataset_id,
            "provenance_status": "uploaded_unverified",
            "verification": None,
            "verification_summary": None,
            "warning": "Stored dataset has no valid synthetic provenance flag.",
        }

    sources = _approved_sources(approved_sources_path)
    active_verification: dict[str, Any] | None = None
    history = _load_history(dataset_dir / "verification.json")
    try:
        date_range = _dataset_date_range(data_path)
    except ProvenanceError as exc:
        logger.warning("Dataset %s provenance cannot be checked: %s", dataset_id, exc)
        return {
            "dataset_id": dataset_id,
            "provenance_status": "uploaded_unverified",
            "verification": None,
            "verification_summary": None,
            "warning": "Stored dataset date range could not be checked.",
        }
    for record in history:
        if record.get("event") == "revocation":
            active_verification = None
        elif record.get("event") == "verification":
            source = sources.get(str(record.get("source_id")))
            if source is not None and _valid_verification(
                record,
                source,
                dataset_id=dataset_id,
                current_hash=current_hash,
                dataset_dir=dataset_dir,
                date_range=date_range,
            ):
                active_verification = record

    if active_verification is None:
        return {
            "dataset_id": dataset_id,
            "provenance_status": "uploaded_unverified",
            "verification": None,
            "verification_summary": None,
            "warning": None,
        }

    source = sources[active_verification["source_id"]]
    block = _verification_block(active_verification, source)
    return {
        "dataset_id": dataset_id,
        "provenance_status": "verified",
        "verification": block,
        "verification_summary": {
            "source_id": source["source_id"],
            "source_name": source.get("name") or None,
            "verification_method": active_verification["verification_method"],
            "verified_by": active_verification.get("verified_by") or None,
            "verified_at": active_verification.get("verified_at") or None,
            "single_party": bool(active_verification.get("single_party")),
            "identity_note": active_verification.get("identity_note") or None,
        },
        "warning": None,
    }


def verify_dataset(
    dataset_id: str,
    uploads_root: Path,
    *,
    source_id: str,
    verification_method: str,
    verification_reference: str,
    reporting_period_start: str,
    reporting_period_end: str,
    verified_by: str | None,
    evidence_file: bytes | None = None,
    approved_sources_path: Path | None = None,
) -> dict[str, Any]:
    dataset_dir = _dataset_directory(dataset_id, uploads_root)
    metadata = _read_metadata(dataset_dir, dataset_id)
    data_path = dataset_dir / "data.csv"
    current_hash = _sha256(data_path)
    if current_hash != metadata.get("sha256"):
        raise ProvenanceError("Stored dataset hash does not match the upload record.")
    is_synthetic = _dataset_synthetic_flag(data_path)
    if is_synthetic is True:
        raise ProvenanceError("Synthetic datasets cannot be verified.")
    if is_synthetic is not False or metadata.get("is_synthetic") is not False:
        raise ProvenanceError("Dataset synthetic provenance is missing or invalid.")

    sources = _approved_sources(approved_sources_path)
    source = sources.get(source_id)
    if source is None:
        raise ProvenanceError(f"Unknown approved source_id: {source_id}.")
    if verification_method not in VERIFICATION_METHODS:
        raise ProvenanceError("Unsupported verification_method.")
    accepted_methods = source.get("accepted_verification_methods")
    if isinstance(accepted_methods, list) and verification_method not in accepted_methods:
        raise ProvenanceError("Verification method is not accepted for this approved source.")
    reference = verification_reference.strip()
    if not reference:
        raise ProvenanceError("verification_reference must not be empty.")

    start = _date_field(reporting_period_start, "reporting_period_start")
    end = _date_field(reporting_period_end, "reporting_period_end")
    if start > end:
        raise ProvenanceError("Reporting period start must not be after its end.")

    csv_start, csv_end = _dataset_date_range(data_path)
    if start > csv_start or end < csv_end:
        raise ProvenanceError(
            "Reporting period must cover the stored CSV's complete date range."
        )

    uploader_value = metadata.get("uploader_identity") or metadata.get("uploader")
    uploader = (
        uploader_value.strip()
        if isinstance(uploader_value, str)
        and uploader_value.strip()
        and (
            metadata.get("uploader_identity")
            or uploader_value.strip().casefold() != "admin"
        )
        else None
    )
    verifier_identity = verified_by.strip() if verified_by and verified_by.strip() else None
    if (
        uploader is not None
        and verifier_identity is not None
        and uploader.casefold() == verifier_identity.casefold()
    ):
        raise ProvenanceError("The verifier must be a different person from the uploader.")
    single_party = uploader is None or verifier_identity is None

    record: dict[str, Any] = {
        "event": "verification",
        "source_id": source_id,
        "verification_method": verification_method,
        "verification_reference": reference,
        "reporting_period_start": start.isoformat(),
        "reporting_period_end": end.isoformat(),
        "dataset_id": dataset_id,
        "dataset_sha256": current_hash,
        "verified_by": verifier_identity or "admin",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "single_party": single_party,
        "identity_note": (
            "Uploader and verifier identities could not both be distinguished."
            if single_party
            else None
        ),
    }
    if evidence_file is not None:
        evidence_dir = dataset_dir / "evidence"
        evidence_dir.mkdir(exist_ok=True)
        evidence_digest = hashlib.sha256(evidence_file).hexdigest()
        evidence_path = evidence_dir / evidence_digest
        if not evidence_path.exists():
            with evidence_path.open("xb") as destination:
                destination.write(evidence_file)
        record["evidence_file_sha256"] = evidence_digest
    _append_event(dataset_dir / "verification.json", record)
    return resolve_provenance(
        dataset_id,
        uploads_root,
        approved_sources_path=approved_sources_path,
    )


def revoke_verification(
    dataset_id: str,
    uploads_root: Path,
    *,
    reason: str,
    revoked_by: str | None,
    approved_sources_path: Path | None = None,
) -> dict[str, Any]:
    if not reason.strip():
        raise ProvenanceError("Revocation reason must not be empty.")
    dataset_dir = _dataset_directory(dataset_id, uploads_root)
    metadata = _read_metadata(dataset_dir, dataset_id)
    current_hash = _sha256(dataset_dir / "data.csv")
    record = {
        "event": "revocation",
        "dataset_id": dataset_id,
        "dataset_sha256": current_hash,
        "reason": reason.strip(),
        "revoked_by": revoked_by.strip() if revoked_by and revoked_by.strip() else None,
        "revoked_at": datetime.now(timezone.utc).isoformat(),
    }
    if metadata.get("is_synthetic") is True:
        raise ProvenanceError("Synthetic datasets do not have a verification to revoke.")
    if resolve_provenance(
        dataset_id,
        uploads_root,
        approved_sources_path=approved_sources_path,
    )["provenance_status"] != "verified":
        raise ProvenanceError("Dataset has no active verification to revoke.")
    _append_event(dataset_dir / "verification.json", record)
    return resolve_provenance(
        dataset_id,
        uploads_root,
        approved_sources_path=approved_sources_path,
    )


def _append_event(history_path: Path, record: dict[str, Any]) -> None:
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
    with history_path.open("a", encoding="utf-8", newline="\n") as destination:
        destination.write(encoded)
