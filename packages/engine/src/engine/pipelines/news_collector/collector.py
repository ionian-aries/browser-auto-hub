"""NewsCollectorPipeline — 7 Phase 主编排（spec §6）

Phase 1: 信源遍历 & Config 解析 (load config from file, resolve inheritance)
Phase 2: 翻页采集 (crawl pages with pagination)
Phase 3: URL 去重 (internal + DB dedup)
Phase 4: 粗筛 (batch LLM screening)
Phase 5: 正文提取 (detail page extraction, with explorer fallback)
Phase 6: 细筛 (per-article LLM scoring, semaphore concurrency)
Phase 7: 入库 + 统计报告 (INSERT IGNORE + stats summary)
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from playwright.async_api import Page, async_playwright
from sqlalchemy import text

from engine.base import BasePipeline, PipelineResult
from engine.context import ExecutionContext
from engine.registry import register_pipeline

from .config_schema import resolve_config
from .config_store import load_config_by_base_url
from .crawler import go_next_page, try_extract_detail, try_extract_items
from .explorer import explore_detail, explore_list
from .screener import coarse_screen, fine_screen

# ── 默认参数 ──
_DEFAULT_RATE_LIMIT_MS = 2000
_DEFAULT_SOURCE_SWITCH_MS = 5000
_DEFAULT_MAX_PAGES = 50
_DEFAULT_COARSE_BATCH = 20
_DEFAULT_FINE_CONCURRENCY = 3
_DEFAULT_EXPLORE_RETRIES = 3


# ── 浏览器生命周期 ──
def _consume_close_exception(task: asyncio.Task) -> None:
    """取回后台 close 的异常，避免 'exception was never retrieved' 噪音。"""
    if not task.cancelled():
        task.exception()


@asynccontextmanager
async def _news_browser(config: dict) -> AsyncIterator[Page]:
    """Launch Chromium, yield a page, shielded close — 对齐 OA pipeline 模式。"""
    headless = config.get("headless", True)
    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch(headless=headless)
        try:
            context = await browser.new_context()
            page = await context.new_page()
            yield page
        finally:
            close_task = asyncio.ensure_future(browser.close())
            close_task.add_done_callback(_consume_close_exception)
            try:
                await asyncio.shield(close_task)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
    finally:
        try:
            await pw.stop()
        except Exception:
            pass


# ── 工具函数 ──
async def _rate_limit(ms: int) -> None:
    """请求限速。"""
    await asyncio.sleep(ms / 1000)


async def _dedup_urls(db: Any, items: list[dict]) -> list[dict]:
    """URL 去重：内部去重 + DB 去重。"""
    # 内部去重（保序）
    seen: dict[str, dict] = {}
    for it in items:
        url = it.get("url", "")
        if url and url not in seen:
            seen[url] = it
    unique = list(seen.values())

    if not unique:
        return []

    # DB 去重（分批查询，MySQL IN 限制）
    urls = [it["url"] for it in unique]
    existing_urls: set[str] = set()
    for i in range(0, len(urls), 500):
        batch = urls[i : i + 500]
        placeholders = ", ".join(f":u{j}" for j in range(len(batch)))
        params = {f"u{j}": u for j, u in enumerate(batch)}
        try:
            result = await db.execute(
                text(
                    f"SELECT link_url FROM ganghang_materials "
                    f"WHERE link_url IN ({placeholders})"
                ),
                params,
            )
            for row in result.fetchall():
                existing_urls.add(row[0])
        except Exception:
            pass  # DB 查询失败 → 保守不过滤

    return [it for it in unique if it["url"] not in existing_urls]


async def _insert_documents(db: Any, docs: list[dict]) -> int:
    """批量 INSERT IGNORE INTO ganghang_materials。返回实际插入数。"""
    inserted = 0
    for doc in docs:
        try:
            await db.execute(
                text(
                    "INSERT IGNORE INTO ganghang_materials "
                    "(category, title, content, digest, insight, "
                    "link_url, doc_date, website_name, score, score_reason) "
                    "VALUES (:category, :title, :content, :digest, :insight, "
                    ":link_url, :doc_date, :website_name, :score, :score_reason)"
                ),
                doc,
            )
            inserted += 1
        except Exception:
            pass
    try:
        await db.commit()
    except Exception:
        pass
    return inserted


# ── 7 Phase 主流程 ──
async def _run_pipeline(config: dict, ctx: ExecutionContext) -> PipelineResult:
    """7 Phase 主编排。"""
    stats: dict[str, Any] = {
        "sources_total": 0,
        "entries_total": 0,
        "entries_skipped": 0,
        "items_crawled": 0,
        "items_after_dedup": 0,
        "items_coarse_pass": 0,
        "items_coarse_reject": 0,
        "items_fine_pass": 0,
        "items_fine_reject": 0,
        "items_inserted": 0,
        "explore_triggered": 0,
        "explore_success": 0,
        "explore_failed": 0,
        "categories": {},
    }

    sources = config.get("sources", [])
    start_date = config.get("start_date", "2026-01-01")
    end_date = config.get("end_date", "2026-12-31")
    preference = config.get("preference")
    rate_limit_ms = config.get("rate_limit_ms", _DEFAULT_RATE_LIMIT_MS)
    source_switch_ms = config.get(
        "source_switch_delay_ms", _DEFAULT_SOURCE_SWITCH_MS
    )
    max_pages = config.get("max_pages", _DEFAULT_MAX_PAGES)
    coarse_batch = config.get("coarse_batch_size", _DEFAULT_COARSE_BATCH)
    fine_concurrency = config.get("fine_concurrency", _DEFAULT_FINE_CONCURRENCY)
    explore_retries = config.get("explore_max_retries", _DEFAULT_EXPLORE_RETRIES)
    headless = config.get("headless", True)

    stats["sources_total"] = len(sources)

    # ── Phase 1 & 2: 信源遍历 + 翻页采集 ──
    all_items: list[dict] = []

    async with _news_browser({"headless": headless}) as page:
        for src_idx, source in enumerate(sources):
            source_name = source.get("name", "未知信源")
            base_url = source.get("base_url", "")
            entries = source.get("entries", [])

            await ctx.logger.step(
                "phase1", f"信源: {source_name} ({len(entries)} 个入口)"
            )

            # 加载信源 config（文件存储）
            db_config = load_config_by_base_url(base_url)

            for entry_idx, entry in enumerate(entries):
                entry_name = entry.get("name", f"entry_{entry_idx}")
                entry_url = entry.get("url", "")
                stats["entries_total"] += 1

                await ctx.logger.step("phase1", f"  入口: {entry_name}")

                # 解析 config（信源级 + entry 级覆盖）
                resolved = resolve_config(db_config, entry) if db_config else None

                # 打开页面
                try:
                    await page.goto(
                        entry_url, wait_until="domcontentloaded", timeout=60000
                    )
                    await asyncio.sleep(3)
                except Exception as e:
                    await ctx.logger.error("phase1", f"  页面加载失败: {e}")
                    stats["entries_skipped"] += 1
                    continue

                # Phase 1: Config 解析 / 探索
                list_config = resolved["list"] if resolved else None
                pagination_config = (
                    resolved.get("pagination") if resolved else None
                )
                detail_config = resolved.get("detail") if resolved else None

                items: list[dict] = []
                if list_config:
                    items = await try_extract_items(page, list_config)

                # Config 缺失或失效 → 探索 Agent
                if not items:
                    stats["explore_triggered"] += 1
                    await ctx.logger.step(
                        "explorer", f"  触发探索 Agent: {entry_name}"
                    )
                    new_config = await explore_list(
                        page, source_name, base_url, explore_retries
                    )
                    if new_config:
                        stats["explore_success"] += 1
                        entry_resolved = resolve_config(
                            {"configs": new_config, "entries": []}, entry
                        )
                        list_config = entry_resolved["list"]
                        pagination_config = entry_resolved.get("pagination")
                        detail_config = entry_resolved.get("detail")
                        items = await try_extract_items(page, list_config)
                    else:
                        stats["explore_failed"] += 1
                        await ctx.logger.error(
                            "explorer", f"  探索失败，跳过: {entry_name}"
                        )
                        stats["entries_skipped"] += 1
                        continue

                # Phase 2: 翻页采集
                page_items = list(items)
                for page_num in range(1, max_pages):
                    await _rate_limit(rate_limit_ms)

                    # 日期过滤：所有 items 都早于 start_date → 停止翻页
                    dates = [
                        it.get("date") for it in page_items if it.get("date")
                    ]
                    if dates and all(d < start_date for d in dates):
                        break

                    # 翻页
                    if not await go_next_page(page, pagination_config):
                        break

                    await ctx.logger.step(
                        "phase2",
                        f"  翻页: {entry_name} 第{page_num + 1}页",
                    )

                    new_items = await try_extract_items(page, list_config)
                    if not new_items:
                        break

                    page_items.extend(new_items)

                    await ctx.logger.step(
                        "phase2",
                        f"  {entry_name} 第{page_num + 1}页: "
                        f"采集 {len(new_items)} 条",
                    )

                # 日期范围过滤
                for it in page_items:
                    d = it.get("date")
                    if d and (d < start_date or d > end_date):
                        continue
                    it["source_name"] = source_name
                    it["detail_config"] = detail_config
                    all_items.append(it)

                stats["items_crawled"] += len(page_items)
                await ctx.logger.step(
                    "phase2", f"  {entry_name}: 采集 {len(page_items)} 条"
                )

            # 信源间延迟
            if src_idx < len(sources) - 1:
                await asyncio.sleep(source_switch_ms / 1000)

        # ── Phase 3: URL 去重 ──
        await ctx.logger.step("phase3", f"URL 去重: {len(all_items)} → ...")
        all_items = await _dedup_urls(ctx.db, all_items)
        stats["items_after_dedup"] = len(all_items)
        await ctx.logger.step("phase3", f"去重后: {len(all_items)} 条")

        # ── Phase 4: 粗筛 ──
        await ctx.logger.step("phase4", f"粗筛: {len(all_items)} 条...")
        passed_items = await coarse_screen(
            all_items, start_date, end_date, preference, coarse_batch
        )
        stats["items_coarse_pass"] = len(passed_items)
        stats["items_coarse_reject"] = len(all_items) - len(passed_items)
        await ctx.logger.step(
            "phase4",
            f"粗筛: pass={len(passed_items)}, "
            f"reject={stats['items_coarse_reject']}",
        )

        # ── Phase 5: 正文提取 ──
        await ctx.logger.step(
            "phase5", f"正文提取: {len(passed_items)} 条..."
        )
        for it in passed_items:
            url = it.get("url", "")
            if not url.startswith("http"):
                continue

            await _rate_limit(rate_limit_ms)
            try:
                await page.goto(
                    url, wait_until="domcontentloaded", timeout=60000
                )
                await asyncio.sleep(2)
            except Exception:
                continue

            detail_cfg = it.get("detail_config")
            detail = await try_extract_detail(page, detail_cfg)

            if not detail or not detail.get("content"):
                # 探索 Agent detail 模式
                detail_cfg_new = await explore_detail(
                    page, url, explore_retries
                )
                if detail_cfg_new:
                    detail = await try_extract_detail(page, detail_cfg_new)

            if detail:
                it["content"] = detail.get("content", "")
                it["detail_title"] = detail.get("title", it.get("title", ""))
                if detail.get("date"):
                    it["date"] = detail["date"]
                it["source_text"] = detail.get("source", "")

        # 过滤掉没有正文的
        with_content = [it for it in passed_items if it.get("content")]
        await ctx.logger.step(
            "phase5",
            f"正文提取完成: {len(with_content)}/{len(passed_items)}",
        )

        # ── Phase 6: 细筛 ──
        await ctx.logger.step(
            "phase6", f"细筛: {len(with_content)} 条..."
        )
        sem = asyncio.Semaphore(fine_concurrency)

        async def _fine_one(it: dict) -> dict | None:
            async with sem:
                return await fine_screen(it, start_date, end_date)

        fine_tasks = [_fine_one(it) for it in with_content]
        fine_results = await asyncio.gather(
            *fine_tasks, return_exceptions=True
        )

        docs_to_insert: list[dict] = []
        for it, result in zip(with_content, fine_results):
            if isinstance(result, Exception) or result is None:
                stats["items_fine_reject"] += 1
                continue
            stats["items_fine_pass"] += 1
            cat = result.get("category", "未知")
            stats["categories"][cat] = stats["categories"].get(cat, 0) + 1
            docs_to_insert.append(
                {
                    "category": cat,
                    "title": it.get("detail_title", it.get("title", "")),
                    "content": it.get("content", ""),
                    "digest": result.get("digest", ""),
                    "insight": result.get("insight", ""),
                    "link_url": it.get("url", ""),
                    "doc_date": result.get(
                        "doc_date", it.get("date", start_date)
                    ),
                    "website_name": it.get("source_name", ""),
                    "score": result.get("score"),
                    "score_reason": result.get("score_reason", ""),
                }
            )

        await ctx.logger.step(
            "phase6",
            f"细筛: pass={stats['items_fine_pass']}, "
            f"reject={stats['items_fine_reject']}",
        )

    # ── Phase 7: 入库 + 统计（浏览器已关闭）──
    await ctx.logger.step("phase7", f"入库: {len(docs_to_insert)} 条...")
    inserted = await _insert_documents(ctx.db, docs_to_insert)
    stats["items_inserted"] = inserted
    await ctx.logger.step("phase7", f"入库完成: {inserted} 条")

    return PipelineResult(success=True, summary=stats)


# ── Pipeline 注册 ──
@register_pipeline(
    name="news.collector",
    display_name="资讯采集",
    description="采集白名单信源的资讯列表，经粗筛/细筛后入素材库",
    trigger_modes=["cron", "api", "manual"],
    version="1.0.0",
    config_schema={
        "type": "object",
        "properties": {
            "sources": {
                "type": "array",
                "description": "信源列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "信源名称",
                        },
                        "base_url": {
                            "type": "string",
                            "description": "信源根域名",
                        },
                        "entries": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "url": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
            "start_date": {
                "type": "string",
                "description": "开始日期 YYYY-MM-DD",
            },
            "end_date": {
                "type": "string",
                "description": "结束日期 YYYY-MM-DD",
            },
            "preference": {
                "type": "string",
                "description": "查询偏好（可选）",
            },
            "headless": {
                "type": "boolean",
                "default": True,
                "description": "无头模式",
            },
            "max_pages": {"type": "integer", "default": 50},
            "coarse_batch_size": {"type": "integer", "default": 20},
            "fine_concurrency": {"type": "integer", "default": 3},
            "explore_max_retries": {"type": "integer", "default": 3},
            "rate_limit_ms": {"type": "integer", "default": 2000},
            "source_switch_delay_ms": {"type": "integer", "default": 5000},
        },
        "required": ["sources", "start_date", "end_date"],
    },
)
class NewsCollectorPipeline(BasePipeline):
    async def execute(
        self, config: dict, ctx: ExecutionContext
    ) -> PipelineResult:
        config.setdefault("headless", True)
        config.setdefault("max_pages", _DEFAULT_MAX_PAGES)
        config.setdefault("coarse_batch_size", _DEFAULT_COARSE_BATCH)
        config.setdefault("fine_concurrency", _DEFAULT_FINE_CONCURRENCY)
        config.setdefault("explore_max_retries", _DEFAULT_EXPLORE_RETRIES)
        config.setdefault("rate_limit_ms", _DEFAULT_RATE_LIMIT_MS)
        config.setdefault("source_switch_delay_ms", _DEFAULT_SOURCE_SWITCH_MS)

        try:
            return await _run_pipeline(config, ctx)
        except Exception as e:
            await ctx.logger.error("execute", f"Pipeline 异常: {e}")
            return PipelineResult(success=False, error=str(e))
