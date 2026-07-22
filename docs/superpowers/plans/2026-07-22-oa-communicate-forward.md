# OA 沟通转发 Pipeline 迁移 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `browser-agent/scripts_v3/oa_communicate_forward.py` 迁移为平台 pipeline `oa.communicate_forward`，支持一次登录批量串行转发、逐条独立 commit 回写 fwd=1。

**Architecture:** 在 `engine/pipelines/oa/` 下新增 `communicate_forward.py`（步骤函数内联为私有方法，同 communicate_todos 先例）；新增 `oa/shared/browser.py` 统一浏览器生命周期并改造 communicate_todos 复用；DB 走 `ctx.db` 原始 SQL，截图走 `ctx.logger.step(screenshot=...)`。

**Tech Stack:** Python 3.11+, Playwright async API, SQLAlchemy 2.0 async (raw SQL via `text()`), pytest + pytest-asyncio。

**Spec:** `docs/specs/5.2026-07-22-OA沟通转发Pipeline设计.md`

## Global Constraints

- 所有改动在 worktree 分支 `worktree-oa-forward-pipeline` 上进行，根目录 `/Users/zhuanghengheng/浏览器browser/browser-auto-hub/.claude/worktrees/oa-forward-pipeline`
- engine 包**不能 import backend 任何模块**；DB 只能用 `ctx.db`（AsyncSession）+ `sqlalchemy.text()` 原始 SQL
- 超时默认值必须与 communicate_todos 一致：`page_load_timeout=15000`、`element_visible_timeout=5000`、`action_settle_timeout=500`
- `trigger_modes=["api", "manual"]`（不支持 cron）
- 无 `submit` 参数——总是真实提交
- 串行逐条转发，禁止并发（避免 OA 限流）
- 每条 submit 成功后**立即 `await ctx.db.commit()`**，不得依赖 runner 统一 commit
- 测试命令统一从 repo 根目录运行：`uv run pytest <path> -v`
- 人名歧义（候选 >1）禁止自动选，必须 raise（源脚本行为，安全红线）

---

### Task 1: shared/browser.py — 统一浏览器生命周期

**Files:**
- Create: `packages/engine/src/engine/pipelines/oa/shared/browser.py`
- Modify: `packages/engine/src/engine/pipelines/oa/shared/__init__.py`
- Test: `packages/engine/tests/test_oa_browser.py`

**Interfaces:**
- Consumes: `playwright.async_api.async_playwright`
- Produces: `oa_browser(config: dict) -> AsyncIterator[Page]`（async context manager，yield page，自动 close browser；`config.get("headless", True)` 控制无头模式）。Task 2、Task 3 均消费此接口。

- [ ] **Step 1: Write the failing test**

创建 `packages/engine/tests/test_oa_browser.py`：

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/engine/tests/test_oa_browser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.pipelines.oa.shared.browser'`

- [ ] **Step 3: Write minimal implementation**

创建 `packages/engine/src/engine/pipelines/oa/shared/browser.py`：

```python
"""Shared browser lifecycle for OA pipelines."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from playwright.async_api import Page, async_playwright


@asynccontextmanager
async def oa_browser(config: dict) -> AsyncIterator[Page]:
    """Launch Chromium, yield a page, always close the browser."""
    headless = config.get("headless", True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        try:
            page = await browser.new_page()
            yield page
        finally:
            await browser.close()
```

将 `packages/engine/src/engine/pipelines/oa/shared/__init__.py` 全文替换为：

```python
"""Shared utilities for OA pipelines (login, browser)."""

from .browser import oa_browser
from .login import LoginError, LoginTimeout, oa_login

__all__ = ["oa_browser", "oa_login", "LoginError", "LoginTimeout"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/engine/tests/test_oa_browser.py packages/engine/tests/test_oa_login.py -v`
Expected: 全部 PASS（含旧 login 测试无回归）

- [ ] **Step 5: Commit**

```bash
git add packages/engine/src/engine/pipelines/oa/shared/browser.py \
        packages/engine/src/engine/pipelines/oa/shared/__init__.py \
        packages/engine/tests/test_oa_browser.py
git commit -m "feat: add shared oa_browser context manager for OA pipelines"
```

---

### Task 2: communicate_todos 改用 oa_browser（行为不变重构）

**Files:**
- Modify: `packages/engine/src/engine/pipelines/oa/communicate_todos.py`

