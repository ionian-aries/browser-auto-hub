"""资讯采集 Pipeline — 主编排 + 浏览器管理 + 存储 + LLM 接入。

替换来也RPA资讯采集服务，实现多信源遍历 → 粗筛 → 细筛 → 入库的全流程。
注册到 engine pipeline registry，支持 manual / cron / api 三种触发模式。

数据库表：ganghang_materials（对齐来也 RPA schema）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncIterator
from urllib.parse import urljoin

from playwright.async_api import Page, async_playwright

from engine.base import BasePipeline, PipelineResult
from engine.context import ExecutionContext
from engine.logger import StepLogger
from engine.pipelines.news.config_loader import load_config, merge_entry_config
from engine.pipelines.news.crawler import Crawler
from engine.pipelines.news.explorer import Explorer
from engine.pipelines.news.screener import Screener
from engine.registry import register_pipeline

logger = logging.getLogger(__name__)


# ─── LLM 调用 ───


def _create_ll_caller(settings) -> callable | None:
    """根据 settings 创建 LLM 调用函数。

    返回 async callable(system: str, user: str) -> str | None。
    settings.llm_api_key 为空时返回 None（降级为跳过LLM环节）。
    """
    api_key = getattr(settings, "llm_api_key", "")
    if not api_key:
        logger.warning("LLM_API_KEY 未配置，粗筛/细筛/探索Agent将降级跳过")
        return None

    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=getattr(settings, "llm_api_base_url", "https://api.openai.com/v1"),
    )
    model = getattr(settings, "llm_model", "gpt-4o-mini")

    async def call_llm(system: str, user: str) -> str | None:
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.1,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error("LLM call failed: %s", e)
            return None

    return call_llm


# ─── 浏览器生命周期 ───


def _consume_close_exception(task: asyncio.Task) -> None:
    if not task.cancelled():
        task.exception()


@asynccontextmanager
async def news_browser(config: dict) -> AsyncIterator[Page]:
    """启动 Chromium，yield 一个 page，退出时关闭。"""
    headless = config.get("headless", True)
    close_browser = config.get("close_browser", True)
    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch(headless=headless)
        try:
            context = await browser.new_context()
            page = await context.new_page()
            yield page
        finally:
            if close_browser:
                close_task = asyncio.ensure_future(browser.close())
                close_task.add_done_callback(_consume_close_exception)
                try:
                    await asyncio.shield(close_task)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass
    finally:
        if close_browser:
            try:
                await pw.stop()
            except Exception:
                pass


# ─── 存储操作（对齐 ganghang_materials 表，与来也 RPA schema 一致） ───


async def deduplicate(articles: list[dict], db) -> list[dict]:
    """URL去重：查 ganghang_materials 表，返回不存在的文章。"""
    if not articles:
        return []
    urls = [a["url"] for a in articles if a.get("url")]
    if not urls:
        return []
    from sqlalchemy import text
    # 分批查询，避免 IN 列表过长
    existing = set()
    batch_size = 500
    for i in range(0, len(urls), batch_size):
        batch = urls[i:i + batch_size]
        placeholders = ", ".join([f":url_{j}" for j in range(len(batch))])
        params = {f"url_{j}": url for j, url in enumerate(batch)}
        result = await db.execute(
            text(f"SELECT link_url FROM ganghang_materials WHERE link_url IN ({placeholders})"),
            params,
        )
        existing.update(row[0] for row in result.fetchall())
    return [a for a in articles if a.get("url") not in existing]


async def save_material(
    article: dict,
    detail: dict,
    fine_result: dict,
    website_name: str,
    db,
) -> None:
    """单篇入库：写入 ganghang_materials 表。

    字段对齐来也 RPA schema：
    - category: 细筛分类（中文，如"政策速读""热点分析"）
    - title: 原始标题
    - content: 正文全文
    - digest: 成稿正文（细筛生成）
    - insight: 战略参考（细筛生成）
    - link_url: 原文URL
    - doc_date: 发布日期
    - website_name: 信源名称
    - score: 评分（0-10，一位小数）
    - score_reason: 评分理由
    """
    from sqlalchemy import text
    await db.execute(
        text("""
            INSERT INTO ganghang_materials
            (category, title, content, digest, insight, link_url,
             doc_date, website_name, score, score_reason)
            VALUES
            (:category, :title, :content, :digest, :insight, :link_url,
             :doc_date, :website_name, :score, :score_reason)
        """),
        {
            "category": fine_result.get("category", ""),
            "title": article.get("title", ""),
            "content": detail.get("content", ""),
            "digest": fine_result.get("digest", ""),
            "insight": fine_result.get("insight", ""),
            "link_url": article.get("url", ""),
            "doc_date": fine_result.get("doc_date") or article.get("date", ""),
            "website_name": website_name,
            "score": fine_result.get("score"),
            "score_reason": fine_result.get("score_reason", ""),
        },
    )
    await db.flush()


# ─── 主 Pipeline ───


@register_pipeline(
    name="news.collector",
    display_name="资讯采集",
    description="资讯类信息采集：多信源遍历 → 粗筛 → 细筛 → 入库素材库",
    trigger_modes=["cron", "api", "manual"],
    version="1.0.0",
    config_schema={
        "type": "object",
        "properties": {
            "sources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "指定信源名称列表，为空则采集全部已启用信源",
            },
            "date_start": {
                "type": "string",
                "description": "起始日期 YYYY-MM-DD",
            },
            "date_end": {
                "type": "string",
                "description": "结束日期 YYYY-MM-DD",
            },
            "preferences": {
                "type": "string",
                "default": "",
                "description": "用户额外查询偏好，补充粗筛/细筛的筛选标准",
            },
            "coarse_batch_size": {
                "type": "integer",
                "default": 20,
                "description": "粗筛每批文章数",
            },
            "llm_concurrency": {
                "type": "integer",
                "default": 3,
                "description": "LLM并发请求数（Semaphore限流）",
            },
            "headless": {
                "type": "boolean",
                "default": False,
                "description": "是否无头模式运行浏览器",
            },
        },
        "required": ["date_start", "date_end"],
    },
)
class NewsCollectorPipeline(BasePipeline):
    """资讯采集 Pipeline。

    执行流程：
    1. 加载 config.json 信源配置，按用户指定过滤信源
    2. 遍历每个信源的每个 entry（起始页面）
    3. 用 config 采集列表页，翻页到日期边界
    4. config 缺失或采集失败 → 探索Agent生成/修复config
    5. URL去重（查 ganghang_materials 表）
    6. 粗筛：批量LLM分类（A/B/C），过滤C类
    7. 逐篇打开详情页提取正文
    8. 细筛：逐篇LLM执行 GATE→CLASSIFY→GENERATE→SCORE
    9. pass 的文章入库 ganghang_materials
    """

    async def execute(
        self, config: dict, ctx: ExecutionContext
    ) -> PipelineResult:
        config.setdefault("coarse_batch_size", 20)
        config.setdefault("llm_concurrency", 3)
        config.setdefault("headless", False)
        config.setdefault("preferences", "")

        stats = {
            "crawled": 0,
            "deduplicated": 0,
            "coarse_passed": 0,
            "fine_passed": 0,
            "fine_rejected": 0,
            "explorer_invoked": 0,
            "errors": 0,
        }

        # 1. 加载配置
        try:
            sources_config = load_config()
        except Exception as e:
            return PipelineResult(success=False, error=f"配置加载失败: {e}")

        target_sources = _filter_sources(sources_config, config.get("sources"))
        if not target_sources:
            return PipelineResult(success=True, summary={"message": "无可采集信源"})

        date_start = config["date_start"]
        date_end = config["date_end"]
        preferences = config["preferences"]

        # 2. 创建 LLM caller
        llm_caller = _create_ll_caller(ctx.settings)

        await ctx.logger.step(
            "init",
            f"信源: {len(target_sources)}个, 日期: {date_start} ~ {date_end}, "
            f"LLM: {'已配置' if llm_caller else '未配置(降级模式)'}",
        )

        # 3. 启动浏览器
        async with news_browser(config) as page:
            crawler = Crawler(page, ctx.logger)
            explorer = Explorer(page, ctx.logger, llm_caller=llm_caller)
            screener = Screener(
                ctx.logger,
                concurrency=config["llm_concurrency"],
                llm_caller=llm_caller,
            )

            for source in target_sources:
                for entry in source.get("entries", []):
                    try:
                        entry_label = f"{source['source_name']}/{entry['entry_name']}"
                        await ctx.logger.step("navigate", f"正在采集: {entry_label}")

                        # 导航到起始页
                        await page.goto(entry["url"], timeout=60000, wait_until="domcontentloaded")
                        await page.wait_for_timeout(3000)

                        # 合并配置（信源级 + entry级覆盖）
                        merged = merge_entry_config(
                            source.get("configs", {}), entry.get("configs")
                        )

                        # 采集列表页（翻页到日期边界）
                        all_items = []
                        page_count = 0

                        while True:
                            page_count += 1
                            items = await crawler.extract_list(merged)

                            if not items:
                                # config 采集失败 → 尝试探索Agent
                                if page_count == 1:
                                    stats["explorer_invoked"] += 1
                                    new_config = await explorer.explore(
                                        source["source_name"],
                                        entry["entry_name"],
                                        entry["url"],
                                    )
                                    if new_config:
                                        merged = new_config
                                        items = await crawler.extract_list(merged)

                                if not items:
                                    await ctx.logger.warn(
                                        "crawl", f"无内容，跳过: {entry_label}"
                                    )
                                    break

                            # URL 补全（相对路径 → 绝对路径）
                            for item in items:
                                if item.get("url") and not item["url"].startswith("http"):
                                    item["url"] = urljoin(entry["url"], item["url"])

                            all_items.extend(items)
                            stats["crawled"] += len(items)

                            # 日期边界检查
                            if _earliest_date_before(items, date_start):
                                await ctx.logger.step(
                                    "crawl",
                                    f"到达日期边界，停止翻页: {entry_label}",
                                )
                                break

                            # 翻页
                            if not await crawler.has_next_page(merged):
                                break
                            if not await crawler.goto_next_page(merged):
                                break

                        await ctx.logger.step(
                            "crawl",
                            f"采集完成: {entry_label} — {len(all_items)}条, {page_count}页",
                        )

                        # 日期范围过滤
                        filtered = _filter_by_date_range(all_items, date_start, date_end)
                        if not filtered:
                            await ctx.logger.step(
                                "filter", f"日期过滤后无内容: {entry_label}"
                            )
                            continue

                        # URL去重
                        new_items = await deduplicate(filtered, ctx.db)
                        stats["deduplicated"] += len(new_items)

                        if not new_items:
                            await ctx.logger.step(
                                "dedup", f"全部已存在，跳过: {entry_label}"
                            )
                            continue

                        await ctx.logger.step(
                            "dedup",
                            f"新增{len(new_items)}条 (过滤前{len(filtered)}条)",
                        )

                        # 粗筛（批量）
                        coarse_results = await screener.coarse_screen(
                            new_items, preferences, config["coarse_batch_size"]
                        )
                        passed = [
                            r for r in coarse_results if r.get("category") in ("A", "B")
                        ]
                        stats["coarse_passed"] += len(passed)
                        await ctx.logger.step(
                            "coarse",
                            f"粗筛通过{len(passed)}/{len(new_items)}条: {entry_label}",
                        )

                        if not passed:
                            continue

                        # 逐篇：详情页提取 + 细筛
                        for article in passed:
                            try:
                                await page.goto(article["url"], timeout=60000, wait_until="domcontentloaded")
                                await page.wait_for_timeout(2000)

                                detail = await crawler.extract_detail(merged)
                                if not detail.get("content"):
                                    await ctx.logger.warn(
                                        "detail",
                                        f"正文为空: {article['title'][:30]}",
                                    )
                                    continue

                                # 细筛：GATE→CLASSIFY→GENERATE→SCORE
                                fine_result = await screener.fine_screen(
                                    article, detail, preferences,
                                    start_date=date_start,
                                    end_date=date_end,
                                )

                                decision = fine_result.get("decision", "reject")
                                if decision == "pass":
                                    await save_material(
                                        article=article,
                                        detail=detail,
                                        fine_result=fine_result,
                                        website_name=source["source_name"],
                                        db=ctx.db,
                                    )
                                    stats["fine_passed"] += 1
                                    await ctx.logger.step(
                                        "fine",
                                        f"入库: {article['title'][:40]} "
                                        f"[{fine_result.get('category', '')}] "
                                        f"评分{fine_result.get('score', '')}",
                                    )
                                else:
                                    stats["fine_rejected"] += 1
                                    reason = fine_result.get("reject_reason", "未知")
                                    await ctx.logger.step(
                                        "fine",
                                        f"拒绝: {article['title'][:30]} — {reason}",
                                    )

                            except Exception as e:
                                stats["errors"] += 1
                                await ctx.logger.error(
                                    "detail",
                                    f"详情处理失败: {article.get('url', '?')} — {e}",
                                )
                                continue

                    except Exception as e:
                        stats["errors"] += 1
                        await ctx.logger.error(
                            "entry",
                            f"采集异常: {source['source_name']}/{entry.get('entry_name', '?')} — {e}",
                        )
                        continue

        return PipelineResult(success=True, summary=stats)


# ─── 辅助函数 ───


def _filter_sources(config: list[dict], source_names: list[str] | None) -> list[dict]:
    """按用户指定的信源名称过滤，为空则返回全部。"""
    if not source_names:
        return config
    return [s for s in config if s.get("source_name") in source_names]


def _earliest_date_before(items: list[dict], date_start: str) -> bool:
    """判断列表中是否有文章的日期早于 date_start。"""
    for item in items:
        d = item.get("date", "")
        if d and d < date_start:
            return True
    return False


def _filter_by_date_range(
    items: list[dict], date_start: str, date_end: str
) -> list[dict]:
    """按日期范围过滤，保留 date_start <= date <= date_end 的文章。"""
    return [
        i
        for i in items
        if i.get("date") and date_start <= i["date"] <= date_end
    ]
