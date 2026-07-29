"""OA 沟通批量转发 Pipeline — 共用一次登录，逐条转发并逐条回写 fwd=2。

迁移自 browser-agent/scripts_v3/oa_communicate_forward.py。
事务语义：每条 submit 成功后立即独立 commit（不依赖 runner 统一 commit），
保证进程崩溃/超时后 DB 状态与 OA 真实状态一致。
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from playwright.async_api import Error as PlaywrightError, Page
from sqlalchemy import text

from engine.base import BasePipeline, PipelineResult
from engine.context import ExecutionContext
from engine.pipelines.oa.shared.browser import oa_browser
from engine.pipelines.oa.shared.login import LoginError, LoginTimeout, oa_login
from engine.registry import register_pipeline
from engine.table_names import resolve_table

_INBOX_TABLE = resolve_table("inbox_documents", "inbox_documents")

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
    description="共用一次登录，按 forwards 列表逐条转发沟通待办并回写 fwd=2",
    trigger_modes=["api", "manual"],
    version="1.0.0",
    config_schema={
        "type": "object",
        "properties": {
            "username": {"type": "string", "description": "OA 用户名"},
            "password": {"type": "string", "format": "password", "description": "OA 密码"},
            "login_url": {
                "type": "string",
                "default": "https://ioa.sd-port.net/login.jsp",
                "description": "OA 登录页地址",
            },
            "forwards": {
                "type": "array",
                "description": "转发任务列表",
                "default": [
                    {
                        "task_id": "19f7fa590e4d644a234b8264566b1ca7",
                        "recipients": ["测试用账号3"],
                        "cc_recipients": ["测试用账号9", "测试用账号10"],
                        "title": None,
                        "urgent": False,
                    }
                ],
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
                            "description": "覆盖标题；null 或缺省 = 保留原标题；空字符串 = 显式清空标题",
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
        },
        "required": ["username", "password", "forwards"],
    },
)
class OaCommunicateForwardPipeline(BasePipeline):
    async def execute(self, config: dict, ctx: ExecutionContext) -> PipelineResult:
        # Apply defaults from config_schema
        config.setdefault("login_url", "https://ioa.sd-port.net/login.jsp")
        # 运行设置类参数由 runner 三级覆盖链注入（系统设置打底）；setdefault 仅作直连兜底
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
                await ctx.logger.step("login", "登录成功，已进入门户页")
            except (LoginError, LoginTimeout) as e:
                await ctx.logger.error("login", str(e))
                return PipelineResult(success=False, error=str(e))

            await ctx.logger.step("prepare", f"共 {len(forwards)} 条转发任务，逐条处理")

            for idx, item in enumerate(forwards, start=1):
                task_id = item["task_id"]
                step = f"forward[{task_id[:8]}]"
                progress = f"第 {idx}/{len(forwards)} 条"
                try:
                    status = await self._check_pending(ctx, task_id)
                    if status == "missing":
                        raise RuntimeError("DB 中不存在该 task_id（未采集？）")
                    if status == "skipped":
                        stats["skipped"] += 1
                        await ctx.logger.step(step, f"{progress}：该记录已转发（fwd=2），跳过")
                        continue

                    await self._goto_forward(page, task_id, config)
                    await ctx.logger.step(step, f"{progress}：已打开转发页，开始填写表单")
                    await self._fill_form(page, item, config, ctx, step)
                    await self._submit_and_verify(page)
                    await ctx.logger.step(step, f"{progress}：已提交，检测到成功文案")
                    result = await self._update_fwd(ctx, task_id)
                    await ctx.db.commit()  # 逐条独立提交：崩溃也不丢 fwd=2
                    stats["forwarded"] += 1
                    await ctx.logger.step(step, f"{progress}：转发成功 (db: {result})")
                except Exception as e:
                    stats["failed"] += 1
                    errors.append({"task_id": task_id, "error": str(e)})
                    await ctx.logger.step(
                        step, f"{progress}：转发失败: {e}", level="error"
                    )

            await ctx.logger.step(
                "summary",
                f"转发完成：成功 {stats['forwarded']} 条，跳过 {stats['skipped']} 条，"
                f"失败 {stats['failed']} 条",
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
        """返回 'pending'（可执行）| 'skipped'（fwd=2 已转发）| 'missing'。实时查询，不预载。

        幂等键仅为 fwd=2（本平台回写值，2026-07-28 修订）：fwd 为 0/1/NULL 均照常执行，
        执行成功后由 _update_fwd 覆盖为 2。
        """
        result = await ctx.db.execute(
            text(f"SELECT fwd FROM {_INBOX_TABLE} WHERE task_id = :task_id"),
            {"task_id": task_id},
        )
        row = result.fetchone()
        if not row:
            return "missing"
        return "skipped" if row[0] == 2 else "pending"

    @staticmethod
    async def _update_fwd(ctx: ExecutionContext, task_id: str) -> str:
        """回写 fwd=2, forward_time=NOW。无守卫条件，直接按 task_id 更新
        （2026-07-28 修订：不再校验 fwd 当前是 0 还是 1）。返回 'updated'|'missing'。"""
        result = await ctx.db.execute(
            text(
                f"UPDATE {_INBOX_TABLE} SET fwd = 2, forward_time = :ts"
                " WHERE task_id = :task_id"
            ),
            # 原始 SQL 不经过 UTCDateTime.bind，需自行写 UTC-naive 值
            {"ts": datetime.now(timezone.utc).replace(tzinfo=None), "task_id": task_id},
        )
        return "updated" if result.rowcount > 0 else "missing"

    # ---------- 浏览器步骤（移植自 oa_forward_steps） ----------

    @staticmethod
    async def _raise_on_oa_error_page(page: Page) -> None:
        """OA prompt 错误页检测：.errortitle（操作失败！）存在即抛错，附带 .errorlist 明细。

        无效 showid（文档已删除/ID 错误）、表单校验失败等场景 OA 渲染错误页而非
        目标表单。快速失败并上报真实原因，避免空等元素超时（15s）且报错信息晦涩。
        """
        errortitle = page.locator(".errortitle")
        if await errortitle.count() == 0:
            return
        messages = [
            m.strip()
            for m in await page.locator(".errorlist").all_inner_texts()
            if m.strip()
        ]
        if not messages:
            title_text = (await errortitle.first.inner_text()).strip()
            messages = [title_text] if title_text else ["未知错误"]
        raise RuntimeError(f"OA 返回错误页：{'; '.join(messages)}")

    @staticmethod
    async def _goto_forward(page: Page, task_id: str, config: dict) -> None:
        url = f"{_OA_ORIGIN}{_FORWARD_PATH}{task_id}"
        await page.goto(url, wait_until="domcontentloaded")
        await OaCommunicateForwardPipeline._raise_on_oa_error_page(page)
        # docSubject 可见即表单就绪
        await page.locator("input[name=docSubject]").wait_for(
            state="visible", timeout=config["page_load_timeout"]
        )
        # 表单动态脚本稳定后再填写
        await page.wait_for_timeout(config["action_settle_timeout"])

    async def _fill_form(self, page: Page, item: dict, config: dict, ctx, step: str) -> None:
        # 标题三态语义（spec 5 §6）：null/缺省 = 保留原标题；空字符串 = 显式清空；非空 = 覆盖
        title = item.get("title")
        if title is None:
            await ctx.logger.step(step, "标题：保留原标题")
        else:
            await page.locator("input[name=docSubject]").fill(title)
            await ctx.logger.step(step, "标题：显式清空" if title == "" else f"标题：覆盖为「{title}」")

        checkbox = page.locator("input[name=_fdIsPriority]")
        if item.get("urgent"):
            await checkbox.check()
        else:
            await checkbox.uncheck()
        await ctx.logger.step(step, f"紧急标记：{'是' if item.get('urgent') else '否'}")

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

        # 成功页约3s后自动关闭，需轮询所有标签页快速捕获；
        # 提交校验失败时 OA 渲染 prompt 错误页，同样需快速识别
        deadline = time.time() + 5
        while time.time() < deadline:
            for p in page.context.pages:
                if p.is_closed():
                    continue
                try:
                    if await p.get_by_text(_SUCCESS_TEXT).count() > 0:
                        return
                    await OaCommunicateForwardPipeline._raise_on_oa_error_page(p)
                except PlaywrightError:
                    continue  # 探测间隙页面关闭/导航（成功页自动关闭），下轮重试
            await page.wait_for_timeout(200)

        raise RuntimeError("提交后未检测到成功文案（5s超时）")
