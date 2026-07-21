import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from backend.config import get_settings


class MinioStorage:
    def __init__(self):
        settings = get_settings()
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.minio_endpoint,
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            region_name="us-east-1",
            config=BotoConfig(signature_version="s3v4"),
        )
        self._bucket = settings.minio_bucket
        self._presign_expires = settings.minio_presign_expires_seconds

    def ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self._bucket)

    def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return key

    def download(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()

    def presign_url(self, key: str, expires_in: int | None = None) -> str:
        """Generate a presigned GET URL for the given object key."""
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in or self._presign_expires,
        )
