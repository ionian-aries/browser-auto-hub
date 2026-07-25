import pytest
from unittest.mock import AsyncMock, MagicMock
from engine.pipelines.news_collector.crawler import (
    try_extract_items, go_next_page, try_extract_detail,
)


class FakeLocator:
    def __init__(self, items):
        self._items = items

    async def count(self):
        return len(self._items)

    def nth(self, i):
        return self._items[i]


class FakeElement:
    def __init__(self, text="", href=None, child=None):
        self._text = text
        self._href = href
        self._child = child

    async def inner_text(self):
        return self._text

    async def get_attribute(self, name):
        if name == "href":
            return self._href
        return None

    async def query_selector(self, sel):
        return self._child


class TestTryExtractItems:
    @pytest.mark.asyncio
    async def test_selectors_mode(self):
        """selectors 模式：用 page.locator 提取"""
        # 构造 fake item: <li><a href="/news/1">标题A</a><span>2026-06-01</span></li>
        link = FakeElement(text="标题A", href="/news/1")
        date_el = FakeElement(text="2026-06-01")
        item = MagicMock()
        item.inner_text = AsyncMock(return_value="标题A\n2026-06-01")
        item.query_selector = AsyncMock(side_effect=lambda sel: link if "a" in sel else date_el)
        item.query_selector_all = AsyncMock(return_value=[date_el])

        page = MagicMock()
        page.locator = MagicMock(return_value=FakeLocator([item]))

        config = {
            "mode": "selectors",
            "fields": {
                "container": "ul.news-list",
                "item": "li",
                "title": "a",
                "link": "a",
                "link_attr": "href",
                "date": "span",
            },
        }
        items = await try_extract_items(page, config)
        assert len(items) == 1
        assert items[0]["title"] == "标题A"

    @pytest.mark.asyncio
    async def test_script_mode(self):
        """script 模式：用 page.evaluate 执行 JS"""
        page = MagicMock()
        page.evaluate = AsyncMock(return_value=[
            {"title": "新闻1", "date": "2026-06-15", "url": "/n/1"},
            {"title": "新闻2", "date": "2026-06-14", "url": "/n/2"},
        ])

        config = {
            "mode": "script",
            "fields": {
                "items": "() => Array.from(document.querySelectorAll('li')).map(...)",
            },
        }
        items = await try_extract_items(page, config)
        assert len(items) == 2
        assert items[0]["title"] == "新闻1"

    @pytest.mark.asyncio
    async def test_empty_result(self):
        """提取结果为空列表"""
        page = MagicMock()
        page.locator = MagicMock(return_value=FakeLocator([]))

        config = {"mode": "selectors", "fields": {"container": "ul", "item": "li",
                   "title": "a", "link": "a", "link_attr": "href", "date": "span"}}
        items = await try_extract_items(page, config)
        assert items == []


class TestGoNextPage:
    @pytest.mark.asyncio
    async def test_no_pagination(self):
        """pagination 为 None → 返回 False"""
        page = MagicMock()
        result = await go_next_page(page, None)
        assert result is False

    @pytest.mark.asyncio
    async def test_selectors_click_next(self):
        """selectors 模式：点击下一页按钮"""
        next_btn = MagicMock()
        next_btn.count = AsyncMock(return_value=1)
        next_btn.first = MagicMock()
        next_btn.first.click = AsyncMock()

        page = MagicMock()
        page.locator = MagicMock(return_value=next_btn)
        page.wait_for_load_state = AsyncMock()

        config = {"mode": "selectors", "fields": {"next": "a.next", "next_text": "下一页"}}
        result = await go_next_page(page, config)
        assert result is True
        next_btn.first.click.assert_called_once()


class TestTryExtractDetail:
    @pytest.mark.asyncio
    async def test_selectors_mode(self):
        """selectors 模式提取正文"""
        page = MagicMock()

        def fake_locator(sel):
            loc = MagicMock()
            if "h1" in sel:
                loc.first = MagicMock()
                loc.first.inner_text = AsyncMock(return_value="文章标题")
                loc.count = AsyncMock(return_value=1)
            elif "content" in sel:
                loc.first = MagicMock()
                loc.first.inner_text = AsyncMock(return_value="这是正文内容，超过50字的文本..." * 5)
                loc.count = AsyncMock(return_value=1)
            elif "date" in sel:
                loc.first = MagicMock()
                loc.first.inner_text = AsyncMock(return_value="2026-06-15")
                loc.count = AsyncMock(return_value=1)
            else:
                loc.count = AsyncMock(return_value=0)
            return loc

        page.locator = fake_locator

        config = {
            "mode": "selectors",
            "fields": {"title": "h1", "content": "div.content", "date": "span.date", "source": "span.src"},
        }
        result = await try_extract_detail(page, config)
        assert result is not None
        assert result["title"] == "文章标题"

    @pytest.mark.asyncio
    async def test_script_mode(self):
        """script 模式执行 JS"""
        page = MagicMock()
        page.evaluate = AsyncMock(side_effect=lambda code: {
            "title_code": "文章标题",
            "content_code": "正文内容" * 20,
            "date_code": "2026-06-15",
            "source_code": "新华社",
        }.get(code, ""))

        config = {
            "mode": "script",
            "fields": {
                "title": "title_code",
                "content": "content_code",
                "date": "date_code",
                "source": "source_code",
            },
        }
        result = await try_extract_detail(page, config)
        assert result is not None
        assert result["title"] == "文章标题"
