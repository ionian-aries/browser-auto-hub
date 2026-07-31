"""详情流式管道 — per-item worker: fetch → 细筛 → UPDATE/DELETE。

DB 写走 pipeline 业务 session、日志由 DbStepLogger 独立 session 即时落库；
所有业务写操作在 log.lock 内串行；per-item commit 保证单条耐久
（对齐 oa forward 的 mid-run commit 先例）。
"""
from __future__ import annotations

import asyncio
import re
import time

from playwright.async_api import Page

from . import materials, screen
from .collect import _parse_date


async def detail_pipeline(
    items: list[dict],
    sources: list[dict],
    config: dict,
    page: Page,
    fine_prompt: str,
    session,
    llm,
    log,
) -> dict:
    """per-item 流式处理: fetch_detail → 校验 content → fine_screen → UPDATE/DELETE。

    返回统计: {"processed", "passed", "rejected", "kept_existing", "failed",
               "outcomes": [{title, url, decision, db_id, is_new,
                             reason?, category?, score?}, ...]}
    outcomes 供 summary 阶段分组归纳（decision: pass/reject/kept/failed）；
    result_summary 只落留存行（pass/kept），过滤在 harvest 汇总处完成。
    """
    stats = {"processed": 0, "passed": 0, "rejected": 0, "failed": 0, "kept_existing": 0}
    outcomes: list[dict] = []
    if not items:
        stats["outcomes"] = outcomes
        return stats

    browser_tabs = min(max(config.get("browser_tabs", 5), 1), 5)
    page_timeout = config.get("page_load_timeout", 120000)
    max_retries = config.get("retry_max", 2)
    min_content_chars = config.get("min_content_chars", 100)
    max_content_chars = config.get("max_content_chars", 15000)
    fine_model = config.get("fine_model") or llm.setting("llm_fine_model")

    # 构建 source_name → detail 配置映射（支持数组）
    detail_map: dict[str, list[dict]] = {}
    for source in sources:
        name = source.get("source_name", "")
        detail_cfg = source.get("configs", {}).get("detail")
        if not detail_cfg:
            continue
        # 兼容单个 dict 或数组
        detail_map[name] = detail_cfg if isinstance(detail_cfg, list) else [detail_cfg]

    semaphore = asyncio.Semaphore(browser_tabs)
    # LLM 并发上限独立于浏览器并发：细筛不占 tab，但需防 API 限流
    llm_sem = asyncio.Semaphore(config.get("llm_concurrency", 5))

    async def _worker(it: dict) -> None:
        """单条 worker: 校验 → fetch(重试) → 校验 content → fine → UPDATE/DELETE。"""
        title = it.get("title", "")[:30]
        url = it.get("link_url", "")
        db_id = it.get("db_id")

        # 校验 db_id
        if not db_id:
            await log.error("detail", f"✗ {title}  (无 db_id，跳过)")
            stats["failed"] += 1
            outcomes.append({"title": it.get("title", ""), "url": url, "decision": "failed", "reason": "无 db_id", "db_id": db_id, "is_new": it.get("is_new", True)})
            return

        # tab 信号量只包住 fetch（浏览器操作）；细筛 LLM 不占浏览器并发位
        t_fetch0 = time.monotonic()
        async with semaphore:
            # fetch_detail 带重试
            fetched = False
            for attempt in range(max_retries + 1):
                try:
                    result = await _fetch_detail(
                        it, detail_map, page_timeout, page, log
                    )
                    if result is not None:
                        fetched = True
                        break
                    # result=None 表示选择器未匹配，重试可能也无意义
                    # 但仍重试（页面可能加载不完整）
                    if attempt < max_retries:
                        await log.warn(
                            "detail",
                            f"↻ {title}  fetch 未成功，重试 {attempt + 1}/{max_retries}",
                        )
                except Exception as e:
                    if attempt < max_retries:
                        await log.warn(
                            "detail",
                            f"↻ {title}  fetch 异常: {e}，重试 {attempt + 1}/{max_retries}",
                        )
                    else:
                        await log.error(
                            "detail", f"✗ {title}  fetch 失败（重试耗尽）: {e}"
                        )

        if not fetched:
            stats["failed"] += 1
            outcomes.append({"title": it.get("title", ""), "url": url, "decision": "failed", "reason": "fetch 未成功", "db_id": db_id, "is_new": it.get("is_new", True)})
            await log.error("detail", f"✗ {title}\n  决策: fetch 未成功（重试耗尽）\n  链接: {url}")
            return
        t_fetch = time.monotonic() - t_fetch0

        # 校验 content 非空
        if not it.get("content"):
            await log.warn("detail", f"✗ {title}\n  决策: 正文为空\n  链接: {url}")
            stats["failed"] += 1
            outcomes.append({"title": it.get("title", ""), "url": url, "decision": "failed", "reason": "正文为空", "db_id": db_id, "is_new": it.get("is_new", True)})
            return

        # fine_screen（正文过短 → 硬门槛直接判信息量不足，不调 LLM）
        hard_gate = len(it["content"]) < min_content_chars
        t_fine0 = time.monotonic()
        if hard_gate:
            fine_result = {"decision": "reject", "reject_reason": "信息量不足"}
        else:
            try:
                # 超长正文截断仅作用于 LLM 输入（浅拷贝），DB 保留全文
                async with llm_sem:
                    fine_result = await screen.fine_screen(
                        {**it, "content": it["content"][:max_content_chars]},
                        fine_prompt, fine_model, llm, log,
                    )
            except Exception as e:
                await log.error("detail", f"✗ {title}\n  决策: 细筛异常 {e}\n  链接: {url}")
                stats["failed"] += 1
                outcomes.append({"title": it.get("title", ""), "url": url, "decision": "failed", "reason": f"细筛异常 {e}", "db_id": db_id, "is_new": it.get("is_new", True)})
                return
        t_fine = time.monotonic() - t_fine0
        if hard_gate:
            cost = f"fetch {t_fetch:.1f}s / 细筛 硬门槛直拒（正文<{min_content_chars}字）"
        else:
            cost = f"fetch {t_fetch:.1f}s / 细筛 {t_fine:.1f}s"
        debug_data = {
            "result": fine_result,
            "fetch_seconds": round(t_fetch, 1),
            "fine_seconds": round(t_fine, 1),
        }

        decision = fine_result.get("decision", "reject")

        if decision == "pass":
            it["category"] = fine_result.get("category", "")
            it["digest"] = fine_result.get("digest", "")
            it["insight"] = fine_result.get("insight", "")
            it["score"] = fine_result.get("score")
            it["score_reason"] = fine_result.get("score_reason", "")
            if "doc_date" in fine_result:
                it["doc_date"] = fine_result["doc_date"]

            async with log.lock:
                try:
                    await materials.update_fine(session, it)
                    await session.commit()
                    stats["passed"] += 1
                    outcomes.append({
                        "title": it.get("title", ""), "url": url, "decision": "pass",
                        "category": it["category"], "score": it["score"],
                        "db_id": db_id, "is_new": it.get("is_new", True),
                    })
                    await log.raw.step(
                        "detail",
                        f"✓ {title}\n"
                        f"  决策: pass [{it['category']}] 评分 {it['score']} | {cost}\n"
                        f"  链接: {url}",
                        "info",
                        debug_data,
                    )
                except Exception as e:
                    await session.rollback()
                    stats["failed"] += 1
                    outcomes.append({
                        "title": it.get("title", ""), "url": url, "decision": "failed",
                        "reason": f"UPDATE 失败 {e}",
                        "db_id": db_id, "is_new": it.get("is_new", True),
                    })
                    await log.raw.step(
                        "detail", f"✗ {title}\n  决策: UPDATE 失败 {e}\n  链接: {url}", "error"
                    )
        else:
            reject_reason = fine_result.get("reject_reason", "")
            if it.get("is_new", True):
                # 本次新插入的行 → 删除
                async with log.lock:
                    try:
                        await materials.delete_rows(session, [db_id])
                        await session.commit()
                        stats["rejected"] += 1
                        outcomes.append({
                            "title": it.get("title", ""), "url": url, "decision": "reject",
                            "reason": reject_reason,
                            "db_id": db_id, "is_new": it.get("is_new", True),
                        })
                        await log.raw.step(
                            "detail",
                            f"✗ {title}\n"
                            f"  决策: reject（{reject_reason}） | {cost}\n"
                            f"  链接: {url}",
                            "info",
                            debug_data,
                        )
                    except Exception as e:
                        await session.rollback()
                        stats["failed"] += 1
                        outcomes.append({
                            "title": it.get("title", ""), "url": url, "decision": "failed",
                            "reason": f"DELETE 失败 {e}",
                            "db_id": db_id, "is_new": it.get("is_new", True),
                        })
                        await log.raw.step(
                            "detail", f"✗ {title}\n  决策: DELETE 失败 {e}\n  链接: {url}", "error"
                        )
            else:
                # force 模式复用的历史行 → 保留旧数据，不删除
                stats["kept_existing"] += 1
                outcomes.append({
                    "title": it.get("title", ""), "url": url, "decision": "kept",
                    "reason": reject_reason,
                    "db_id": db_id, "is_new": it.get("is_new", True),
                })
                await log.warn(
                    "detail",
                    f"⊘ {title}\n"
                    f"  决策: reject（{reject_reason}，保留历史行） | {cost}\n"
                    f"  链接: {url}",
                    debug_data,
                )

        stats["processed"] += 1

    tasks = [_worker(it) for it in items]
    await asyncio.gather(*tasks)

    await log.info(
        "detail",
        f"详情流式: {stats['passed']} 通过, "
        f"{stats['rejected']} 拒绝, "
        f"{stats['kept_existing']} 保留历史行, "
        f"{stats['failed']} 失败"
        f"（{browser_tabs} 并发）",
    )
    stats["outcomes"] = outcomes
    return stats


