from contextlib import asynccontextmanager
from datetime import datetime, timezone

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
async def test_check_pending_skipped_only_when_fwd_two():
    """仅 fwd=2 跳过（幂等键，2026-07-28 修订）。"""
    cf = _load()
    ctx = FakeCtx(FakeDb([FakeResult(row=(2,))]))
    assert await cf.OaCommunicateForwardPipeline._check_pending(ctx, "t1") == "skipped"


@pytest.mark.asyncio
async def test_check_pending_fwd_zero_executes():
    cf = _load()
    ctx = FakeCtx(FakeDb([FakeResult(row=(0,))]))
    assert await cf.OaCommunicateForwardPipeline._check_pending(ctx, "t1") == "pending"


@pytest.mark.asyncio
async def test_check_pending_fwd_one_executes():
    """fwd=1（历史已转发值）不豁免，照常执行，成功后覆盖为 2。"""
    cf = _load()
    ctx = FakeCtx(FakeDb([FakeResult(row=(1,))]))
    assert await cf.OaCommunicateForwardPipeline._check_pending(ctx, "t1") == "pending"


@pytest.mark.asyncio
async def test_check_pending_fwd_null_executes():
    cf = _load()
    ctx = FakeCtx(FakeDb([FakeResult(row=(None,))]))
    assert await cf.OaCommunicateForwardPipeline._check_pending(ctx, "t1") == "pending"


@pytest.mark.asyncio
async def test_update_fwd_sql_and_rowcount():
    """2026-07-28 修订：无守卫条件，直接 SET fwd = 2 按 task_id 更新，无前置 SELECT。"""
    cf = _load()
    db = FakeDb([FakeResult(rowcount=1)])
    ctx = FakeCtx(db)
    result = await cf.OaCommunicateForwardPipeline._update_fwd(ctx, "t1")
    assert result == "updated"
    assert len(db.executed) == 1  # 仅一条 UPDATE，不再前置 SELECT
    update_sql, params = db.executed[0]
    assert "fwd = 2" in update_sql
    assert "forward_time" in update_sql
    assert "fwd IS NULL" not in update_sql
    assert "forward_time IS NULL" not in update_sql
    assert params["task_id"] == "t1"


@pytest.mark.asyncio
async def test_update_fwd_timestamp_is_utc():
    """forward_time 必须写 UTC 值，与 backend UTCDateTime（读回按 UTC 解释）对齐。"""
    cf = _load()
    db = FakeDb([FakeResult(rowcount=1)])
    ctx = FakeCtx(db)
    await cf.OaCommunicateForwardPipeline._update_fwd(ctx, "t1")
    ts = db.executed[0][1]["ts"]
    utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
    assert abs((utc_now - ts).total_seconds()) < 60


@pytest.mark.asyncio
async def test_update_fwd_missing():
    """task_id 不存在时 rowcount=0 → 'missing'。"""
    cf = _load()
    db = FakeDb([FakeResult(rowcount=0)])
    ctx = FakeCtx(db)
    assert await cf.OaCommunicateForwardPipeline._update_fwd(ctx, "t1") == "missing"


# ---------- execute 批量流程 ----------

class FakeLogger:
    def __init__(self):
        self.entries = []

    async def step(self, name, message, level="info"):
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
    # 仅 fwd=2 跳过：a 执行、b 执行（填表失败）、c 跳过
    statuses = {"a": "pending", "b": "pending", "c": "skipped"}
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
    assert s["forwarded"] == 1      # 仅 a 成功
    assert s["skipped"] == 1        # c（fwd=2）跳过
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
