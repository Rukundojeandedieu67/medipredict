"""Backend-only access to the configured dashboard data source."""

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from .config import settings

MAX_DASHBOARD_CSV_BYTES = 20 * 1024 * 1024


class StorageConfigurationError(RuntimeError):
    """The configured object-storage settings are incomplete."""


class ObjectStorageError(RuntimeError):
    """The configured object could not be read."""


def _object_store_client():
    required = {
        "MEDIPREDICT_OBJECT_STORE_BUCKET": settings.object_store_bucket,
        "MEDIPREDICT_OBJECT_STORE_ENDPOINT_URL": settings.object_store_endpoint_url,
        "MEDIPREDICT_OBJECT_STORE_ACCESS_KEY_ID": settings.object_store_access_key_id,
        "MEDIPREDICT_OBJECT_STORE_SECRET_ACCESS_KEY": settings.object_store_secret_access_key,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise StorageConfigurationError(
            "S3 storage requires " + ", ".join(missing) + "."
        )
    if not settings.object_store_endpoint_url.startswith("https://"):
        raise StorageConfigurationError(
            "S3 object storage endpoint must use HTTPS."
        )

    return boto3.client(
        "s3",
        endpoint_url=settings.object_store_endpoint_url,
        region_name=settings.object_store_region,
        aws_access_key_id=settings.object_store_access_key_id,
        aws_secret_access_key=settings.object_store_secret_access_key,
        config=Config(
            connect_timeout=5,
            read_timeout=30,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )


def read_dashboard_csv() -> bytes | None:
    """Read the dashboard CSV locally by default, or from private S3-compatible storage."""
    if settings.storage_backend == "local":
        if not settings.csv_path.exists():
            return None
        return settings.csv_path.read_bytes()

    if settings.storage_backend != "s3":
        raise StorageConfigurationError("Unsupported object-storage backend.")
    if not settings.dashboard_data_key:
        raise StorageConfigurationError(
            "MEDIPREDICT_DASHBOARD_DATA_KEY must identify the dashboard CSV object."
        )

    try:
        client = _object_store_client()
        response = client.get_object(
            Bucket=settings.object_store_bucket,
            Key=settings.dashboard_data_key,
        )
        body = response["Body"]
        try:
            content_length = response.get("ContentLength")
            if content_length is not None and content_length > MAX_DASHBOARD_CSV_BYTES:
                raise ObjectStorageError(
                    "The dashboard CSV exceeds the 20 MiB storage limit."
                )
            content = body.read(MAX_DASHBOARD_CSV_BYTES + 1)
            if len(content) > MAX_DASHBOARD_CSV_BYTES:
                raise ObjectStorageError(
                    "The dashboard CSV exceeds the 20 MiB storage limit."
                )
            return content
        finally:
            body.close()
    except (BotoCoreError, ClientError) as exc:
        raise ObjectStorageError(
            "The dashboard CSV could not be read from configured object storage."
        ) from exc
