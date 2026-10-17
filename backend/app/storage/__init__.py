from app.config import Settings
from app.storage.base import StorageBackend, check_key
from app.storage.local import LocalStorage
from app.storage.s3 import S3Storage

__all__ = ["LocalStorage", "S3Storage", "StorageBackend", "check_key", "make_storage"]


def make_storage(settings: Settings) -> StorageBackend:
    """Local folder for development, a private S3 bucket when deployed (STORAGE_BACKEND=s3)."""
    backend = settings.storage_backend.lower()
    if backend == "local":
        return LocalStorage(settings.storage_path)
    if backend == "s3":
        if not settings.s3_bucket:
            raise ValueError("STORAGE_BACKEND=s3 needs S3_BUCKET to name the bucket.")
        return S3Storage(settings.s3_bucket, region=settings.aws_region)
    raise ValueError(f"STORAGE_BACKEND must be 'local' or 's3', not {settings.storage_backend!r}.")
