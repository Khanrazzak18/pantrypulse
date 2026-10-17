"""Uploads in a private, encrypted S3 bucket.

Credentials come from the environment (the task role in AWS); no keys are read from settings."""

from __future__ import annotations

from typing import Any

import boto3
from botocore.exceptions import ClientError

from app.storage.base import check_key

_MISSING = {"NoSuchKey", "404", "NotFound"}


class S3Storage:
    """The same four operations as LocalStorage, one object per key."""

    def __init__(self, bucket: str, client: Any | None = None, region: str | None = None):
        if not bucket:
            raise ValueError("S3Storage needs a bucket name.")
        self.bucket = bucket
        self._client = client or boto3.client("s3", region_name=region)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        check_key(key)  # before the client is touched
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            ServerSideEncryption="AES256",  # the bucket also requires it
        )

    def get(self, key: str) -> bytes:
        check_key(key)
        try:
            return self._client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except ClientError as exc:
            if exc.response["Error"]["Code"] in _MISSING:
                raise FileNotFoundError(key) from exc
            raise

    def delete(self, key: str) -> None:
        check_key(key)
        self._client.delete_object(Bucket=self.bucket, Key=key)  # an absent key is not an error

    def exists(self, key: str) -> bool:
        check_key(key)
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] in _MISSING:
                return False
            raise
