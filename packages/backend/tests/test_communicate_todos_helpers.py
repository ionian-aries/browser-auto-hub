"""oa.communicate_todos 纯函数助手测试（列表级 href 去重，spec 3 2026-07-24 修订三）"""

import asyncio

import pytest

from engine.pipelines.oa.communicate_todos import OaCommunicateTodosPipeline


def test_extract_fd_id_from_relative_href():
    href = "/km/notify/sysNotifyTodo.do?method=view&fdId=19f7fa590e4d644a234b8264566b1ca7&fdModelName=x"
    assert (
        OaCommunicateTodosPipeline._extract_fd_id(href)
        == "19f7fa590e4d644a234b8264566b1ca7"
    )


def test_extract_fd_id_from_absolute_url():
    url = "https://ioa.sd-port.net/km/notify/sysNotifyTodo.do?method=view&fdId=19f6ecba4b0043d72d304a045bead2a0"
    assert (
        OaCommunicateTodosPipeline._extract_fd_id(url)
        == "19f6ecba4b0043d72d304a045bead2a0"
    )


def test_extract_fd_id_missing_returns_none():
    assert OaCommunicateTodosPipeline._extract_fd_id("/km/notify/sysNotifyTodo.do?method=view") is None
    assert OaCommunicateTodosPipeline._extract_fd_id("") is None


def test_metadata_schema_keys_and_defaults():
    """schema 含修订四引入的两个键及默认值；version 为纯溯源标记，schema 变更
    不再要求 bump（spec 1 二十七次修订：sync 按内容对比）。"""
    meta = OaCommunicateTodosPipeline.metadata
    props = meta.config_schema["properties"]
    assert props["max_verify_rounds"]["default"] == 2
    assert props["concurrency"]["default"] == 1


class _FakeDetail:
    def __init__(self):
        self.url = "about:blank"
        self.closed = False

    async def goto(self, href, wait_until=None):
        self.url = href

    async def close(self):
        self.closed = True


class _FakeContext:
    def __init__(self):
        self.pages = []

    async def new_page(self):
        page = _FakeDetail()
        self.pages.append(page)
        return page


class _FakePage:
    def __init__(self):
        self.context = _FakeContext()


class _FakeLogger:
    async def step(self, *args, **kwargs):
        pass

    async def error(self, *args, **kwargs):
        pass


class _FakeCtx:
    logger = _FakeLogger()


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency,expected_peak", [(1, 1), (2, 2)])
async def test_open_detail_respects_concurrency(monkeypatch, concurrency, expected_peak):
    """Semaphore 限流：并行标签页数不超过 concurrency；默认 1 时与串行等价
    （spec 3 2026-07-24 修订四）。"""
    peak = 0
    current = 0

    async def fake_extract_meta(self, page, task_id, config, ctx, stats, shared_lock):
        nonlocal peak, current
        current += 1
        peak = max(peak, current)
        await asyncio.sleep(0.01)
        current -= 1
        return {"task_id": task_id, "title": "t"}

    monkeypatch.setattr(
        OaCommunicateTodosPipeline, "_extract_meta", fake_extract_meta
    )

    pipeline = OaCommunicateTodosPipeline()
    page = _FakePage()
    ctx = _FakeCtx()
    stats = {"skipped": 0, "extract_failures": 0}
    items = [
        {"task_id": f"fd{i:02x}", "href": f"https://oa/x?fdId=fd{i:02x}"}
        for i in range(4)
    ]
    semaphore = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()

    results = await asyncio.gather(*(
        pipeline._open_detail(
            page, item, {}, ctx, stats, set(), semaphore, lock
        )
        for item in items
    ))

    assert peak == expected_peak
    assert all(r is not None for r in results)
    assert stats["extract_failures"] == 0
    assert all(p.closed for p in page.context.pages)

