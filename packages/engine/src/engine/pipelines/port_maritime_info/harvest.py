"""港航信息采集 pipeline — 采集 → 去重 → 粗筛 → 入库 → 详情流式 → 清理。

信源选择器配置见 sources.json；LLM prompt 见 prompts/。
产出写入 ganghang_materials 表，供《港航信息》月刊编撰选用。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from engine.base import BasePipeline, PipelineResult
from engine.context import ExecutionContext
from engine.pipelines.shared.browser import managed_browser
from engine.pipelines.shared.llm import LlmClient
from engine.pipelines.shared.sync_log import SyncLog
from engine.registry import register_pipeline

from . import collect, materials, screen
from .detail import detail_pipeline

_SOURCES_FILE = Path(__file__).parent / "sources.json"


def _source_names() -> list[str]:
    """信源名称清单（供 config_schema enum；单一事实源为 sources.json）。"""
    data = json.loads(_SOURCES_FILE.read_text(encoding="utf-8"))
    return [s["source_name"] for s in data.get("sources", [])]


def _recap(outcomes: list[dict]) -> str:
    """阶段归纳：细筛逐条决策（标题 + 结论 + 链接）。

    粗筛通过者全部进入细筛 outcomes，不再单列粗筛段。
    与 detail 逐条日志关注点错开——那里是过程（耗时/单条上下文），
    这里只留结论。标题截断 40 字符保持扫描对齐。
    """
    def _t(o: dict) -> str:
        return o.get("title", "")[:40]

    passed = [o for o in outcomes if o["decision"] == "pass"]
    rejected = [o for o in outcomes if o["decision"] == "reject"]
    kept = [o for o in outcomes if o["decision"] == "kept"]
    failed = [o for o in outcomes if o["decision"] == "failed"]

    lines = [
        "阶段归纳:",
        f"{len(passed)} 通过 / {len(rejected)} 拒绝 / "
        f"{len(kept)} 保留历史 / {len(failed)} 失败:",
    ]

    def _append(icon: str, conclusion: str, o: dict) -> None:
        lines.append(f"  {icon} {_t(o)}  {conclusion}")
        lines.append(f"    链接: {o.get('url', '')}")

    for o in passed:
        _append("✅", f"[{o.get('category', '')}] 评分 {o.get('score', '')}", o)
    for o in rejected:
        _append("❌", f"— {o.get('reason', '')}", o)
    for o in kept:
        _append("⊘", f"— {o.get('reason', '')}（保留历史行）", o)
    for o in failed:
        _append("⚠", f"— {o.get('reason', '')}", o)
    return "\n".join(lines)


@register_pipeline(
    name="port_maritime_info.harvest",
    display_name="港航信息采集",
    description=(
        "采集港航资讯信源（交通运输部、中央人民政府等），"
        "经 LLM 粗筛/细筛后写入 ganghang_materials 表，"
        "供《港航信息》月刊编撰选用"
    ),
    trigger_modes=["cron", "api", "manual"],
    version="1.0.0",
    config_schema={
        "type": "object",
        "properties": {
            # x-order：展示顺序（MySQL JSON 列会重排 key，声明顺序不可靠，
            # 前端 SchemaFields 按 x-order 排序）
            "sources": {
                "type": "array",
                "items": {"type": "string", "enum": _source_names()},
                "x-order": 1,
                "x-empty-means-all": "全部信源（后续新增自动纳入）",
                "description": "信源选择：不选 = 全部已接入信源；勾选后仅采集所选（补录/重录建议显式指定）",
            },
            "start_date": {
                "type": "string",
                "format": "date",
                "x-order": 2,
                "x-range-group": "period",
                "x-range-part": "start",
                "x-range-label": "编撰周期",
                "x-allow-relative": True,
                "description": "编撰周期起始（YYYY-MM-DD，或相对表达式 today / today-N，定时任务按执行日滚动解析）",
            },
            "end_date": {
                "type": "string",
                "format": "date",
                "x-order": 3,
                "x-range-group": "period",
                "x-range-part": "end",
                "x-allow-relative": True,
                "description": "编撰周期结束（YYYY-MM-DD，或相对表达式 today / today-N）",
            },
            "force": {
                "type": "boolean",
                "default": False,
                "x-order": 4,
                "description": "强制模式：跳过 DB 去重，重采已有数据",
            },
            "preference": {
                "type": "string",
                "default": "",
                "x-order": 5,
                "description": "额外关注偏好（如'国际油价动态'），空为无",
            },
            "browser_tabs": {
                "type": "integer",
                "default": 5,
                "x-order": 6,
                "description": "浏览器并发 tab 数（1~5）",
            },
            "llm_concurrency": {
                "type": "integer",
                "default": 5,
                "x-order": 7,
                "description": "LLM 并发请求数上限",
            },
            "max_pages": {
                "type": "integer",
                "default": 50,
                "x-order": 8,
                "description": "单 entry 最大翻页数",
            },
            "max_tokens": {
                "type": "integer",
                "default": 16384,
                "x-order": 9,
                "description": "LLM 单次最大输出 token 数",
            },
            "temperature": {
                "type": "number",
                "default": 0.0,
                "x-order": 10,
                "description": "LLM 采样温度（筛选判定任务取 0 最稳定，消除采样漂移）",
            },
        },
        "required": ["start_date", "end_date"],
    },
)
class PortMaritimeInfoHarvestPipeline(BasePipeline):
    """港航信息采集：列表采集 → DB 去重 → LLM 粗筛 → 入库 → 详情流式（fetch+细筛+写入）。"""

    @classmethod
    def validate_config(cls, config: dict) -> str | None:
        """触发边界预校验：sources 省略=全部，空数组非法，显式名单须在已接入信源内。

        空数组拒绝（而非视作全部）：过滤语义中 [] 通识为空集，且动态拼装
        调用方上游出 bug 时恰好得到空数组，静默展开为全量采集是最坏失败
        模式——fail-fast 并引导正确写法（省略字段）。

        注意：相对表达式在此按调用时刻解析仅为校验可行性；真实窗口仍以
        execute 时刻解析为准（cron 滚动语义不受影响）。
        """
        sources = config.get("sources")
        if sources is not None and not sources:
            return "sources 为空数组：省略该字段即表示采集全部信源，或列出具体信源名"
        if sources:
            available = _source_names()
            unknown = [s for s in sources if s not in available]
            if unknown:
                return f"未接入信源: {unknown}，可用: {available}（或省略 sources 表示全部）"
        start_date = collect.resolve_date_expr(config.get("start_date", ""))
        end_date = collect.resolve_date_expr(config.get("end_date", ""))
        if not start_date or not end_date:
            return "缺少必填参数 start_date/end_date"
        try:
            collect._validate_dates(start_date, end_date)
        except ValueError as e:
            return str(e)
        return None

    async def execute(self, config: dict, ctx: ExecutionContext) -> PipelineResult:
        log = SyncLog(ctx.logger)

        # ── 入参校验（与边界预校验同一入口，执行时刻再验为最后防线） ──
        if err := self.validate_config(config):
            return PipelineResult(success=False, error=err)
        # 相对日期表达式（today / today-N）在执行时刻解析为真实日期；
        # config 保留表达式原样（执行记录可见调度意图），解析值进 stats["period"]
        start_date = collect.resolve_date_expr(config.get("start_date", ""))
        end_date = collect.resolve_date_expr(config.get("end_date", ""))
        source_names = config.get("sources") or []

        # ── 耦合运行配置（默认值；runner 三级链已注入 headless/page_load_timeout 等） ──
        config.setdefault("headless", True)
        config.setdefault("close_browser", True)
        # 政府站点响应慢，runner 全局默认 15s 对本 pipeline 偏低，抬下限
        config["page_load_timeout"] = max(
            int(config.get("page_load_timeout", 120000)), 60000
        )
        config.setdefault("browser_tabs", 5)
        config.setdefault("llm_concurrency", 5)
        config.setdefault("max_pages", 50)
        config.setdefault("rate_limit_ms", 2000)
        config.setdefault("coarse_batch_size", 20)
        config.setdefault("retry_max", 2)
        config.setdefault("min_content_chars", 100)
        config.setdefault("max_content_chars", 15000)
        config.setdefault("temperature", 0.0)
        config.setdefault("max_tokens", 16384)
        config.setdefault("enable_thinking", False)

        force = bool(config.get("force", False))
        preference = config.get("preference", "")

        # ── 信源选择（sources 省略 = 全部：定时任务免维护，新增信源自动纳入；
        #    空数组已被 validate_config 拦截，到此处 None 才展开） ──
        sources_data = json.loads(_SOURCES_FILE.read_text(encoding="utf-8"))
        available = [
            s.get("source_name") for s in sources_data.get("sources", [])
        ]
        if not source_names:
            source_names = available
        selected = [
            s for s in sources_data.get("sources", [])
            if s.get("source_name") in source_names
        ]
        if not selected:
            return PipelineResult(
                success=False,
                error=f"未找到信源: {source_names}，可用: {available}",
            )

        await log.info(
            "summary",
            f"信源: {[s['source_name'] for s in selected]} | "
            f"周期: {start_date} ~ {end_date}"
            + (" | 强制模式" if force else "")
            + (f" | 偏好: {preference}" if preference else ""),
        )

        stats: dict = {"period": [start_date, end_date]}
        timings: dict[str, float] = {}
        t_start = time.monotonic()

        llm = LlmClient(ctx.settings, config)
        session = ctx.db
        try:
            async with managed_browser(config) as page:
                # 列表采集
                t0 = time.monotonic()
                items = await collect.crawl_list(
                    page, selected, start_date, end_date, config, log
                )
                timings["列表采集"] = time.monotonic() - t0
                stats["crawled"] = len(items)

                if not items:
                    await log.warn("summary", "未采集到条目，结束")
                    return PipelineResult(success=True, summary=stats)

                # DB 去重（force=true 时跳过）
                t0 = time.monotonic()
                if force:
                    new_items = items
                    await log.info("dedup", f"强制模式，跳过去重: {len(items)} 条")
                else:
                    urls = [it["link_url"] for it in items if it.get("link_url")]
                    async with log.lock:
                        existing = await materials.find_existing_urls(session, urls)
                        await session.commit()
                    new_items = [
                        it for it in items
                        if it.get("link_url") and it["link_url"] not in existing
                    ]
                    await log.info(
                        "dedup", f"DB 已有: {len(existing)}, 新增: {len(new_items)}"
                    )
                timings["去重"] = time.monotonic() - t0
                stats["new"] = len(new_items)

                if not new_items:
                    await log.info("summary", "无新增条目，结束")
                    return PipelineResult(success=True, summary=stats)

                # LLM 粗筛
                t0 = time.monotonic()
                coarse_items = await screen.coarse_screen(
                    new_items, config, start_date, end_date, preference, llm, log
                )
                timings["粗筛"] = time.monotonic() - t0
                stats["coarse_passed"] = len(coarse_items)

                if not coarse_items:
                    await log.warn("summary", "粗筛无通过条目，结束")
                    return PipelineResult(success=True, summary=stats)

                # 入库基础行
                t0 = time.monotonic()
                async with log.lock:
                    await materials.insert_basic(
                        session, coarse_items, ctx.execution_id
                    )
                    await session.commit()
                timings["入库"] = time.monotonic() - t0
                # inserted_ids 供 cleanup_unprocessed 清理未处理空行，必须保持全量
                # （新行 + force 复用行），不随下方 stats 展示口径拆分
                inserted_ids = [
                    it["db_id"] for it in coarse_items if it.get("db_id")
                ]
                # 展示口径：inserted=真新增，reused=force 复用旧行（非 force 恒 0）
                stats["inserted"] = sum(
                    1 for it in coarse_items
                    if it.get("db_id") and it.get("is_new", True)
                )
                stats["reused"] = sum(
                    1 for it in coarse_items
                    if it.get("db_id") and not it.get("is_new", True)
                )
                await log.info(
                    "insert",
                    f"INSERT: 新增 {stats['inserted']} / 复用 {stats['reused']}"
                    f"（共 {len(inserted_ids)}/{len(coarse_items)} 条）",
                )

                no_id = [it for it in coarse_items if not it.get("db_id")]
                if no_id:
                    await log.warn(
                        "insert", f"{len(no_id)} 条未获得 db_id，跳过"
                    )

                de_items = [it for it in coarse_items if it.get("db_id")]
                if not de_items:
                    await log.warn("summary", "无有效 db_id 的条目，结束")
                    return PipelineResult(success=True, summary=stats)

                # 详情流式（fetch → 细筛 → 写入）
                fine_prompt = screen.load_fine_prompt(start_date, end_date, preference)
                try:
                    t0 = time.monotonic()
                    de_stats = await detail_pipeline(
                        de_items, selected, config, page, fine_prompt,
                        session, llm, log,
                    )
                    timings["详情流式"] = time.monotonic() - t0
                    stats["passed"] = de_stats["passed"]
                    stats["rejected"] = de_stats["rejected"]
                    stats["kept_existing"] = de_stats["kept_existing"]
                    stats["failed"] = de_stats["failed"]
                    # 留存清单：result_summary.outcomes 只收录运行后仍存在
                    # 于素材表的行（pass=本次写入/更新，kept=force 保留历史行）；
                    # reject/failed 行已删除，全量逐条决策见执行日志「阶段归纳」
                    stats["outcomes"] = [
                        o for o in de_stats.get("outcomes", [])
                        if o["decision"] in ("pass", "kept")
                    ]
                    await log.info(
                        "summary",
                        _recap(de_stats.get("outcomes", [])),
                    )
                finally:
                    # 清理未处理行（异常中断也必须执行，防残留空行）
                    if inserted_ids:
                        async with log.lock:
                            removed = await materials.cleanup_unprocessed(
                                session, inserted_ids
                            )
                            await session.commit()
                            if removed:
                                await log.raw.step(
                                    "cleanup",
                                    f"CLEANUP: {removed} 条未处理行已删除",
                                    "warn",
                                )

        except Exception as e:
            await log.error("summary", f"执行异常: {e}")
            return PipelineResult(success=False, error=str(e), summary=stats)
        finally:
            await llm.close()

        stats["total_seconds"] = round(time.monotonic() - t_start, 1)
        stats["timings"] = {k: round(v, 1) for k, v in timings.items()}
        await log.info(
            "summary",
            f"完成: 采集 {stats.get('crawled', 0)} → 新增 {stats.get('new', 0)} → "
            f"粗筛 {stats.get('coarse_passed', 0)} → "
            f"入库 {stats.get('inserted', 0)} / 复用 {stats.get('reused', 0)} → "
            f"通过 {stats.get('passed', 0)} / 拒绝 {stats.get('rejected', 0)} / "
            f"保留 {stats.get('kept_existing', 0)} / 失败 {stats.get('failed', 0)} | "
            f"总计 {stats['total_seconds']}s",
            data={"timings": stats["timings"]},
        )
        return PipelineResult(success=True, summary=stats)
