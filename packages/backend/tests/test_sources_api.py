import pytest
from contextlib import asynccontextmanager
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from backend.api.sources import router as sources_router


@asynccontextmanager
async def _test_lifespan(app: FastAPI):
    yield


@pytest.fixture
async def sources_client():
    """sources 端点无 DB 依赖，独立 client 读真实 sources.json。"""
    test_app = FastAPI(lifespan=_test_lifespan)
    test_app.include_router(sources_router)
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_list_sources_structure(sources_client):
    response = await sources_client.get("/api/sources")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 4

    by_name = {s["source_name"]: s for s in data}

    # 交通运输部: 3 entry, 2 详情变体, 1 自定义 entry
    mot = by_name["交通运输部"]
    assert mot["entry_count"] == 3
    assert mot["detail_variant_count"] == 2
    assert mot["has_pagination"] is True
    assert mot["entries_with_override"] == 1
    assert mot["list_fields"] == ["container", "item", "title", "date", "link"]
    assert mot["detail_fields"] == ["content", "title", "date", "source"]
    # 图片新闻 entry 有 list override
    pic = next(e for e in mot["entries"] if e["entry_name"] == "图片新闻")
    assert pic["has_override"] is True
    other = next(e for e in mot["entries"] if e["entry_name"] == "交通要闻")
    assert other["has_override"] is False

    # 中央人民政府: 2 entry, 1 变体, 0 自定义
    gov = by_name["中央人民政府"]
    assert gov["entry_count"] == 2
    assert gov["detail_variant_count"] == 1
    assert gov["entries_with_override"] == 0
    assert all(e["has_override"] is False for e in gov["entries"])

    # 工信部: 10 entry, 1 变体, 4 自定义
    miit = by_name["工信部"]
    assert miit["entry_count"] == 10
    assert miit["detail_variant_count"] == 1
    assert miit["entries_with_override"] == 4

    # 发改委: 5 entry, 3 变体, 0 自定义
    ndrc = by_name["发改委"]
    assert ndrc["entry_count"] == 5
    assert ndrc["detail_variant_count"] == 3
    assert ndrc["entries_with_override"] == 0


@pytest.mark.asyncio
async def test_list_sources_no_selector_values(sources_client):
    """不暴露 CSS 选择器值——响应中不应出现选择器字符串。"""
    response = await sources_client.get("/api/sources")
    data = response.json()
    # list_fields / detail_fields 只含字段名，不含选择器值
    for s in data:
        assert "ul.news-list" not in s["list_fields"]
        assert "div.article-content" not in s["detail_fields"]
        for e in s["entries"]:
            assert "list" not in e  # entry 不暴露 override 的选择器内容
            assert "fields" not in e