**Interfaces:**
- Consumes: Task 1 的 `oa_browser(config)`
- Produces: 无新接口；`oa.communicate_todos` 注册名、config_schema、行为完全不变

- [ ] **Step 1: 修改 import**

`communicate_todos.py` 第 8 行：

```python
from playwright.async_api import Page, async_playwright
```

改为：

```python
from playwright.async_api import Page
```

第 12 行之后（`from engine.pipelines.oa.shared.login import ...` 一行后）插入：

```python
from engine.pipelines.oa.shared.browser import oa_browser
```

- [ ] **Step 2: 替换浏览器启动/关闭逻辑**

第 71-75 行原文：

```python
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
```

改为：

```python
        async with oa_browser(config) as page:
            try:
```

第 134-138 行原文：

```python
            except Exception as e:
                await ctx.logger.error("crawl", f"Unexpected error: {e}")
                return PipelineResult(success=False, error=str(e))
            finally:
                await browser.close()
```

改为（删除 finally 块，close 由 oa_browser 负责）：

```python
            except Exception as e:
                await ctx.logger.error("crawl", f"Unexpected error: {e}")
                return PipelineResult(success=False, error=str(e))
```

注意：try 内部所有代码缩进不变（`try:` 仍在原层级）。

- [ ] **Step 3: Run full engine + backend tests (regression)**

Run: `uv run pytest packages/engine/tests packages/backend/tests -v`
Expected: 全部 PASS（重点：test_oa_pipeline_registration.py、test_runner*.py 无回归）

- [ ] **Step 4: Commit**

```bash
git add packages/engine/src/engine/pipelines/oa/communicate_todos.py
git commit -m "refactor: communicate_todos uses shared oa_browser (no behavior change)"
```

---

### Task 3: communicate_forward.py — 转发 Pipeline 实现

**Files:**
- Create: `packages/engine/src/engine/pipelines/oa/communicate_forward.py`
- Test: `packages/engine/tests/test_oa_forward.py`

**Interfaces:**
- Consumes: `oa_browser(config)`（Task 1）；`oa_login(page, config)`、`LoginError`、`LoginTimeout`（shared/login.py）；`ExecutionContext`（`ctx.db` AsyncSession、`ctx.logger.step(name, message, level="info", screenshot: bytes | None = None)`）
- Produces: 注册名 `oa.communicate_forward`；类 `OaCommunicateForwardPipeline(BasePipeline)`，私有方法签名：
  - `_validate(config: dict) -> str | None`（staticmethod）
  - `_check_pending(ctx: ExecutionContext, task_id: str) -> str`（staticmethod，返回 `"pending" | "forwarded" | "missing"`）
  - `_update_fwd(ctx: ExecutionContext, task_id: str) -> str`（staticmethod，返回 `"updated" | "forwarded" | "missing"`）
  - `_goto_forward(page: Page, task_id: str, config: dict) -> None`（staticmethod）
  - `_fill_form(page, item, config, ctx, step) -> None`（实例方法）
  - `_pick_one(page: Page, field: str, person: str) -> None`（staticmethod，field ∈ `"participant" | "copy"`）
  - `_submit_and_verify(page: Page) -> None`（staticmethod）
  - `_safe_screenshot(page: Page) -> bytes | None`（staticmethod）

- [ ] **Step 1: Write the failing tests**

创建 `packages/engine/tests/test_oa_forward.py`：

