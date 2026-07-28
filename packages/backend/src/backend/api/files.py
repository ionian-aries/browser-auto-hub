from urllib.parse import quote

from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from backend.storage.minio_client import MinioStorage

router = APIRouter(prefix="/api/files", tags=["files"])

_CHUNK_SIZE = 64 * 1024


@router.get("/{object_key:path}")
async def download_file(object_key: str):
    """MinIO 对象代理下载（spec 1 二十三次修订：替代预签名 URL，永不过期）。

    boto3 为同步 SDK：get_object 经线程池执行避免阻塞事件循环；
    StreamingResponse 接收同步生成器时同样在线程池迭代，分块转发、恒定内存。
    """
    storage = MinioStorage()
    try:
        body, content_type = await run_in_threadpool(storage.get_object, object_key)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404", "NoSuchBucket"):
            raise HTTPException(404, "File not found") from e
        raise

    def _iter_chunks():
        try:
            while chunk := body.read(_CHUNK_SIZE):
                yield chunk
        finally:
            body.close()

    filename = object_key.rsplit("/", 1)[-1]
    headers = {
        # RFC 5987：中文文件名需 filename* 百分号编码
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
    }
    return StreamingResponse(_iter_chunks(), media_type=content_type, headers=headers)
