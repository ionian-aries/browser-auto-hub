import asyncio

import pytest

from engine.pipelines.oa.shared import browser as browser_mod


class FakePage:
    pass


class FakeBrowser:
    def __init__(self):
        self.closed = False

    async def new_page(self):
        return FakePage()

    async def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self, browser):
        self._browser = browser
        self.launch_kwargs = None

    async def launch(self, **kwargs):
        self.launch_kwargs = kwargs
        return self._browser


class FakePw:
    def __init__(self, browser):
        self.chromium = FakeChromium(browser)


class FakePwCM:
    def __init__(self, pw):
        self._pw = pw

    async def __aenter__(self):
        return self._pw

    async def __aexit__(self, *args):
        return False


def _patch(monkeypatch, browser):
    pw = FakePw(browser)
    monkeypatch.setattr(browser_mod, "async_playwright", lambda: FakePwCM(pw))
    return pw


@pytest.mark.asyncio
async def test_oa_browser_yields_page_and_closes(monkeypatch):
    browser = FakeBrowser()
    _patch(monkeypatch, browser)
    async with browser_mod.oa_browser({}) as page:
        assert isinstance(page, FakePage)
        assert not browser.closed
    assert browser.closed


@pytest.mark.asyncio
async def test_oa_browser_headless_config(monkeypatch):
    browser = FakeBrowser()
    pw = _patch(monkeypatch, browser)
    async with browser_mod.oa_browser({"headless": False}):
        pass
    assert pw.chromium.launch_kwargs == {"headless": False}


@pytest.mark.asyncio
async def test_oa_browser_default_headless(monkeypatch):
    browser = FakeBrowser()
    pw = _patch(monkeypatch, browser)
    async with browser_mod.oa_browser({}):
        pass
    assert pw.chromium.launch_kwargs == {"headless": True}


@pytest.mark.asyncio
async def test_oa_browser_closes_on_exception(monkeypatch):
    browser = FakeBrowser()
    _patch(monkeypatch, browser)
    with pytest.raises(RuntimeError, match="boom"):
        async with browser_mod.oa_browser({}):
            raise RuntimeError("boom")
    assert browser.closed


@pytest.mark.asyncio
async def test_oa_browser_close_browser_false(monkeypatch):
    browser = FakeBrowser()
    _patch(monkeypatch, browser)
    async with browser_mod.oa_browser({"close_browser": False}):
        pass
    assert not browser.closed


class SlowCloseBrowser(FakeBrowser):
    def __init__(self):
        super().__init__()
        self.close_started = asyncio.Event()

    async def close(self):
        self.close_started.set()
        await asyncio.sleep(0.2)
        self.closed = True


@pytest.mark.asyncio
async def test_oa_browser_close_survives_double_cancel(monkeypatch):
    """超时取消后 close 进行中又遇手动 cancel：close 不得被打断（chromium 进程泄漏）。"""
    browser = SlowCloseBrowser()
    _patch(monkeypatch, browser)

    async def _use():
        async with browser_mod.oa_browser({}):
            await asyncio.sleep(60)

    task = asyncio.create_task(_use())
    await asyncio.sleep(0.02)
    task.cancel()  # 第一次取消（如 runner 超时）
    await browser.close_started.wait()
    task.cancel()  # 第二次取消（cancel 端点竞态）
    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.sleep(0.3)
    assert browser.closed  # close 在后台完成，进程不泄漏