async def _fetch_detail(
    item: dict,
    detail_map: dict[str, list[dict]],
    timeout: int,
    parent_page: Page,
    log,
) -> dict | None:
    """打开新 tab，提取正文，关闭 tab。返回 item 或 None。

    支持多模板探测: detail 配置为数组，依次尝试每个 config 的 content selector，
    首个匹配即使用（短超时 3s 快速跳过不匹配的模板）。
    """
    source_name = item.get("website_name", "")
    configs = detail_map.get(source_name)

    if not configs:
        await log.warn("detail", f"跳过（无 detail 配置）: {source_name}")
        return None

    ctx = parent_page.context
    tab = await ctx.new_page()
    try:
        await tab.goto(item["link_url"], wait_until="commit", timeout=timeout)

        # 逐个 config 探测正文容器（短超时快速跳过）
        matched_cfg = None
        for cfg in configs:
            sel = cfg.get("fields", {}).get("content", "")
            if not sel:
                continue
            try:
                await tab.wait_for_selector(sel, timeout=3000)
                matched_cfg = cfg
                break
            except Exception:
                continue

        if not matched_cfg:
            await log.warn(
                "detail", f"所有正文容器均未匹配 — {item['title'][:30]}"
            )
            return None

        fields = matched_cfg.get("fields", {})
        content_sel = fields.get("content", "")
        title_sel = fields.get("title", "")
        date_sel = fields.get("date", "")

        # 提取正文
        content = ""
        if content_sel:
            loc = tab.locator(content_sel)
            if await loc.count() > 0:
                content = (await loc.first.inner_text()).strip()

        # 提取详情页标题（覆盖列表标题，更准确）
        if title_sel:
            loc = tab.locator(title_sel)
            if await loc.count() > 0:
                t = (await loc.first.inner_text()).strip()
                if t:
                    item["title"] = t

        # 提取日期（详情页日期更准确，覆盖列表日期）
        if date_sel:
            loc = tab.locator(date_sel)
            if await loc.count() > 0:
                d = _parse_date(
                    (await loc.first.inner_text()).strip(), item["link_url"]
                )
                if d:
                    item["doc_date"] = d

        # 提取来源（可选，用于细筛信源权威性评分）
        source_sel = fields.get("source", "")
        if source_sel:
            loc = tab.locator(source_sel)
            if await loc.count() > 0:
                item["source"] = _clean_source(
                    (await loc.first.inner_text()).strip()
                )

        item["content"] = content
        return item

    except Exception as e:
        await log.warn("detail", f"提取失败: {item.get('title', '')[:30]} — {e}")
        return None

    finally:
        await tab.close()


# ── 来源清洗 ──
def _clean_source(raw: str) -> str:
    """去除 '来源:' / '来源：' 前缀，返回纯名称。"""
    return re.sub(r"^来源[:：]\s*", "", raw).strip()
