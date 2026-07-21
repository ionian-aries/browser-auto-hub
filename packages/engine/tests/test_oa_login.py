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
