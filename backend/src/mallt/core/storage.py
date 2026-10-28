"""S3-compatible object storage (Neon Object Storage in dev, AWS S3 in prod).

Browsers upload straight to the bucket with a presigned PUT; the API only issues the URL and
stores the object key. Presigning is pure computation (no network), so it is safe to call from
async code.
"""

import uuid
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.config import Config

from mallt.core.config import Settings
from mallt.core.errors import BadRequest
from mallt.core.ids import uuid7

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


@dataclass(frozen=True)
class PresignedUpload:
    url: str
    key: str
    headers: dict[str, str]
    expires_in: int


class Storage:
    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.s3_bucket
        self._public_base = settings.s3_public_base_url.rstrip("/")
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id or None,
            aws_secret_access_key=settings.s3_secret_access_key or None,
            # Neon requires path-style addressing, and a checksum baked into a presigned PUT
            # (computed from an empty body) would reject every real upload.
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                request_checksum_calculation="when_required",
            ),
        )

    def presign_put(self, key: str, content_type: str, expires_in: int = 300) -> PresignedUpload:
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise BadRequest("unsupported_content_type", "Only JPEG, PNG or WebP images.")
        url: str = self._client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self._bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expires_in,
        )
        return PresignedUpload(
            url=url, key=key, headers={"Content-Type": content_type}, expires_in=expires_in
        )

    def public_url(self, key: str) -> str:
        return f"{self._public_base}/{key}"

    @staticmethod
    def object_key(*, organization_id: uuid.UUID, kind: str, ext: str) -> str:
        return f"org/{organization_id}/{kind}/{uuid7()}.{ext}"