```python
from contextlib import asynccontextmanager
from datetime import datetime

import pytest


@pytest.fixture(autouse=True)
def _discover():
    from engine.registry import PipelineRegistry

    PipelineRegistry._pipelines.clear()
    PipelineRegistry.discover()
    yield


def _load():
    from engine.pipelines.oa import communicate_forward as cf

    return cf


def test_forward_pipeline_registers():
    from engine.registry import PipelineRegistry

    assert "oa.communicate_forward" in PipelineRegistry.all()


def test_forward_pipeline_metadata():
    from engine.registry import PipelineRegistry

    cls = PipelineRegistry.get("oa.communicate_forward")
    assert cls.metadata.display_name == "OA 沟通批量转发"
    assert sorted(cls.metadata.trigger_modes) == ["api", "manual"]
    required = cls.metadata.config_schema["required"]
    assert "username" in required and "password" in required and "forwards" in required


# ---------- _validate ----------

def test_validate_ok():
    cf = _load()
    cfg = {"forwards": [{"task_id": "t1", "recipients": ["张三"]}]}
    assert cf.OaCommunicateForwardPipeline._validate(cfg) is None


def test_validate_missing_forwards():
    cf = _load()
    assert "forwards" in cf.OaCommunicateForwardPipeline._validate({})


def test_validate_empty_forwards():
    cf = _load()
    assert "forwards" in cf.OaCommunicateForwardPipeline._validate({"forwards": []})


def test_validate_missing_task_id():
    cf = _load()
    err = cf.OaCommunicateForwardPipeline._validate(
        {"forwards": [{"recipients": ["张三"]}]}
    )
    assert "task_id" in err


def test_validate_empty_recipients():
    cf = _load()
    err = cf.OaCommunicateForwardPipeline._validate(
        {"forwards": [{"task_id": "t1", "recipients": []}]}
    )
    assert "recipients" in err


# ---------- _check_pending / _update_fwd ----------

class FakeResult:
    def __init__(self, row=None, rowcount=0):
        self._row = row
        self.rowcount = rowcount

    def fetchone(self):
        return self._row


class FakeDb:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.executed = []  # (sql, params)
        self.commits = 0

    async def execute(self, clause, params=None):
        self.executed.append((str(clause), params))
        return self.results.pop(0) if self.results else FakeResult()

    async def commit(self):
        self.commits += 1


class FakeCtx:
    def __init__(self, db):
        self.db = db
        self.execution_id = "test"


@pytest.mark.asyncio
async def test_check_pending_missing():
    cf = _load()
    ctx = FakeCtx(FakeDb([FakeResult(row=None)]))
    assert await cf.OaCommunicateForwardPipeline._check_pending(ctx, "t1") == "missing"


@pytest.mark.asyncio
async def test_check_pending_forwarded_by_flag():
    cf = _load()
    ctx = FakeCtx(FakeDb([FakeResult(row=(1, None))]))
    assert await cf.OaCommunicateForwardPipeline._check_pending(ctx, "t1") == "forwarded"


@pytest.mark.asyncio
async def test_check_pending_forwarded_by_time():
    cf = _load()
    ctx = FakeCtx(FakeDb([FakeResult(row=(0, datetime(2026, 7, 22)))]))
    assert await cf.OaCommunicateForwardPipeline._check_pending(ctx, "t1") == "forwarded"


@pytest.mark.asyncio
async def test_check_pending_pending():
    cf = _load()
    ctx = FakeCtx(FakeDb([FakeResult(row=(0, None))]))
    assert await cf.OaCommunicateForwardPipeline._check_pending(ctx, "t1") == "pending"


@pytest.mark.asyncio
async def test_update_fwd_atomic_sql_and_rowcount():
    cf = _load()
    db = FakeDb([FakeResult(row=(0, None)), FakeResult(rowcount=1)])
    ctx = FakeCtx(db)
    result = await cf.OaCommunicateForwardPipeline._update_fwd(ctx, "t1")
    assert result == "updated"
    update_sql, params = db.executed[1]
    assert "fwd = 1" in update_sql
    assert "forward_time" in update_sql
    assert "(fwd IS NULL OR fwd = 0)" in update_sql
    assert "forward_time IS NULL" in update_sql
    assert params["task_id"] == "t1"


@pytest.mark.asyncio
async def test_update_fwd_concurrent_lost():
    cf = _load()
    db = FakeDb([FakeResult(row=(0, None)), FakeResult(rowcount=0)])
    ctx = FakeCtx(db)
    assert await cf.OaCommunicateForwardPipeline._update_fwd(ctx, "t1") == "forwarded"


# ---------- execute 批量流程 ----------

class FakeLogger:
    def __init__(self):
        self.entries = []

    async def step(self, name, message, level="info", screenshot=None):
        self.entries.append((name, message, level))

    async def error(self, name, message):
        self.entries.append((name, message, "error"))


class FakeExecCtx:
    def __init__(self):
        self.logger = FakeLogger()
        self.db = FakeDb()
        self.settings = None
        self.minio = None
        self.execution_id = "test"


@asynccontextmanager
async def _fake_browser(config):
    yield object()


def _patch_browser_and_login(monkeypatch, cf, counters):
    monkeypatch.setattr(cf, "oa_browser", _fake_browser)

    async def fake_login(page, config):
        counters["login"] = counters.get("login", 0) + 1

    monkeypatch.setattr(cf, "oa_login", fake_login)


@pytest.mark.asyncio
async def test_execute_validation_failure_no_browser(monkeypatch):
    cf = _load()
    entered = []

    @asynccontextmanager
    async def tracking_browser(config):
        entered.append(1)
        yield object()

    monkeypatch.setattr(cf, "oa_browser", tracking_browser)
    pipeline = cf.OaCommunicateForwardPipeline()
    result = await pipeline.execute({"forwards": []}, FakeExecCtx())
    assert result.success is False
    assert entered == []


@pytest.mark.asyncio
async def test_execute_batch_isolation_and_per_item_commit(monkeypatch):
    cf = _load()
    counters = {}
    _patch_browser_and_login(monkeypatch, cf, counters)

    cls = cf.OaCommunicateForwardPipeline
    statuses = {"a": "pending", "b": "pending", "c": "forwarded"}
    monkeypatch.setattr(
        cls, "_check_pending", staticmethod(lambda ctx, tid: _async(statuses[tid]))
    )
    monkeypatch.setattr(cls, "_goto_forward", staticmethod(lambda *a: _async(None)))
    monkeypatch.setattr(cls, "_submit_and_verify", staticmethod(lambda *a: _async(None)))
    monkeypatch.setattr(cls, "_update_fwd", staticmethod(lambda *a: _async("updated")))

    async def fake_fill(self, page, item, config, ctx, step):
        if item["task_id"] == "b":
            raise RuntimeError("未找到: 某人")

    monkeypatch.setattr(cls, "_fill_form", fake_fill)

    ctx = FakeExecCtx()
    config = {
        "username": "u",
        "password": "p",
        "forwards": [
            {"task_id": "a", "recipients": ["张三"]},
            {"task_id": "b", "recipients": ["李四"]},
            {"task_id": "c", "recipients": ["王五"]},
        ],
    }
    result = await cls().execute(config, ctx)

    assert result.success is False  # b 失败
    s = result.summary
    assert s["total"] == 3
    assert s["forwarded"] == 1
    assert s["skipped"] == 1
    assert s["failed"] == 1
    assert s["errors"] == [{"task_id": "b", "error": "未找到: 某人"}]
    assert counters["login"] == 1          # 一次登录
    assert ctx.db.commits == 1             # 仅成功的 a 逐条 commit


async def _async(value):
    return value


@pytest.mark.asyncio
async def test_execute_login_failure_aborts(monkeypatch):
    cf = _load()
    monkeypatch.setattr(cf, "oa_browser", _fake_browser)

    from engine.pipelines.oa.shared.login import LoginError

    async def bad_login(page, config):
        raise LoginError("用户名或密码错误")

    monkeypatch.setattr(cf, "oa_login", bad_login)

    cls = cf.OaCommunicateForwardPipeline
    called = []
    monkeypatch.setattr(
        cls, "_goto_forward", staticmethod(lambda *a: called.append(1) or _async(None))
    )

    ctx = FakeExecCtx()
    config = {
        "username": "u",
        "password": "p",
        "forwards": [{"task_id": "a", "recipients": ["张三"]}],
    }
    result = await cls().execute(config, ctx)
    assert result.success is False
    assert "用户名或密码错误" in result.error
    assert called == []
```

