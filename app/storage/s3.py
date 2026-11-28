"""
app/storage/s3.py — S3 / MinIO ObjectStorageBackend powered by boto3.
"""

from __future__ import annotations

import logging

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from app.storage.base import ObjectStorageBackend, normalize_object_key

logger = logging.getLogger("FinSight.storage.s3")


class S3ObjectStorage(ObjectStorageBackend):
    """Stateless object storage backed by MinIO or AWS S3."""

    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str = "us-east-1",
    ):
        self.bucket = bucket
        client_kwargs: dict = {
            "service_name": "s3",
            "region_name": region or "us-east-1",
            "config": BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
        }
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        if access_key and secret_key:
            client_kwargs["aws_access_key_id"] = access_key
            client_kwargs["aws_secret_access_key"] = secret_key

        self._client = boto3.client(**client_kwargs)

    @staticmethod
    def _is_not_found(exc: ClientError) -> bool:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return code in {"404", "NoSuchKey", "NoSuchBucket", "NotFound"} or status == 404

    def ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            if not self._is_not_found(exc):
                raise
            logger.info(f"[Storage] Creating missing S3 bucket '{self.bucket}'")
            self._client.create_bucket(Bucket=self.bucket)

    def put_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        canonical = normalize_object_key(key)
        self._client.put_object(
            Bucket=self.bucket,
            Key=canonical,
            Body=data,
            ContentType=content_type or "application/octet-stream",
        )
        return canonical

    def get_bytes(self, key: str) -> bytes:
        canonical = normalize_object_key(key)
        try:
            resp = self._client.get_object(Bucket=self.bucket, Key=canonical)
            return resp["Body"].read()
        except ClientError as exc:
            if self._is_not_found(exc):
                raise FileNotFoundError(f"Object not found in S3: {canonical}") from exc
            raise

    def delete(self, key: str) -> None:
        canonical = normalize_object_key(key)
        try:
            self._client.delete_object(Bucket=self.bucket, Key=canonical)
        except ClientError as exc:
            if not self._is_not_found(exc):
                raise

    def exists(self, key: str) -> bool:
        canonical = normalize_object_key(key)
        try:
            self._client.head_object(Bucket=self.bucket, Key=canonical)
            return True
        except ClientError as exc:
            if self._is_not_found(exc):
                return False
            raise
