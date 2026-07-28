import boto3
from botocore.config import Config as BotoConfig

from backend.config import get_settings


class MinioStorage:
    def __init__(self, settings=None):
        if settings is None:
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

    @classmethod
    async def create(cls, session=None) -> "MinioStorage":
        """构造 MinioStorage（配置唯一来源 `.env`，spec 1 十七次修订）。

        session 参数保留仅为兼容调用点签名，不参与配置解析。
        bucket 由部署方提前创建（十八次修订），此处仅连接使用。
        """
        return cls(settings=get_settings())

    def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return key

    def get_object(self, key: str):
        """取对象流，返回 (body, content_type)。NoSuchKey 抛 botocore ClientError。

        body 为 botocore StreamingBody（read/close），由调用方负责关闭。
        供 /api/files 代理下载使用（spec 1 二十三次修订，预签名链路已退役）。
        """
        resp = self._client.get_object(Bucket=self._bucket, Key=key)
        return resp["Body"], resp.get("ContentType", "application/octet-stream")
