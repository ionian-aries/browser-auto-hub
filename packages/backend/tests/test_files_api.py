# packages/backend/tests/test_files_api.py
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api import files as files_mod
from backend.api.files import router as files_router


def _make_client() -> AsyncClient:
    app = FastAPI()
    app.include_router(files_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_download_streams_content(monkeypatch):
    body = BytesIO(b"x" * (70 * 1024))  # 跨 64KB chunk 边界
    storage = MagicMock()
    storage.get_object.return_value = (body, "application/octet-stream")
    monkeypatch.setattr(files_mod, "MinioStorage", MagicMock(return_value=storage))

    async with _make_client() as ac:
        resp = await ac.get("/api/files/browser-auto-hub/attachments/t1/%E6%8A%A5%E8%A1%A8.xlsx")

    assert resp.status_code == 200
    assert resp.content == b"x" * (70 * 1024)
    storage.get_object.assert_called_once_with("browser-auto-hub/attachments/t1/报表.xlsx")
    # RFC 5987 filename* 编码中文附件名
    assert "filename*=UTF-8''%E6%8A%A5%E8%A1%A8.xlsx" in resp.headers["content-disposition"]


@pytest.mark.asyncio
async def test_download_not_found(monkeypatch):
    storage = MagicMock()
    storage.get_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "GetObject"
    )
    monkeypatch.setattr(files_mod, "MinioStorage", MagicMock(return_value=storage))

    async with _make_client() as ac:
        resp = await ac.get("/api/files/missing/key.bin")

    assert resp.status_code == 404
