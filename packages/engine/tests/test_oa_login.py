import pytest

from engine.pipelines.oa.shared.login import LoginError, LoginTimeout, oa_login


def test_login_exports():
    """Verify login module exports expected symbols."""
    assert callable(oa_login)
    assert issubclass(LoginError, Exception)
    assert issubclass(LoginTimeout, Exception)


@pytest.mark.asyncio
async def test_login_raises_on_empty_credentials():
    """oa_login should raise LoginError if username/password missing."""

    class FakePage:
        url = ""
        async def goto(self, *a, **kw): pass
        def get_by_role(self, *a, **kw): return self
        async def wait_for(self, **kw): pass
        async def fill(self, *a, **kw): pass
        async def click(self, *a, **kw): pass
        def or_(self, *a): return self

    with pytest.raises(LoginError, match="username"):
        await oa_login(FakePage(), {"login_url": "http://x", "username": "", "password": "p"})


class _NavFakePage:
    """点击登录后按脚本设置 URL，模拟导航失败/成功序列。"""

    def __init__(self, url_after_clicks: list[str], body_text: str = ""):
        self.url = ""
        self.goto_calls = 0
        self._url_after_clicks = url_after_clicks
        self._click_count = 0
        self._body_text = body_text

    async def goto(self, url, **kw):
        self.goto_calls += 1
        self.url = url

    def get_by_role(self, *a, **kw):
        page = self

        class El:
            async def wait_for(self, **kw): pass
            async def fill(self, *a): pass
            def or_(self, *a): return self
            async def click(self, *a, **kw):
                page.url = page._url_after_clicks[
                    min(page._click_count, len(page._url_after_clicks) - 1)
                ]
                page._click_count += 1

        return El()

    async def wait_for_timeout(self, *a): pass
    async def inner_text(self, *a): return self._body_text


_CONFIG = {
    "login_url": "https://ioa/login.jsp",
    "username": "u",
    "password": "p",
    "page_load_timeout": 2000,
    "element_visible_timeout": 100,
}


@pytest.mark.asyncio
async def test_login_retries_once_on_navigation_failure():
    """chrome-error 导航失败 → 自动完整重试 1 次并成功
    （spec 3 2026-07-24 修订五：服务端 SSO 状态在首次尝试后建立）。"""
    page = _NavFakePage([
        "chrome-error://chromewebdata/",
        "https://ioa/sys/portal/page.jsp",
    ])
    await oa_login(page, _CONFIG)
    assert page.goto_calls == 2


@pytest.mark.asyncio
async def test_login_navigation_failure_twice_raises_timeout():
    """两次尝试均导航失败 → LoginTimeout，错误消息含真实原因与重试说明。"""
    page = _NavFakePage(["chrome-error://chromewebdata/"])
    with pytest.raises(LoginTimeout, match="不可达.*已自动重试 1 次"):
        await oa_login(page, _CONFIG)
    assert page.goto_calls == 2


@pytest.mark.asyncio
async def test_login_credential_error_not_retried():
    """凭据错误（login_error 页）→ LoginError 立即抛出，不触发重试。"""
    page = _NavFakePage(
        ["https://ioa/login.jsp?login_error=1"], body_text="系统提示： 密码错误\n"
    )
    with pytest.raises(LoginError, match="密码错误"):
        await oa_login(page, _CONFIG)
    assert page.goto_calls == 1