注意：辅助函数 `_async` 定义在使用它的测试之后，Python 模块加载顺序无碍（调用发生在运行时）。若想更整洁可将其移到文件顶部 FakeResult 之前。

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/engine/tests/test_oa_forward.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.pipelines.oa.communicate_forward'`

- [ ] **Step 3: Write the implementation**

创建 `packages/engine/src/engine/pipelines/oa/communicate_forward.py`：

```python
"""OA 沟通批量转发 Pipeline — 共用一次登录，逐条转发并逐条回写 fwd=1。

迁移自 browser-agent/scripts_v3/oa_communicate_forward.py。
事务语义：每条 submit 成功后立即独立 commit（不依赖 runner 统一 commit），
保证进程崩溃/超时后 DB 状态与 OA 真实状态一致，杜绝重复转发。
"""

from __future__ import annotations

import time
from datetime import datetime

from playwright.async_api import Page
from sqlalchemy import text

from engine.base import BasePipeline, PipelineResult
from engine.context import ExecutionContext
from engine.pipelines.oa.shared.browser import oa_browser
from engine.pipelines.oa.shared.login import LoginError, LoginTimeout, oa_login
from engine.registry import register_pipeline

_OA_ORIGIN = "https://ioa.sd-port.net"
_FORWARD_PATH = (
    "/km/collaborate/km_collaborate_main/kmCollaborateMain.do"
    "?method=add&showForward=true&showid="
)
_SUCCESS_TEXT = "您的操作已成功"
_NO_RESULTS_TEXT = "未找到符合条件的记录"

# 接收者/抄送：输入 textarea 与隐藏 ids input
_FIELDS = {
    "participant": ("textarea.participantClass", "input[name=participantIds]"),
    "copy": ("textarea.copyPersonClass", "input[name=copyPersonIds]"),
}


@register_pipeline(
    name="oa.communicate_forward",
    display_name="OA 沟通批量转发",
    description="共用一次登录，按 forwards 列表逐条转发沟通待办并回写 fwd=1",
    trigger_modes=["api", "manual"],
    config_schema={
        "type": "object",
        "properties": {
            "login_url": {
                "type": "string",
                "default": "https://ioa.sd-port.net/login.jsp",
                "description": "OA 登录页地址",
            },
            "username": {"type": "string", "description": "OA 用户名"},
            "password": {"type": "string", "description": "OA 密码"},
            "forwards": {
                "type": "array",
                "description": "转发任务列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "待办 fdId"},
                        "recipients": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "接收者姓名列表",
                        },
                        "cc_recipients": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "抄送人姓名列表",
                        },
                        "title": {
                            "type": "string",
                            "description": "覆盖标题，缺省保留原标题",
                        },
                        "urgent": {
                            "type": "boolean",
                            "default": False,
                            "description": "是否紧急",
                        },
                    },
                    "required": ["task_id", "recipients"],
                },
            },
            "page_load_timeout": {
                "type": "integer",
                "default": 15000,
                "description": "页面加载超时(ms)",
            },
            "element_visible_timeout": {
                "type": "integer",
                "default": 5000,
                "description": "元素可见超时(ms)",
            },
            "action_settle_timeout": {
                "type": "integer",
                "default": 500,
                "description": "操作后稳定等待(ms)",
            },
        },
        "required": ["username", "password", "forwards"],
    },
)
class OaCommunicateForwardPipeline(BasePipeline):
    async def execute(self, config: dict, ctx: ExecutionContext) -> PipelineResult:
        # Apply defaults from config_schema
        config.setdefault("login_url", "https://ioa.sd-port.net/login.jsp")
        config.setdefault("page_load_timeout", 15000)
        config.setdefault("element_visible_timeout", 5000)
        config.setdefault("action_settle_timeout", 500)

        error = self._validate(config)
        if error:
            await ctx.logger.error("validate", error)
            return PipelineResult(success=False, error=error)

        forwards = config["forwards"]
        stats = {"total": len(forwards), "forwarded": 0, "skipped": 0, "failed": 0}
        errors: list[dict] = []

        async with oa_browser(config) as page:
            try:
                await ctx.logger.step("login", "登录 OA 系统")
                await oa_login(page, config)
            except (LoginError, LoginTimeout) as e:
                await ctx.logger.error("login", str(e))
                return PipelineResult(success=False, error=str(e))

            for item in forwards:
                task_id = item["task_id"]
                step = f"forward[{task_id}]"
                try:
                    status = await self._check_pending(ctx, task_id)
                    if status == "missing":
                        raise RuntimeError("DB 中不存在该 task_id（未采集？）")
                    if status == "forwarded":
                        stats["skipped"] += 1
                        await ctx.logger.step(step, "该记录已转发，跳过")
                        continue

                    await self._goto_forward(page, task_id, config)
                    await self._fill_form(page, item, config, ctx, step)
                    await self._submit_and_verify(page)
                    result = await self._update_fwd(ctx, task_id)
                    await ctx.db.commit()  # 逐条独立提交：崩溃也不丢 fwd=1
                    stats["forwarded"] += 1
                    await ctx.logger.step(step, f"转发成功 (db: {result})")
                except Exception as e:
                    stats["failed"] += 1
                    errors.append({"task_id": task_id, "error": str(e)})
                    screenshot = await self._safe_screenshot(page)
                    await ctx.logger.step(
                        step, f"转发失败: {e}", level="error", screenshot=screenshot
                    )

        summary = {**stats, "errors": errors}
        if stats["failed"] == 0:
            return PipelineResult(success=True, summary=summary)
        return PipelineResult(
            success=False,
            summary=summary,
            error=f"{stats['failed']}/{stats['total']} 条转发失败",
        )

    # ---------- 校验 ----------

    @staticmethod
    def _validate(config: dict) -> str | None:
        forwards = config.get("forwards")
        if not forwards or not isinstance(forwards, list):
            return "config.forwards 必须是非空数组"
        for i, item in enumerate(forwards):
            if not item.get("task_id"):
                return f"forwards[{i}].task_id 必填"
            recipients = item.get("recipients")
            if not recipients or not isinstance(recipients, list):
                return f"forwards[{i}].recipients 必须是非空数组"
        return None

    # ---------- DB（ctx.db 原始 SQL，engine 不 import backend） ----------

    @staticmethod
    async def _check_pending(ctx: ExecutionContext, task_id: str) -> str:
        """返回 'pending'（未转发）| 'forwarded' | 'missing'。实时查询，不预载。"""
        result = await ctx.db.execute(
            text("SELECT fwd, forward_time FROM inbox_documents WHERE task_id = :task_id"),
            {"task_id": task_id},
        )
        row = result.fetchone()
        if not row:
            return "missing"
        fwd, forward_time = row
        if fwd == 1 or forward_time is not None:
            return "forwarded"
        return "pending"

    @staticmethod
    async def _update_fwd(ctx: ExecutionContext, task_id: str) -> str:
        """原子回写 fwd=1, forward_time=NOW。返回 'updated'|'forwarded'|'missing'。"""
        status = await OaCommunicateForwardPipeline._check_pending(ctx, task_id)
        if status != "pending":
            return status
        result = await ctx.db.execute(
            text(
                "UPDATE inbox_documents SET fwd = 1, forward_time = :ts"
                " WHERE task_id = :task_id"
                " AND (fwd IS NULL OR fwd = 0) AND forward_time IS NULL"
            ),
            {"ts": datetime.now(), "task_id": task_id},
        )
        # WHERE 条件原子防重：并发重复执行时只有一方能写入
        return "updated" if result.rowcount > 0 else "forwarded"

    # ---------- 浏览器步骤（移植自 oa_forward_steps） ----------

    @staticmethod
    async def _goto_forward(page: Page, task_id: str, config: dict) -> None:
        url = f"{_OA_ORIGIN}{_FORWARD_PATH}{task_id}"
        await page.goto(url, wait_until="domcontentloaded")
        # docSubject 可见即表单就绪
        await page.locator("input[name=docSubject]").wait_for(
            state="visible", timeout=config["page_load_timeout"]
        )

    async def _fill_form(self, page: Page, item: dict, config: dict, ctx, step: str) -> None:
        # 标题：非空才覆盖，保留默认"转发:…"
        if item.get("title"):
            await page.locator("input[name=docSubject]").fill(item["title"])

        checkbox = page.locator("input[name=_fdIsPriority]")
        if item.get("urgent"):
            await checkbox.check()
        else:
            await checkbox.uncheck()

        for person in item["recipients"]:
            await self._pick_one(page, "participant", person)
            await ctx.logger.step(step, f"接收者: {person} ✓")
        for person in item.get("cc_recipients", []):
            await self._pick_one(page, "copy", person)
            await ctx.logger.step(step, f"抄送: {person} ✓")

    @staticmethod
    async def _pick_one(page: Page, field: str, person: str) -> None:
        ta_sel, ids_sel = _FIELDS[field]
        textarea = page.locator(ta_sel)
        ids_loc = page.locator(ids_sel)
        before_ids = await ids_loc.input_value()

        # 直接键入触发搜索。不可 fill("") 清空：会重置组件、丢失已选 chips
        await textarea.click()
        await textarea.type(person, delay=40)

        # 只认可见候选：另一字段残留的下拉 DOM 不可见，须排除
        items = page.locator(".mp_item.mp_selectable:visible")
        no_results = page.locator(".mp_no_results:visible")
        mp_list = page.locator(".mp_list:visible")

        deadline = time.time() + 5
        while time.time() < deadline:
            item_count = await items.count()
            no_res = await no_results.count() > 0
            if not no_res and await mp_list.count() > 0:
                no_res = _NO_RESULTS_TEXT in await mp_list.first.inner_text()
            if no_res and item_count == 0:
                raise RuntimeError(f"未找到: {person}")
            # 人名歧义禁止自动选，必须人工处理
            if item_count > 1:
                texts = [await items.nth(i).inner_text() for i in range(min(item_count, 5))]
                raise RuntimeError(f"候选项 {item_count} 条(>1), 禁止自动选: {texts}")
            if item_count == 1:
                break
            await page.wait_for_timeout(200)
        else:
            raise RuntimeError(f"等待候选项超时: {person}")

        await items.first.click()

        # 选中后隐藏 input 以分号追加新 ID，据此确认选中生效
        deadline = time.time() + 3
        while time.time() < deadline:
            if await ids_loc.input_value() != before_ids:
                return
            await page.wait_for_timeout(150)
        raise RuntimeError(f"选中后 ids 未变化: {person}")

    @staticmethod
    async def _submit_and_verify(page: Page) -> None:
        await page.get_by_role("cell", name="提交", exact=True).click()

        # 成功页约3s后自动关闭，需轮询所有标签页快速捕获
        deadline = time.time() + 5
        while time.time() < deadline:
            for p in page.context.pages:
                if not p.is_closed() and await p.get_by_text(_SUCCESS_TEXT).count() > 0:
                    return
            await page.wait_for_timeout(200)

        raise RuntimeError("提交后未检测到成功文案（5s超时）")

    @staticmethod
    async def _safe_screenshot(page: Page) -> bytes | None:
        try:
            return await page.screenshot()
        except Exception:
            return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/engine/tests/test_oa_forward.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add packages/engine/src/engine/pipelines/oa/communicate_forward.py \
        packages/engine/tests/test_oa_forward.py
git commit -m "feat: add oa.communicate_forward pipeline with batch forward and per-item commit"
```

---

### Task 4: 全量回归 + 注册验证

**Files:**
- 无新增/修改（仅验证）

**Interfaces:**
- Consumes: 全部前序任务

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: 全部 PASS（engine + backend，包括 test_oa_pipeline_registration.py、test_runner*.py、test_scheduler*.py 无回归）

- [ ] **Step 2: 验证双 pipeline 可发现**

Run:

```bash
uv run python -c "
from engine.registry import PipelineRegistry
PipelineRegistry.discover()
for name, cls in sorted(PipelineRegistry.all().items()):
    print(name, '|', cls.metadata.display_name, '|', cls.metadata.trigger_modes)
"
```

Expected 输出包含两行（顺序按名字排序）：

```
oa.communicate_forward | OA 沟通批量转发 | ['api', 'manual']
oa.communicate_todos | OA 沟通待办采集 | ['cron', 'api', 'manual']
```

（`example_pipeline` 若存在也会出现，属正常。）

- [ ] **Step 3: 更新 spec 状态**

将 `docs/specs/5.2026-07-22-OA沟通转发Pipeline设计.md` 首部 `- 状态：已确认` 改为 `- 状态：已实施`。

- [ ] **Step 4: Commit**

```bash
git add docs/specs/5.2026-07-22-OA沟通转发Pipeline设计.md
git commit -m "docs: mark OA forward pipeline spec as implemented"
```

---

## Self-Review 记录

- **Spec 覆盖**：spec §3 文件结构→Task 1/2/3；§4 oa_browser→Task 1；§5 注册/config_schema→Task 3；§6 执行流程（含 6.1 逐条 commit、6.2 实时 SELECT）→Task 3 实现与测试；§7 存储/logger 对接→Task 3；§8 错误处理→Task 3 测试（validation/no-browser、login abort、batch isolation）；§9 测试→各 Task Step 1；§10 工作区→Global Constraints。
- **类型一致性**：`oa_browser(config: dict) -> AsyncIterator[Page]` 在 Task 1 定义、Task 2/3 消费一致；`_check_pending/_update_fwd` 静态方法签名在测试与实现中一致；`ctx.logger.step(name, message, level=..., screenshot=...)` 与 backend `DbStepLogger.step` 签名一致。
- **Placeholder 扫描**：无 TBD/TODO；所有代码步骤含完整代码。
